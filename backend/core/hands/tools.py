import os
import base64
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain.messages import HumanMessage
from langchain_openrouter import ChatOpenRouter
import helpers.video_segmentation as vs


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_model():
    return ChatOpenRouter(
        model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
        temperature=0,
    )


def _extract_text(response) -> str:
    """
    LangChain responses can return either a plain string or a list of content
    blocks like [{"type": "text", "text": "..."}]. Normalise both to a string.
    """
    content = response.content

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "reasoning":
                    pass  # skip internal chain-of-thought
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts).strip()

    return str(content).strip()


# ── Per-segment worker ────────────────────────────────────────────────────────

def _analyze_segment(args: tuple) -> tuple[int, str]:
    i, path, user_query, total = args
    model = _make_model()

    with open(path, "rb") as f:
        video_base64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = (
        f"User Goal: {user_query}\n\n"
        "Watch this video segment and analyze its content in relation to the User Goal. Be concise and directly address the User Goal. If the segment contains no relevant information, respond with 'No relevant content.'"
    )

    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{video_base64}"}},
        ]
    )

    del video_base64

    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = model.invoke([message])
            text = _extract_text(response)

            # ── Debug: show exactly what came back ──
            print(f"\n[Segment {i+1}/{total} raw response type]: {type(response.content)}")
            print(f"[Segment {i+1}/{total} extracted text]:\n{text or '(EMPTY)'}\n")

            if not text:
                text = "No relevant content."

            return i, text

        except Exception as e:
            wait = 2 ** attempt
            print(f"  ✗ Segment {i+1} attempt {attempt+1} failed: {e}. Retrying in {wait}s…")
            time.sleep(wait)

    return i, "Segment analysis failed."


# ── Merge ─────────────────────────────────────────────────────────────────────

def _merge_summaries(model, user_query: str, ordered_summaries: list[str]) -> str:
    # ── Debug: confirm what we're sending into the merge ──
    print("\n[Merge input summaries]:")
    for i, s in enumerate(ordered_summaries):
        print(f"  Segment {i+1}: {s or '(EMPTY)'}")

    numbered = "\n".join(
        f"Segment {i+1}: {s}" for i, s in enumerate(ordered_summaries)
    )
    prompt = (
        f"User Goal: {user_query}\n\n"
        "Below are per-segment summaries of a video in chronological order:\n\n"
        f"{numbered}\n\n"
        "Synthesize these into one concise, coherent final answer that directly "
        "addresses the User Goal."
    )

    message = HumanMessage(content=[{"type": "text", "text": prompt}])

    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = model.invoke([message])
            text = _extract_text(response)

            # ── Debug: show merge response ──
            print(f"\n[Merge raw response type]: {type(response.content)}")
            print(f"[Merge extracted text]:\n{text or '(EMPTY)'}\n")

            return text if text else "Merge produced no output."

        except Exception as e:
            wait = 2 ** attempt
            print(f"  ✗ Merge attempt {attempt+1} failed: {e}. Retrying in {wait}s…")
            time.sleep(wait)

    return "Merge failed after retries."


# ── Main ──────────────────────────────────────────────────────────────────────

def video_analysis(video_path: str, user_query: str, max_workers: int = 4) -> str:
    segment_paths = vs.parallel_video_segmentation(video_path)
    total = len(segment_paths)
    print(f"Segmented into {total} parts. Analysing in parallel (workers={min(max_workers, total)})…")

    args = [(i, path, user_query, total) for i, path in enumerate(segment_paths)]
    results: list[tuple[int, str]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_analyze_segment, arg): arg[0] for arg in args}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                idx = futures[future]
                print(f"  ✗ Segment {idx+1} unhandled exception: {e}")
                results.append((idx, "Segment analysis failed."))

    for path in segment_paths:
        if os.path.exists(path):
            os.remove(path)

    results.sort(key=lambda x: x[0])
    ordered_summaries = [summary for _, summary in results]

    print("All segments done. Merging summaries…")
    model = _make_model()
    return _merge_summaries(model, user_query, ordered_summaries)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    final_summary = video_analysis(
        "/Users/lawrence/Projects/VidA/vids/test1.MP4",
        "Categorize the content of this video into one-word categories, and list the key events.",
        max_workers=4,
    )
    print("\nFinal Summary:\n", final_summary)