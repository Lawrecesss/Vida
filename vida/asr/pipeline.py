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
from vida.asr.glossary import build_prompt
from vida.asr.languages import to_code
from vida.config import ASRConfig
from vida.errors import MediaError, TranscriptionError, VidaError
from vida.media.audio import AudioChunk, cut_audio, extract_audio, split_audio
from vida.types import Segment, Transcript

__all__ = ["transcribe_audio_file", "merge_chunk_transcripts", "detect_language"]

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
    glossary: list[str] | None = None,
    work_dir: str | None = None,
    source: str | None = None,
    probe_source: str | None = None,
) -> Transcript:
    """Transcribe an audio file of any length, in parallel where it helps."""
    # The one choke point both the single- and multi-chunk paths funnel through,
    # so the vocabulary prompt is assembled once here rather than per chunk.
    # Every chunk gets the same prompt: each is its own request with no memory
    # of the last, so a term dropped from one chunk's prompt is a term that
    # chunk cannot recognise.
    prompt = build_prompt(prompt, [*(config.glossary or []), *(glossary or [])])

    if language is not None:
        # Callers reasonably say "English" where the models want "en". An
        # unrecognised value is passed through untouched rather than dropped —
        # the backend may well know a name this table does not.
        language = to_code(language) or language
    else:
        language = await detect_language(
            transcriber,
            probe_source or audio_path,
            duration,
            config,
            work_dir=work_dir,
        )

    chunks = await split_audio(
        audio_path,
        duration,
        chunk_seconds=config.chunk_seconds,
        overlap=config.chunk_overlap,
        out_dir=work_dir,
        silence_aware=config.silence_aware_chunking,
        search_seconds=config.chunk_boundary_search_seconds,
    )

    if len(chunks) == 1:
        transcript = await transcriber.transcribe_file(
            chunks[0].path, language=language, prompt=prompt
        )
        transcript.source = source or audio_path
        if not transcript.duration:
            transcript.duration = duration
        # Filtered-out segments leave holes in the backend's own numbering;
        # close them so an id means the same thing on both paths.
        for index, segment in enumerate(transcript.segments):
            segment.id = index
        # Stamp here too, so a segment's language means the same thing whether
        # or not the audio happened to be long enough to split.
        _stamp_language(transcript.segments, transcript.language)
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
                # Each chunk is its own ASR request with its own language
                # detection, so this is the one place the truth about a
                # bilingual recording exists. The transcript-level language
                # below is only the majority vote.
                language=segment.language or transcript.language,
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

    # Majority vote, weighted by how much speech each chunk actually carried —
    # counting chunks equally lets a near-silent chunk outvote a dense one.
    weighted: collections.Counter[str] = collections.Counter()
    for segment in merged:
        if segment.language:
            weighted[segment.language] += max(segment.end - segment.start, 0.0)
    if weighted:
        language = weighted.most_common(1)[0][0]
    else:
        language = collections.Counter(languages).most_common(1)[0][0] if languages else None

    return Transcript(
        language=language,
        segments=merged,
        duration=merged[-1].end if merged else 0.0,
    )


async def detect_language(
    transcriber: Transcriber,
    audio_path: str,
    duration: float,
    config: ASRConfig,
    *,
    work_dir: str | None = None,
) -> str | None:
    """Decide once what language the audio is in, so every window agrees.

    Whisper re-detects the language for each 30-second window it decodes, and
    on accented speech it does drift: half a recording comes back as English
    and the rest as a language that merely sounds like it, invented word for
    word. Detecting from the opening slice and pinning that answer for the
    whole file removes the drift, at the cost of one short extra request.

    This is best effort, and on hard audio it is the weakest link in the
    pipeline — measured on one wind-heavy recording, Whisper called the same
    English speech English, Malay, or Burmese depending on which 30 seconds it
    was shown. Scoring candidate languages by decode log-probability is not a
    way out: the model scores a fluent hallucination in the wrong language
    *better* than a faithful transcript in the right one. Pass ``language``
    explicitly whenever the caller knows it; that path is exact and this one
    is a guess.

    ``audio_path`` should be the *unprocessed* media where there is a choice:
    the detector is trained on natural audio, and a denoised, level-normalised
    signal reads as further from what it expects, not closer.

    Returns an ISO-639-1 code, or ``None`` when detection is off, unnecessary,
    or inconclusive — a wrong pin is worse than no pin, so every failure here
    falls back to letting the backend decide.
    """
    probe_seconds = config.detect_seconds
    # A file no longer than one detection window has nothing to drift between,
    # so probing it would just ask the same question twice.
    if probe_seconds <= 0 or duration <= probe_seconds:
        return None

    probe_path = os.path.join(
        work_dir or os.path.dirname(os.path.abspath(audio_path)),
        f"{os.path.splitext(os.path.basename(audio_path))[0]}_detect.flac",
    )
    try:
        await cut_audio(audio_path, probe_path, 0.0, probe_seconds, timeout=config.timeout)
        transcript = await transcriber.transcribe_file(probe_path)
    except (VidaError, OSError):
        # Detection is an optimisation; losing it must never lose the transcript.
        return None
    finally:
        _unlink(probe_path)

    return to_code(transcript.language)


def _stamp_language(segments: list[Segment], language: str | None) -> None:
    """Fill in each segment's language from the transcript that produced it."""
    if not language:
        return
    for segment in segments:
        if not segment.language:
            segment.language = language


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
    video_path: str,
    work_dir: str,
    has_audio: bool,
    timeout: float = 900.0,
    audio_filter: str | None = None,
    dialogue_filter: str | None = None,
) -> str:
    """Pull the audio track out of a video into ``work_dir``."""
    if not has_audio:
        raise MediaError(f"{video_path} has no audio track to transcribe.")

    stem = os.path.splitext(os.path.basename(video_path))[0]
    out_path = os.path.join(work_dir, f"{stem}.flac")
    try:
        return await extract_audio(
            video_path,
            out_path,
            timeout=timeout,
            audio_filter=audio_filter,
            dialogue_filter=dialogue_filter,
        )
    except MediaError as exc:
        raise TranscriptionError(f"Could not extract audio from {video_path}: {exc}") from exc
