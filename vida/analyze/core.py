"""Visual analysis: watch the video in parallel clips, then synthesize.

Short videos go to the model whole. Longer ones are cut into overlapping clips
that are analysed concurrently, then a reasoning model stitches the per-clip
descriptions back into one narrative. When a clip fails as video — too large,
rejected by the provider, timed out — it is retried as still frames, which is
far cheaper and almost always succeeds.
"""

from __future__ import annotations

import asyncio
import os
import shutil

from vida.analyze.prompts import build_frames_prompt, build_synthesis_prompt, build_video_prompt
from vida.config import AnalysisConfig
from vida.errors import AnalysisError
from vida.llm import OpenRouterClient, strip_reasoning
from vida.media.frames import extract_frames
from vida.media.video import VideoSegment, segment_video
from vida.types import Analysis, MediaInfo, SegmentAnalysis, Transcript

__all__ = ["analyze_video"]


def _excerpt_for(transcript: Transcript | None, start: float, end: float) -> str | None:
    """The transcript text spoken between ``start`` and ``end``."""
    if transcript is None or not transcript.segments:
        return None
    spoken = [
        segment.text
        for segment in transcript.segments
        if segment.end > start and segment.start < end
    ]
    if not spoken:
        return None
    excerpt = " ".join(spoken).strip()
    # Keep the payload sane on dense, fast-talking clips.
    return excerpt[:2000]


async def _analyze_clip(
    client: OpenRouterClient,
    segment: VideoSegment,
    config: AnalysisConfig,
    semaphore: asyncio.Semaphore,
    *,
    user_query: str | None,
    transcript: Transcript | None,
    work_dir: str,
    delete_after: bool,
) -> SegmentAnalysis:
    excerpt = _excerpt_for(transcript, segment.start, segment.end)
    mode = "video"
    content = build_video_prompt(
        segment.path,
        start=segment.start,
        end=segment.end,
        user_query=user_query,
        transcript_excerpt=excerpt,
    )
    frames_dir = os.path.join(work_dir, f"frames_{segment.index:04d}")
    last_error = "unknown error"

    try:
        for attempt in range(max(config.retries, 1)):
            try:
                async with semaphore:
                    text = await asyncio.wait_for(
                        client.complete(
                            content,
                            model=config.model,
                            temperature=config.temperature,
                            reasoning=False,
                            timeout=config.timeout,
                        ),
                        timeout=config.timeout + 30,
                    )
                cleaned = strip_reasoning(text)
                if cleaned:
                    return SegmentAnalysis(
                        index=segment.index,
                        status="ok",
                        analysis=cleaned,
                        mode=mode,
                        start=segment.start,
                        end=segment.end,
                    )
                last_error = "model returned an empty response"

            except Exception as exc:  # noqa: BLE001 - recorded and retried below
                last_error = "timed out" if isinstance(exc, asyncio.TimeoutError) else str(exc)

            # First failure on the video path: drop to frames, which are smaller
            # and accepted by models that reject inline video entirely.
            if mode == "video":
                try:
                    frame_paths = await extract_frames(
                        segment.path,
                        frames_dir,
                        count=config.frames_per_segment,
                        duration=segment.duration,
                    )
                except Exception as exc:  # noqa: BLE001
                    return SegmentAnalysis(
                        index=segment.index,
                        status="error",
                        analysis=f"{last_error}; frame fallback also failed: {exc}",
                        mode="failed",
                        start=segment.start,
                        end=segment.end,
                    )
                if frame_paths:
                    mode = "frames"
                    content = build_frames_prompt(
                        frame_paths,
                        start=segment.start,
                        end=segment.end,
                        user_query=user_query,
                        transcript_excerpt=excerpt,
                    )
                    continue

            if attempt < config.retries - 1:
                await asyncio.sleep(2**attempt)

        return SegmentAnalysis(
            index=segment.index,
            status="error",
            analysis=last_error,
            mode="failed",
            start=segment.start,
            end=segment.end,
        )

    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
        if delete_after:
            try:
                os.remove(segment.path)
            except OSError:
                pass


async def _synthesize(
    client: OpenRouterClient,
    results: list[SegmentAnalysis],
    config: AnalysisConfig,
    user_query: str | None,
) -> str:
    usable = [result for result in results if result.status == "ok"]
    if not usable:
        raise AnalysisError(
            "Every clip failed to analyze. First error: "
            + (results[0].analysis if results else "no clips were produced")
        )

    timeline = "\n\n".join(
        f"[{result.start:.0f}s - {result.end:.0f}s]\n{result.analysis}"
        if result.start is not None
        else f"[Clip {result.index + 1}]\n{result.analysis}"
        for result in usable
    )

    text = await client.complete(
        build_synthesis_prompt(timeline, user_query),
        model=config.synthesis_model,
        temperature=config.temperature,
        reasoning=True,
        timeout=config.timeout,
    )
    return strip_reasoning(text)


async def analyze_video(
    media: MediaInfo,
    *,
    client: OpenRouterClient,
    config: AnalysisConfig | None = None,
    user_query: str | None = None,
    transcript: Transcript | None = None,
    work_dir: str,
) -> Analysis:
    """Analyze what a video shows.

    Args:
        media: Probed info for the video.
        client: OpenRouter client used for both clip analysis and synthesis.
        config: Model, concurrency, and segmentation settings.
        user_query: An optional question to focus the analysis on.
        transcript: If available, the transcript is fed to each clip as context,
            which noticeably sharpens the descriptions.
        work_dir: Scratch directory for clips and frames.

    Returns:
        An :class:`~vida.types.Analysis` with a summary and per-clip detail.
    """
    config = config or AnalysisConfig()
    fits_whole = (
        media.size_mb <= config.max_segment_mb and media.duration <= config.max_segment_seconds
    )

    if fits_whole:
        segments = [VideoSegment(media.path, 0.0, media.duration, 0)]
        delete_after = False  # never delete the caller's original file
        concurrency = 1
    else:
        segments = await segment_video(
            media.path,
            media.duration,
            max_mb=config.max_segment_mb,
            max_seconds=config.max_segment_seconds,
            overlap=config.segment_overlap,
            out_dir=work_dir,
        )
        delete_after = True
        concurrency = min(len(segments), max(config.concurrency, 1))

    if not segments:
        raise AnalysisError(f"Could not split {media.path} into analyzable clips.")

    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(
            _analyze_clip(
                client,
                segment,
                config,
                semaphore,
                user_query=user_query,
                transcript=transcript,
                work_dir=work_dir,
                delete_after=delete_after,
            )
            for segment in segments
        )
    )
    results = sorted(results, key=lambda result: result.index)

    # A single clip that succeeded is already the summary; a synthesis pass
    # would just paraphrase it and cost another round trip.
    if len(results) == 1 and results[0].status == "ok" and not user_query:
        summary = results[0].analysis
    else:
        summary = await _synthesize(client, results, config, user_query)

    return Analysis(summary=summary, segments=results, query=user_query, source=media.path)
