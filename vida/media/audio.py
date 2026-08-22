"""Audio extraction and chunking.

ASR backends all want small, mono, 16 kHz audio. Pulling that out of the video
once — instead of shipping video bytes to the model — is the single biggest
speed win in the transcription path: a 1-hour video becomes roughly 30 MB of
FLAC instead of several GB of H.264.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from vida.errors import MediaError
from vida.media.ffmpeg import arun, ffmpeg_path

__all__ = [
    "extract_audio",
    "split_audio",
    "cut_audio",
    "AudioChunk",
    "DIALOGUE_FILTER_CENTER_51",
    "DIALOGUE_FILTER_MIDSIDE_STEREO",
]

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
"""Whisper-family models resample to 16 kHz internally; doing it here saves bandwidth."""

# Dialogue isolation presets for `ASRConfig.dialogue_filter`. Unlike the denoise
# chain these run *before* the mono downmix, because both work on the channel
# layout the source was mixed in — once it is folded to mono the information
# they exploit is gone.
DIALOGUE_FILTER_CENTER_51 = "pan=mono|c0=FC"
"""Take the centre channel and nothing else. 5.1 sources only.

Film dialogue is mixed to the centre channel almost by convention, so on a true
5.1 source this discards the score and the effects bed outright rather than
trying to subtract them. On stereo or mono input ffmpeg has no ``FC`` to map and
the command fails, which is why this is opt-in per source rather than a default.
"""

DIALOGUE_FILTER_MIDSIDE_STEREO = "pan=mono|c0=0.5*c0+0.5*c1"
"""Approximate the same idea on stereo by keeping what L and R agree on.

Summing to mono reinforces phase-coherent content — centre-panned dialogue —
while hard-panned and out-of-phase content partially cancels. Much weaker than
a real centre channel, and it is what ffmpeg's plain downmix already does, so
its value is being explicit rather than being different.
"""


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


def _filter_graph(
    audio_filter: str | None, dialogue_filter: str | None, sample_rate: int
) -> str:
    """Assemble the ``-af`` chain, in the order each stage needs to run.

    Order is the whole point of this function:

    1. ``dialogue_filter`` — needs the source channel layout, so it goes first.
    2. downmix to mono and resample — everything downstream assumes this.
    3. ``audio_filter`` — the denoise chain, calibrated against 16 kHz mono.

    With no ``dialogue_filter`` set the result is byte-identical to what this
    produced before dialogue isolation existed, so the default path cannot have
    moved.
    """
    stages = []
    if dialogue_filter:
        stages.append(dialogue_filter)
    if audio_filter or dialogue_filter:
        # The downmix is only spelled out here when something in the graph
        # depends on where it happens; `-ac`/`-ar` are set as output options
        # regardless, and duplicating them costs a no-op.
        stages.append(f"aformat=channel_layouts=mono,aresample={sample_rate}")
    if audio_filter:
        stages.append(audio_filter)
    return ",".join(stages)


async def extract_audio(
    video_path: str,
    out_path: str,
    *,
    sample_rate: int = SAMPLE_RATE,
    timeout: float = 900.0,
    audio_filter: str | None = None,
    dialogue_filter: str | None = None,
) -> str:
    """Strip the audio track out of ``video_path`` into mono FLAC at ``out_path``.

    FLAC is lossless (so it costs the ASR model nothing in accuracy) and is
    accepted by every backend we support. ``audio_filter`` is an ffmpeg filter
    chain applied on the way out — this is the one place the audio is decoded
    anyway, so cleaning it here is free.

    ``dialogue_filter`` is a second, optional chain that runs *ahead* of the
    mono downmix rather than after it. The two are separate because they need
    opposite conditions: denoising is calibrated against 16 kHz mono, while
    dialogue isolation only works while the source channels still exist.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    command = [
        ffmpeg_path(), "-y",
        "-i", video_path,
        "-vn",                      # drop video
        "-map", "0:a:0",            # first audio track only
    ]
    graph = _filter_graph(audio_filter, dialogue_filter, sample_rate)
    if graph:
        command += ["-af", graph]
    command += [
        "-ac", "1",                 # mono
        "-ar", str(sample_rate),
        "-c:a", "flac",
        "-loglevel", "error",
        out_path,
    ]
    await arun(command, timeout=timeout)
    return out_path


async def cut_audio(
    src: str,
    dest: str,
    start: float,
    duration: float,
    *,
    sample_rate: int = SAMPLE_RATE,
    timeout: float = 600.0,
) -> str:
    """Copy ``duration`` seconds of ``src`` starting at ``start`` into ``dest``."""
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
    return dest



# ---------------------------------------------------------------------------
# Silence-aware boundaries
# ---------------------------------------------------------------------------

_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")

SILENCE_NOISE_DB = -30.0
"""Level below which audio counts as silence, in dBFS.

Deliberately generous. This is not trying to find true digital silence — a film
mix has none — but the gaps between lines, which sit well above the noise floor
of the medium and well below dialogue. A stricter threshold finds nothing on
real material and the search falls back to the fixed boundary, which is the
behaviour this exists to improve on.
"""

SILENCE_MIN_DURATION = 0.35
"""Shortest gap worth cutting at. Below this it is a pause inside a sentence."""


