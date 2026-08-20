"""The analysis arms under comparison.

All three arms share one skeleton — plan windows, build content, call the model
per window, synthesize — and differ *only* in what goes into the content parts.
That is deliberate: if one arm went through ``analyze_video()`` with its retry
and frame-fallback logic while the others did not, the comparison would measure
the fallback rather than the representation.

For the same reason no arm falls back across modes. A window that fails is
recorded as failed, because "how often does this representation fail" is one of
the things being measured.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from dataclasses import dataclass, field

from vida.analyze.prompts import build_frames_prompt, build_synthesis_prompt, build_video_prompt
from vida.llm import OpenRouterClient, strip_reasoning
from vida.media.ffmpeg import arun, ffmpeg_path
from vida.media.frames import extract_frames
from vida.types import MediaInfo, Transcript

__all__ = ["ARMS", "ArmResult", "WindowResult", "run_arm"]

# Matches vida/media/video.py so the video arm reproduces the shipped path.
_VIDEO_KBPS = 500
_AUDIO_KBPS = 128


@dataclass
class WindowResult:
    index: int
    start: float
    end: float
    status: str  # "ok" | "error"
    text: str
    request_bytes: int = 0


@dataclass
class ArmResult:
    arm: str
    video: str
    frames_per_window: int | None
    window_seconds: float
    summary: str = ""
    windows: list[WindowResult] = field(default_factory=list)
    requests: int = 0
    uploaded_bytes: int = 0
    seconds: float = 0.0
    error: str | None = None

    @property
    def failed_windows(self) -> int:
        return sum(1 for w in self.windows if w.status != "ok")

    def to_dict(self) -> dict:
        return {
            "arm": self.arm,
            "video": self.video,
            "frames_per_window": self.frames_per_window,
            "window_seconds": self.window_seconds,
            "summary": self.summary,
            "windows": [vars(w) for w in self.windows],
            "requests": self.requests,
            "uploaded_bytes": self.uploaded_bytes,
            "seconds": self.seconds,
            "failed_windows": self.failed_windows,
            "error": self.error,
        }


@dataclass
class Window:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)


def plan_windows(duration: float, window_seconds: float, overlap: float) -> list[Window]:
    """Identical windowing for every arm, so they see the same spans."""
    stride = max(window_seconds - overlap, 1.0)
    windows: list[Window] = []
    start, index = 0.0, 0
    while start < duration:
        end = min(start + window_seconds, duration)
        windows.append(Window(index, start, end))
        index += 1
        if end >= duration:
            break
        start += stride
    return windows


# ---------------------------------------------------------------------------
# Media cutting (local, no model involved)
# ---------------------------------------------------------------------------


async def _cut_video(src: str, dest: str, window: Window, timeout: float = 600.0) -> str:
    await arun(
        [
            ffmpeg_path(), "-y",
            "-ss", f"{window.start:.3f}",
            "-t", f"{window.duration:.3f}",
            "-i", src,
            "-vf", "scale=854:-2",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-b:v", f"{_VIDEO_KBPS}k",
            "-c:a", "aac", "-b:a", f"{_AUDIO_KBPS}k",
            "-loglevel", "error",
            dest,
        ],
        timeout=timeout,
    )
    return dest


async def _cut_audio(src: str, dest: str, window: Window, timeout: float = 300.0) -> str:
    """Mono 16 kHz slice of the window, in whatever container ``dest`` implies."""
    await arun(
        [
            ffmpeg_path(), "-y",
            "-ss", f"{window.start:.3f}",
            "-t", f"{window.duration:.3f}",
            "-i", src,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-loglevel", "error",
            dest,
        ],
        timeout=timeout,
    )
    return dest


def _excerpt(transcript: Transcript | None, start: float, end: float) -> str | None:
    """Transcript text spoken inside the window. Mirrors analyze/core.py."""
    if transcript is None or not transcript.segments:
        return None
    spoken = [s.text for s in transcript.segments if s.end > start and s.start < end]
    if not spoken:
        return None
    return " ".join(spoken).strip()[:2000]


def _audio_part(path: str, fmt: str) -> dict:
    """OpenRouter audio content part: base64 payload plus a format tag."""
    with open(path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("utf-8")
    return {"type": "input_audio", "input_audio": {"data": encoded, "format": fmt}}


# ---------------------------------------------------------------------------
# The three content builders — the only place the arms actually differ
# ---------------------------------------------------------------------------


async def _content_video(ctx, window: Window) -> list[dict]:
    """Arm A: one transcoded clip, video and audio together. Today's path."""
    dest = os.path.join(ctx.work_dir, f"w{window.index:04d}.mp4")
    await _cut_video(ctx.media.path, dest, window)
    return build_video_prompt(
        dest,
        start=window.start,
        end=window.end,
        user_query=ctx.query,
        transcript_excerpt=None,
    )


async def _content_frames_text(ctx, window: Window) -> list[dict]:
    """Arm B: stills plus the ASR transcript for the window, as text."""
    frames_dir = os.path.join(ctx.work_dir, f"w{window.index:04d}_frames")
    paths = await _extract_window_frames(ctx, window, frames_dir)
    return build_frames_prompt(
        paths,
        start=window.start,
        end=window.end,
        user_query=ctx.query,
        transcript_excerpt=_excerpt(ctx.transcript, window.start, window.end),
    )


