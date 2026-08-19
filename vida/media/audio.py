"""Audio extraction and chunking.

ASR backends all want small, mono, 16 kHz audio. Pulling that out of the video
once — instead of shipping video bytes to the model — is the single biggest
speed win in the transcription path: a 1-hour video becomes roughly 30 MB of
FLAC instead of several GB of H.264.
"""

from __future__ import annotations

import asyncio
import os

from vida.media.ffmpeg import arun, ffmpeg_path

__all__ = ["extract_audio", "split_audio", "AudioChunk"]

SAMPLE_RATE = 16_000
"""Whisper-family models resample to 16 kHz internally; doing it here saves bandwidth."""


class AudioChunk:
    """A slice of an audio file, plus where it sits in the original timeline."""

    __slots__ = ("path", "start", "end", "index")

    def __init__(self, path: str, start: float, end: float, index: int) -> None:
        self.path = path
        self.start = start
        self.end = end
        self.index = index

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AudioChunk(index={self.index}, {self.start:.1f}-{self.end:.1f}s, {self.path!r})"


async def extract_audio(
    video_path: str,
    out_path: str,
    *,
    sample_rate: int = SAMPLE_RATE,
    timeout: float = 900.0,
) -> str:
    """Strip the audio track out of ``video_path`` into mono FLAC at ``out_path``.

    FLAC is lossless (so it costs the ASR model nothing in accuracy) and is
    accepted by every backend we support.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    await arun(
        [
            ffmpeg_path(), "-y",
            "-i", video_path,
            "-vn",                      # drop video
            "-map", "0:a:0",            # first audio track only
            "-ac", "1",                 # mono
            "-ar", str(sample_rate),
            "-c:a", "flac",
            "-loglevel", "error",
            out_path,
        ],
        timeout=timeout,
    )
    return out_path


async def _cut(
    src: str, dest: str, start: float, duration: float, sample_rate: int, timeout: float
) -> None:
    await arun(
        [
            ffmpeg_path(), "-y",
            "-ss", f"{start:.3f}",       # before -i: fast keyframe-less seek on audio
            "-t", f"{duration:.3f}",
            "-i", src,
            "-ac", "1",
            "-ar", str(sample_rate),
            "-c:a", "flac",
            "-loglevel", "error",
            dest,
        ],
        timeout=timeout,
    )


async def split_audio(
    audio_path: str,
    total_duration: float,
    *,
    chunk_seconds: float,
    overlap: float = 2.0,
    out_dir: str | None = None,
    sample_rate: int = SAMPLE_RATE,
    timeout: float = 600.0,
) -> list[AudioChunk]:
    """Split audio into overlapping chunks that can be transcribed in parallel.

    Returns a single chunk pointing at the original file when the audio is
    already short enough, so short inputs skip transcoding entirely.
    """
    if total_duration <= chunk_seconds:
        return [AudioChunk(audio_path, 0.0, total_duration, 0)]

    out_dir = out_dir or os.path.dirname(os.path.abspath(audio_path))
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(audio_path))[0]

    # Advance by (chunk - overlap) so consecutive chunks share `overlap` seconds
    # of audio; a word spoken across a seam then appears in full in one of them.
    stride = max(chunk_seconds - overlap, 1.0)

    planned: list[tuple[str, float, float, int]] = []
    start = 0.0
    index = 0
    while start < total_duration:
        end = min(start + chunk_seconds, total_duration)
        planned.append((os.path.join(out_dir, f"{stem}_chunk{index:04d}.flac"), start, end, index))
        index += 1
        if end >= total_duration:
            break
        start += stride

    await asyncio.gather(
        *(
            _cut(audio_path, dest, chunk_start, chunk_end - chunk_start, sample_rate, timeout)
            for dest, chunk_start, chunk_end, _ in planned
        )
    )

    return [AudioChunk(dest, s, e, i) for dest, s, e, i in planned]