async def _detect_silences(
    audio_path: str,
    start: float,
    duration: float,
    *,
    noise_db: float = SILENCE_NOISE_DB,
    min_duration: float = SILENCE_MIN_DURATION,
    timeout: float = 120.0,
) -> list[tuple[float, float]]:
    """Find silent spans in a window, as absolute ``(start, end)`` times.

    ffmpeg reports these on stderr at ``info`` level, so the output is parsed
    rather than returned — there is no machine-readable form of ``silencedetect``.
    Returns an empty list on any failure: this is an optimisation, and a window
    with no detected silence simply keeps its fixed boundary.
    """
    command = [
        ffmpeg_path(),
        "-ss", f"{max(start, 0.0):.3f}",
        "-t", f"{max(duration, 0.0):.3f}",
        "-i", audio_path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f", "null",
        "-loglevel", "info",
        "-",
    ]
    try:
        proc = await arun(command, timeout=timeout)
    except MediaError as exc:
        logger.debug("silencedetect failed on %s: %s", audio_path, exc)
        return []

    output = proc.stderr or ""
    starts = [float(m) for m in _SILENCE_START_RE.findall(output)]
    ends = [float(m) for m in _SILENCE_END_RE.findall(output)]

    # A silence still open when the window ended has a start and no end; close
    # it at the window edge rather than dropping it, since a gap running to the
    # end of the search window is a perfectly good place to cut.
    spans = []
    for index, span_start in enumerate(starts):
        span_end = ends[index] if index < len(ends) else max(duration, 0.0)
        # silencedetect reports relative to the trimmed input, not the file.
        spans.append((start + max(span_start, 0.0), start + span_end))
    return spans


def _best_silence_point(spans: list[tuple[float, float]], target: float) -> float | None:
    """The midpoint of the silence nearest ``target``, or ``None`` if there is none.

    The midpoint rather than either edge: cutting where the gap begins risks
    clipping the tail of the word before it, and cutting where it ends risks
    the head of the next one. The middle is the only point with margin on both
    sides.
    """
    if not spans:
        return None
    midpoints = [(span_start + span_end) / 2 for span_start, span_end in spans]
    return min(midpoints, key=lambda point: abs(point - target))


async def _snap_boundary(
    audio_path: str,
    target: float,
    *,
    search_seconds: float,
    total_duration: float,
    timeout: float = 120.0,
) -> float:
    """Move ``target`` to nearby silence, or leave it exactly where it was.

    Best effort by construction — every failure path returns ``target``
    unchanged, mirroring :func:`vida.asr.pipeline.detect_language`: an
    optimisation must never be able to cost you the transcript.
    """
    if search_seconds <= 0:
        return target

    window_start = max(target - search_seconds, 0.0)
    window_end = min(target + search_seconds, total_duration)
    if window_end <= window_start:
        return target

    spans = await _detect_silences(
        audio_path, window_start, window_end - window_start, timeout=timeout
    )
    point = _best_silence_point(spans, target)
    if point is None:
        return target
    # A detected silence can extend past the search window; clamp so a snap can
    # never move the boundary further than the caller allowed.
    return min(max(point, window_start), window_end)


async def split_audio(
    audio_path: str,
    total_duration: float,
    *,
    chunk_seconds: float,
    overlap: float = 2.0,
    out_dir: str | None = None,
    sample_rate: int = SAMPLE_RATE,
    timeout: float = 600.0,
    silence_aware: bool = False,
    search_seconds: float = 3.0,
) -> list[AudioChunk]:
    """Split audio into overlapping chunks that can be transcribed in parallel.

    Returns a single chunk pointing at the original file when the audio is
    already short enough, so short inputs skip transcoding entirely.

    With ``silence_aware`` set, each boundary is nudged up to ``search_seconds``
    to land in a gap between lines instead of wherever the clock happened to
    fall. The overlap already means a word split across a seam survives in one
    chunk or the other; this aims at not splitting it in the first place, so
    neither chunk hands the model half an utterance to guess at.
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

        if silence_aware and end < total_duration:
            # Anchored search: the target is measured from where the *previous*
            # boundary actually landed, not from a fixed multiple of the stride.
            # Snapped boundaries would otherwise accumulate drift, and the exact
            # `previous.end - current.start == overlap` contract that
            # tests/test_media.py asserts would fail by whatever each snap moved.
            end = await _snap_boundary(
                audio_path,
                end,
                search_seconds=search_seconds,
                total_duration=total_duration,
                timeout=timeout,
            )
            # A snap that lands at or before the chunk start would produce an
            # empty or reversed chunk; the fixed boundary is bad but valid.
            if end <= start:
                end = min(start + chunk_seconds, total_duration)

        planned.append((os.path.join(out_dir, f"{stem}_chunk{index:04d}.flac"), start, end, index))
        index += 1
        if end >= total_duration:
            break
        # Overlap is measured back from the boundary that was actually used, so
        # the contract holds however far the snap moved it.
        start = max(end - overlap, start + 1.0) if silence_aware else start + stride

    await asyncio.gather(
        *(
            cut_audio(
                audio_path,
                dest,
                chunk_start,
                chunk_end - chunk_start,
                sample_rate=sample_rate,
                timeout=timeout,
            )
            for dest, chunk_start, chunk_end, _ in planned
        )
    )

    return [AudioChunk(dest, s, e, i) for dest, s, e, i in planned]