async def _content_frames_audio(ctx, window: Window) -> list[dict]:
    """Arm C: stills plus the raw audio for the window.

    Unlike arm B this needs no transcript, so analysis stays independent of ASR
    and the concurrency in ``process()`` would survive.
    """
    frames_dir = os.path.join(ctx.work_dir, f"w{window.index:04d}_frames")
    paths = await _extract_window_frames(ctx, window, frames_dir)

    audio_path = os.path.join(ctx.work_dir, f"w{window.index:04d}.{ctx.audio_format}")
    await _cut_audio(ctx.media.path, audio_path, window)

    content = build_frames_prompt(
        paths,
        start=window.start,
        end=window.end,
        user_query=ctx.query,
        transcript_excerpt=None,
    )
    # Insert the audio ahead of the trailing task text so the instruction stays last.
    return [*content[:-1], _audio_part(audio_path, ctx.audio_format), content[-1]]


async def _extract_window_frames(ctx, window: Window, frames_dir: str) -> list[str]:
    """Frames sampled from the ORIGINAL file — no transcode step.

    ``extract_frames`` measures offsets from the start of the file it is given,
    so a window is cut first and sampled inside. The cut is stream-copied, which
    is far cheaper than the re-encode arm A needs.
    """
    os.makedirs(frames_dir, exist_ok=True)
    slice_path = os.path.join(frames_dir, "slice.mp4")
    await arun(
        [
            ffmpeg_path(), "-y",
            "-ss", f"{window.start:.3f}",
            "-t", f"{window.duration:.3f}",
            "-i", ctx.media.path,
            "-an", "-c:v", "copy",
            "-loglevel", "error",
            slice_path,
        ],
        timeout=300.0,
    )
    return await extract_frames(
        slice_path, frames_dir, count=ctx.frames_per_window, duration=window.duration
    )


ARMS = {
    "video": _content_video,
    "frames_text": _content_frames_text,
    "frames_audio": _content_frames_audio,
}


# ---------------------------------------------------------------------------
# Shared runner
# ---------------------------------------------------------------------------


@dataclass
class _Context:
    media: MediaInfo
    work_dir: str
    frames_per_window: int
    audio_format: str
    transcript: Transcript | None
    query: str | None


def _content_bytes(content) -> int:
    """Approximate request size: the base64 payloads dominate everything else."""
    if isinstance(content, str):
        return len(content)
    total = 0
    for part in content:
        if part.get("type") == "image_url":
            total += len(part["image_url"]["url"])
        elif part.get("type") == "video_url":
            total += len(part["video_url"]["url"])
        elif part.get("type") == "input_audio":
            total += len(part["input_audio"]["data"])
        elif part.get("type") == "text":
            total += len(part["text"])
    return total


async def run_arm(
    arm: str,
    media: MediaInfo,
    *,
    client: OpenRouterClient,
    model: str,
    synthesis_model: str,
    work_dir: str,
    window_seconds: float = 60.0,
    overlap: float = 2.0,
    frames_per_window: int = 6,
    audio_format: str = "mp3",
    concurrency: int = 4,
    transcript: Transcript | None = None,
    query: str | None = None,
    timeout: float = 180.0,
) -> ArmResult:
    """Run one arm end to end over one video."""
    build = ARMS[arm]
    windows = plan_windows(media.duration, window_seconds, overlap)
    result = ArmResult(
        arm=arm,
        video=media.path,
        frames_per_window=None if arm == "video" else frames_per_window,
        window_seconds=window_seconds,
    )

    ctx = _Context(
        media=media,
        work_dir=work_dir,
        frames_per_window=frames_per_window,
        audio_format=audio_format,
        transcript=transcript,
        query=query,
    )

    semaphore = asyncio.Semaphore(max(concurrency, 1))
    started = time.perf_counter()

    async def _one(window: Window) -> WindowResult:
        try:
            content = await build(ctx, window)
        except Exception as exc:  # noqa: BLE001 - a local failure is a result, not a crash
            return WindowResult(window.index, window.start, window.end, "error", f"prep: {exc}")

        size = _content_bytes(content)
        try:
            async with semaphore:
                text = await asyncio.wait_for(
                    client.complete(
                        content, model=model, temperature=0.2, reasoning=False, timeout=timeout
                    ),
                    timeout=timeout + 30,
                )
        except Exception as exc:  # noqa: BLE001
            reason = "timed out" if isinstance(exc, asyncio.TimeoutError) else str(exc)
            return WindowResult(window.index, window.start, window.end, "error", reason, size)

        cleaned = strip_reasoning(text)
        status = "ok" if cleaned else "error"
        return WindowResult(
            window.index,
            window.start,
            window.end,
            status,
            cleaned or "empty response",
            size,
        )

    result.windows = sorted(
        await asyncio.gather(*(_one(w) for w in windows)), key=lambda w: w.index
    )
    result.requests = len(result.windows)
    result.uploaded_bytes = sum(w.request_bytes for w in result.windows)

    usable = [w for w in result.windows if w.status == "ok"]
    if not usable:
        result.error = "every window failed"
        result.seconds = time.perf_counter() - started
        return result

    timeline = "\n\n".join(f"[{w.start:.0f}s - {w.end:.0f}s]\n{w.text}" for w in usable)
    try:
        summary = await client.complete(
            build_synthesis_prompt(timeline, query),
            model=synthesis_model,
            temperature=0.2,
            reasoning=True,
            timeout=timeout,
        )
        result.summary = strip_reasoning(summary)
        result.requests += 1
    except Exception as exc:  # noqa: BLE001
        result.error = f"synthesis failed: {exc}"

    result.seconds = time.perf_counter() - started
    return result
