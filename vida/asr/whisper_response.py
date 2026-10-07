"""Normalising a Whisper ``verbose_json`` response into a :class:`Transcript`.

Every hosted Whisper endpoint — OpenRouter's ``/audio/transcriptions``,
OpenAI's, anything else OpenAI-compatible — answers in the same shape, and the
local backend's objects are near enough that the same silence and confidence
handling applies. This module is where that shape is understood; a backend only
has to get the bytes there and back.

Which fields actually arrive varies by provider. OpenRouter says so explicitly
for ``language``, ``duration`` and ``segments``, and ``avg_logprob`` /
``no_speech_prob`` are not in its documented segment schema at all — so every
read here tolerates absence, and :func:`vida.asr.silence.is_silence` keeps a
segment whose no-speech probability was never reported.
"""

from __future__ import annotations

import math

from vida.asr.silence import DEFAULT_NO_SPEECH_THRESHOLD, is_repetition_loop, is_silence
from vida.types import Segment, Transcript

__all__ = ["read_bytes", "to_transcript", "logprob_to_confidence", "get_field"]


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def get_field(obj, key, default=None):
    """Read a field whether the SDK handed back a model object or a plain dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def to_transcript(
    response,
    source: str,
    backend: str,
    no_speech_threshold: float = DEFAULT_NO_SPEECH_THRESHOLD,
) -> Transcript:
    raw_segments = get_field(response, "segments") or []
    segments: list[Segment] = []

    for index, item in enumerate(raw_segments):
        text = (get_field(item, "text") or "").strip()
        if not text:
            continue
        confidence = logprob_to_confidence(get_field(item, "avg_logprob"))
        # Hosted Whisper hallucinates over silence exactly as the local one does.
        if is_silence(get_field(item, "no_speech_prob"), confidence, no_speech_threshold):
            continue
        if is_repetition_loop(text):
            continue
        segments.append(
            Segment(
                id=index,
                start=float(get_field(item, "start", 0.0) or 0.0),
                end=float(get_field(item, "end", 0.0) or 0.0),
                text=text,
                confidence=confidence,
            )
        )

    # Some models return only flat text with no segment breakdown; keep the
    # transcript usable rather than returning nothing. This is only a fallback
    # for a response that had no segments at all — reaching for it after the
    # silence filter emptied the list would hand back, as one long cue, the
    # exact hallucination the filter just removed.
    if not segments and not raw_segments:
        text = (get_field(response, "text") or "").strip()
        duration = float(get_field(response, "duration", 0.0) or 0.0)
        if text:
            segments = [Segment(id=0, start=0.0, end=duration, text=text)]

    return Transcript(
        language=get_field(response, "language"),
        segments=segments,
        duration=float(get_field(response, "duration", 0.0) or 0.0)
        or (segments[-1].end if segments else 0.0),
        source=source,
        backend=backend,
    )


def logprob_to_confidence(avg_logprob) -> float | None:
    """Map Whisper's average token log-probability to a rough 0-1 confidence."""
    if avg_logprob is None:
        return None
    try:
        return max(0.0, min(1.0, math.exp(float(avg_logprob))))
    except (TypeError, ValueError, OverflowError):
        return None
