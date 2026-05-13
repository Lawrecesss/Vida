import asyncio
import os
import random
from helpers.extract_frame import extract_frames, cleanup_frames
from helpers.video_segmentation import parallel_video_segmentation as cut_segments, get_video_duration
from models.models import OVERLAP, video_analysis_model_with_reasoning, video_analysis_model_without_reasoning, reasoning_model_response
from prompts.prompts import build_video_prompt, build_frames_prompt

async def analyze_segment(index: int, segment_path: str, semaphore: asyncio.Semaphore, user_query: str = None, retries: int = 3, is_original: bool = False) -> dict:
    loop = asyncio.get_event_loop()
    mode = "video"
    content = build_video_prompt(index, segment_path, user_query)

    for attempt in range(retries):
        try:
            async with semaphore:
                response = await asyncio.wait_for(
                    video_analysis_model_without_reasoning(content) if not is_original else video_analysis_model_with_reasoning(content),
                    timeout=120.0
                )

            # FEATURE: Only delete if it's a temporary segment, NOT the original video
            if not is_original and os.path.exists(segment_path):
                os.remove(segment_path)
            cleanup_frames(index)

            return {"index": index, "status": "ok", "mode": mode, "analysis": response.choices[0].message.content}

        except Exception as e:
            if mode == "video":
                frame_paths = await loop.run_in_executor(None, extract_frames, segment_path, index)
                content = build_frames_prompt(index, frame_paths, user_query)
                mode = "frames"
                continue
            if attempt == retries - 1:
                if not is_original and os.path.exists(segment_path):
                    os.remove(segment_path)
                cleanup_frames(index)
                return {"index": index, "status": "error", "mode": "failed", "analysis": str(e)}
            await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))

async def analyze_all_segments(segments: list[str], concurrency: int, user_query: str, is_original: bool) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [analyze_segment(i, seg, semaphore, user_query, is_original=is_original) for i, seg in enumerate(segments)]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda r: r["index"])

async def synthesize(results: list[dict], user_query: str = None) -> str:
    timeline = "\n\n".join([f"[Segment {r['index'] + 1}]\n{r['analysis']}" if r["status"] == "ok" else "Error" for r in results])
    response = await reasoning_model_response(timeline, user_query)
    return response.choices[0].message.content

async def video_analyzer(video_path: str, user_query: str = None):
    # FEATURE: Logic to check range
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    duration = get_video_duration(video_path)
    
    is_within_range = file_size_mb <= 25 and duration <= 60

    if is_within_range:
        print(f"✅ Video within range ({file_size_mb:.1f}MB, {duration:.1f}s). Skipping segmentation.")
        # We pass the single original video path as a list
        results = await analyze_all_segments([video_path], concurrency=1, user_query=user_query, is_original=True)
        return {"segments": results, "summary": results[0]["analysis"] if results else ""}
    else:
        print(f"✂️ Video exceeds range ({file_size_mb:.1f}MB, {duration:.1f}s). Segmenting...")
        segments = cut_segments(video_path, overlap=OVERLAP)
        results = await analyze_all_segments(segments, concurrency=3, user_query=user_query, is_original=False)
        print("🧠 Synthesizing...")
        summary = await synthesize(results, user_query)
        return {"segments": results, "summary": summary}

if __name__ == "__main__":
    result = asyncio.run(video_analyzer(
        video_path="test_video.mp4",
        user_query="What is the main topic?"
    ))
    print(f"\n── Final Summary ──\n{result['summary']}")