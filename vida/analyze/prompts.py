"""Prompt construction for visual analysis."""

from __future__ import annotations

from vida.media.encode import data_url

__all__ = ["build_video_prompt", "build_frames_prompt", "build_synthesis_prompt"]

_ANALYSIS_TASK = (
    "Watch this clip and describe what actually happens: the setting, who or what "
    "is on screen, the actions, and any visible text or on-screen graphics. "
    "Be concrete and specific. Do not speculate beyond what is shown. "
    "Keep it under 5 sentences."
)


def _timespan(start: float | None, end: float | None) -> str:
    if start is None or end is None:
        return ""
    return f"This clip covers {start:.0f}s to {end:.0f}s of the full video.\n"


def _context(user_query: str | None, transcript_excerpt: str | None) -> str:
    parts = []
    if user_query:
        parts.append(f"The viewer wants to know: {user_query}\nFocus on that.")
    if transcript_excerpt:
        parts.append(
            "For reference, here is what is said during this clip:\n"
            f"\"\"\"\n{transcript_excerpt.strip()}\n\"\"\"\n"
            "Use it to ground your description, but describe what is *shown*."
        )
    return "\n\n".join(parts)


def build_video_prompt(
    segment_path: str,
    *,
    start: float | None = None,
    end: float | None = None,
    user_query: str | None = None,
    transcript_excerpt: str | None = None,
) -> list[dict]:
    """Content parts for sending a video clip to a multimodal model."""
    text = "\n".join(
        part
        for part in (_timespan(start, end), _context(user_query, transcript_excerpt), _ANALYSIS_TASK)
        if part
    )
    return [
        {"type": "video_url", "video_url": {"url": data_url(segment_path, "video/mp4")}},
        {"type": "text", "text": text},
    ]


def build_frames_prompt(
    frame_paths: list[str],
    *,
    start: float | None = None,
    end: float | None = None,
    user_query: str | None = None,
    transcript_excerpt: str | None = None,
) -> list[dict]:
    """Content parts for the still-frame fallback path.

    Used when a model rejects or times out on raw video; evenly spaced stills
    carry most of the signal at a fraction of the payload.
    """
    content: list[dict] = []
    for index, path in enumerate(frame_paths):
        content.append({"type": "text", "text": f"Frame {index + 1} of {len(frame_paths)}:"})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": data_url(path, "image/jpeg"), "detail": "low"},
            }
        )

    text = "\n".join(
        part
        for part in (
            _timespan(start, end),
            "These frames are evenly spaced samples from one clip.",
            _context(user_query, transcript_excerpt),
            _ANALYSIS_TASK,
        )
        if part
    )
    content.append({"type": "text", "text": text})
    return content


def build_synthesis_prompt(timeline: str, user_query: str | None = None) -> str:
    """Prompt that turns per-clip descriptions back into one narrative."""
    if user_query:
        task = (
            f"Answer this question about the video: {user_query}\n\n"
            "Ground every claim in the clip descriptions. If they don't contain "
            "enough information to answer, say so plainly."
        )
    else:
        task = (
            "Write a coherent summary of the whole video: what it is, what happens, "
            "and how it progresses. Note the key moments in order."
        )

    return (
        "Below are descriptions of consecutive clips from a single video, in order. "
        "They overlap slightly, so the same moment may be described twice — treat "
        "those as one event rather than two.\n\n"
        f"{timeline}\n\n{task}\n\n"
        "Write the answer directly. Do not mention clips, segments, or that you were "
        "given descriptions."
    )
