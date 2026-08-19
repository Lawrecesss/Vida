"""Rendering transcripts as subtitle files."""

from __future__ import annotations

import json
import os
import textwrap
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from vida.types import Transcript

__all__ = ["to_srt", "to_vtt", "save_transcript", "format_timestamp"]

MAX_LINE_CHARS = 42
"""Roughly one comfortable subtitle line; broadcast guidelines land near here."""

MAX_LINES = 2


def format_timestamp(seconds: float, *, separator: str = ",") -> str:
    """Format seconds as ``HH:MM:SS,mmm`` (SRT) or ``HH:MM:SS.mmm`` (VTT)."""
    seconds = max(seconds, 0.0)
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _wrap(text: str) -> str:
    """Break a caption onto at most two readable lines."""
    text = " ".join(text.split())
    if len(text) <= MAX_LINE_CHARS:
        return text
    lines = textwrap.wrap(text, width=MAX_LINE_CHARS, break_long_words=False)
    if len(lines) <= MAX_LINES:
        return "\n".join(lines)
    # Too long to split cleanly — balance it across MAX_LINES instead of
    # truncating, so no words are lost.
    width = max(len(text) // MAX_LINES + 1, MAX_LINE_CHARS)
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False)[:MAX_LINES])


def _cues(transcript: Transcript) -> list[tuple[float, float, str]]:
    """Segments as non-overlapping, non-empty cues with sane minimum durations."""
    cues: list[tuple[float, float, str]] = []
    for segment in transcript.segments:
        text = segment.text.strip()
        if not text:
            continue
        start = max(segment.start, 0.0)
        # A zero-length cue never renders; give it a readable floor.
        end = max(segment.end, start + 0.4)
        if cues and start < cues[-1][1]:
            # Trim the previous cue rather than letting two show at once.
            previous_start, _, previous_text = cues[-1]
            cues[-1] = (previous_start, max(start, previous_start + 0.1), previous_text)
        cues.append((start, end, text))
    return cues


def to_srt(transcript: Transcript, *, wrap: bool = True) -> str:
    """Render a transcript as SubRip (.srt)."""
    blocks = []
    for index, (start, end, text) in enumerate(_cues(transcript), start=1):
        body = _wrap(text) if wrap else text
        blocks.append(
            f"{index}\n"
            f"{format_timestamp(start)} --> {format_timestamp(end)}\n"
            f"{body}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_vtt(transcript: Transcript, *, wrap: bool = True) -> str:
    """Render a transcript as WebVTT (.vtt)."""
    header = "WEBVTT\n"
    if transcript.language:
        header += f"Language: {transcript.language}\n"

    blocks = []
    for index, (start, end, text) in enumerate(_cues(transcript), start=1):
        body = _wrap(text) if wrap else text
        blocks.append(
            f"{index}\n"
            f"{format_timestamp(start, separator='.')} --> "
            f"{format_timestamp(end, separator='.')}\n"
            f"{body}"
        )
    return header + "\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


def save_transcript(
    transcript: Transcript,
    path: str,
    fmt: Literal["srt", "vtt", "txt", "json"] | None = None,
) -> str:
    """Write a transcript to disk, inferring the format from the extension."""
    if fmt is None:
        extension = os.path.splitext(path)[1].lower().lstrip(".")
        fmt = extension if extension in ("srt", "vtt", "txt", "json") else "srt"  # type: ignore[assignment]

    if fmt == "srt":
        content = to_srt(transcript)
    elif fmt == "vtt":
        content = to_vtt(transcript)
    elif fmt == "txt":
        content = transcript.text + "\n"
    elif fmt == "json":
        content = json.dumps(transcript.model_dump(mode="json"), ensure_ascii=False, indent=2)
    else:  # pragma: no cover - guarded by the inference above
        raise ValueError(f"Unsupported subtitle format: {fmt!r}")

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path
