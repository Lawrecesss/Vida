import asyncio
import os
import re
import random
from langchain_core.tools import tool
from core.helpers.extract_frame import extract_frames, cleanup_frames
from core.helpers.video_segmentation import parallel_video_segmentation as cut_segments, get_video_duration
from core.models.models import OVERLAP, video_analysis_model_with_reasoning, video_analysis_model_without_reasoning, reasoning_model_response
from core.prompts.prompts import build_video_prompt, build_frames_prompt


async def analyze_segment(
    index: int,
    segment_path: str,
    semaphore: asyncio.Semaphore,
    user_query: str = None,
    retries: int = 3,
    is_original: bool = False
) -> dict:
    loop = asyncio.get_running_loop()
    mode = "video"
    content = build_video_prompt(index, segment_path, user_query)

    for attempt in range(retries):
        try:
            if mode == "frames":
                frame_paths = await loop.run_in_executor(None, extract_frames, segment_path, index)
                content = build_frames_prompt(index, frame_paths, user_query)

            async with semaphore:
                response = await asyncio.wait_for(
                    video_analysis_model_with_reasoning(content) if is_original
                    else video_analysis_model_without_reasoning(content),
                    timeout=120.0
                )

            if not is_original and os.path.exists(segment_path):
                os.remove(segment_path)
            if mode == "frames":
                cleanup_frames(index)

            return {"index": index, "status": "ok", "mode": mode, "analysis": response.content}

        except asyncio.TimeoutError:
            print(f"⏱️ Segment {index} timed out (attempt {attempt + 1})")
            if mode == "video":
                mode = "frames"
                continue
            if attempt == retries - 1:
                if not is_original and os.path.exists(segment_path):
                    os.remove(segment_path)
                cleanup_frames(index)
                return {"index": index, "status": "error", "mode": "failed", "analysis": "Timeout"}
            await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))

        except Exception as e:
            print(f"❌ Segment {index} error (attempt {attempt + 1}): {e}")
            if mode == "video":
                mode = "frames"
                continue
            if attempt == retries - 1:
                if not is_original and os.path.exists(segment_path):
                    os.remove(segment_path)
                cleanup_frames(index)
                return {"index": index, "status": "error", "mode": "failed", "analysis": str(e)}
            await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))

    if not is_original and os.path.exists(segment_path):
        os.remove(segment_path)
    cleanup_frames(index)
    return {"index": index, "status": "error", "mode": "failed", "analysis": "Max retries exceeded"}


async def analyze_all_segments(
    segments: list[str],
    concurrency: int,
    user_query: str,
    is_original: bool
) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        analyze_segment(i, seg, semaphore, user_query, is_original=is_original)
        for i, seg in enumerate(segments)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return sorted(results, key=lambda r: r["index"])


def strip_thinking_tokens(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()


async def synthesize(results: list[dict], user_query: str = None) -> str:
    timeline = "\n\n".join([
        f"[Segment {r['index'] + 1}]\n{r['analysis']}"
        if r["status"] == "ok"
        else f"[Segment {r['index'] + 1}]\nError: {r['analysis']}"
        for r in results
    ])
    response = await reasoning_model_response(timeline, user_query)
    return strip_thinking_tokens(response.content)


async def _video_analyzer(video_path: str, user_query: str = None) -> dict:
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    duration = get_video_duration(video_path)
    is_within_range = file_size_mb <= 25 and duration <= 60

    if is_within_range:
        print(f"✅ Video within range ({file_size_mb:.1f}MB, {duration:.1f}s). Skipping segmentation.")
        results = await analyze_all_segments(
            [video_path], concurrency=1, user_query=user_query, is_original=True
        )
        summary = (
            strip_thinking_tokens(results[0]["analysis"])
            if results and results[0]["status"] == "ok"
            else await synthesize(results, user_query)
        )
        return {"segments": results, "summary": summary}

    else:
        print(f"✂️ Video exceeds range ({file_size_mb:.1f}MB, {duration:.1f}s). Segmenting...")
        segments = cut_segments(video_path, overlap=OVERLAP)
        print(f"📦 {len(segments)} segments created. Analyzing with concurrency={min(len(segments), 5)}...")
        results = await analyze_all_segments(
            segments, concurrency=min(len(segments), 5), user_query=user_query, is_original=False
        )
        print("🧠 Synthesizing...")
        summary = await synthesize(results, user_query)
        return {"segments": results, "summary": summary}


@tool
async def video_analyzer(video_path: str, user_query: str = None) -> str:
    """
    Analyze a video file and return a summary of its content.

    Use this tool when the user wants to:
    - Understand what happens in a video
    - Extract key events or topics from a video
    - Answer questions about video content

    Args:
        video_path: Absolute or relative path to the video file to analyze.
        user_query: Optional specific question or focus for the analysis.
                    If not provided, a general summary will be produced.

    Returns:
        A string summary of the video content, optionally focused on the user query.
    """
    if not os.path.exists(video_path):
        return f"Error: Video file not found at path: {video_path}"

    result = await _video_analyzer(video_path, user_query)
    return result["summary"]