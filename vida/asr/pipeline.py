"""The transcription pipeline: extract audio, fan out, stitch back together.

Long media is the slow case, and it's embarrassingly parallel: split the audio
into overlapping chunks, transcribe them all at once, then shift each chunk's
timestamps back onto the original timeline and drop the duplicates the overlap
created.
"""

from __future__ import annotations

import asyncio
import collections
import os

from vida.asr.base import Transcriber
from vida.config import ASRConfig
from vida.errors import MediaError, TranscriptionError
from vida.media.audio import AudioChunk, extract_audio, split_audio
from vida.types import Segment, Transcript

__all__ = ["transcribe_audio_file", "merge_chunk_transcripts"]

# A segment ending this close to its chunk's end was probably cut off mid-word;
# prefer the next chunk's complete version of it.
_TRUNCATION_EPSILON = 0.25


async def transcribe_audio_file(
    transcriber: Transcriber,
    audio_path: str,
    duration: float,
    config: ASRConfig,
    *,
    language: str | None = None,
    prompt: str | None = None,
    work_dir: str | None = None,
    source: str | None = None,
) -> Transcript:
    """Transcribe an audio file of any length, in parallel where it helps."""
    chunks = await split_audio(
        audio_path,
        duration,
        chunk_seconds=config.chunk_seconds,
        overlap=config.chunk_overlap,
        out_dir=work_dir,
    )

    if len(chunks) == 1:
        transcript = await transcriber.transcribe_file(
            chunks[0].path, language=language, prompt=prompt
        )
        transcript.source = source or audio_path
        if not transcript.duration:
            transcript.duration = duration
        return transcript

    semaphore = asyncio.Semaphore(max(config.concurrency, 1))

    async def _one(chunk: AudioChunk) -> tuple[AudioChunk, Transcript]:
        async with semaphore:
            result = await transcriber.transcribe_file(
                chunk.path, language=language, prompt=prompt
            )
        return chunk, result

    try:
        results = await asyncio.gather(*(_one(chunk) for chunk in chunks))
    finally:
        # Chunk files are scratch; the extracted audio itself is cleaned up by
        # whoever created the work directory.
        for chunk in chunks:
            if chunk.path != audio_path:
                _unlink(chunk.path)

    merged = merge_chunk_transcripts(results)
    merged.source = source or audio_path
    merged.backend = transcriber.name
    merged.duration = merged.duration or duration
    return merged


def merge_chunk_transcripts(
    results: list[tuple[AudioChunk, Transcript]],
) -> Transcript:
    """Shift each chunk's segments onto the global timeline and de-overlap them.

    Two things go wrong at a chunk seam, and both are handled here: the last
    segment of a chunk may be cut off mid-utterance, and the overlap means the
    next chunk repeats what the previous one already covered.
    """
    ordered = sorted(results, key=lambda pair: pair[0].index)

    merged: list[Segment] = []
    cursor = 0.0  # global time already accounted for
    languages: list[str] = []
    last_index = len(ordered) - 1

    for position, (chunk, transcript) in enumerate(ordered):
        if transcript.language:
            languages.append(transcript.language)

        shifted = [
            Segment(
                id=0,
                start=segment.start + chunk.start,
                end=segment.end + chunk.start,
                text=segment.text,
                speaker=segment.speaker,
                confidence=segment.confidence,
            )
            for segment in transcript.segments
        ]

        # Drop a trailing segment that runs into the chunk boundary — the next
        # chunk has the whole utterance thanks to the overlap.
        if (
            position < last_index
            and len(shifted) > 1
            and chunk.end - shifted[-1].end < _TRUNCATION_EPSILON
        ):
            shifted = shifted[:-1]

        for segment in shifted:
            if position > 0:
                # Already covered by an earlier chunk.
                if segment.end <= cursor + _TRUNCATION_EPSILON:
                    continue
                # Same utterance, re-heard at the seam.
                if (
                    segment.start < cursor - _TRUNCATION_EPSILON
                    and merged
                    and _looks_duplicated(merged[-1].text, segment.text)
                ):
                    continue
            merged.append(segment)
            cursor = max(cursor, segment.end)

    for index, segment in enumerate(merged):
        segment.id = index

    language = collections.Counter(languages).most_common(1)[0][0] if languages else None

    return Transcript(
        language=language,
        segments=merged,
        duration=merged[-1].end if merged else 0.0,
    )


def _looks_duplicated(previous: str, current: str) -> bool:
    """Cheap check for the same utterance transcribed twice at a seam."""
    a = previous.strip().lower()
    b = current.strip().lower()
    if not a or not b:
        return False
    return a == b or a.endswith(b) or b.startswith(a[-40:])


def _unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


async def extract_audio_for(
    video_path: str, work_dir: str, has_audio: bool, timeout: float = 900.0
) -> str:
    """Pull the audio track out of a video into ``work_dir``."""
    if not has_audio:
        raise MediaError(f"{video_path} has no audio track to transcribe.")

    stem = os.path.splitext(os.path.basename(video_path))[0]
    out_path = os.path.join(work_dir, f"{stem}.flac")
    try:
        return await extract_audio(video_path, out_path, timeout=timeout)
    except MediaError as exc:
        raise TranscriptionError(f"Could not extract audio from {video_path}: {exc}") from exc
