"""Dropping Whisper's silence hallucinations.

Given audio with no speech in it, Whisper does not return nothing. It returns
"You", "Thank you.", or "Thanks for watching!" — and confidently enough that the
model's own gate passes them: a segment is only treated as silence when the
no-speech probability is high *and* the average log-probability is below -1.0.
Real hallucinations routinely score better than that. On a silent 30s clip this
produced a one-word transcript reading "You".

Matching the phrases themselves is a losing game across languages, so we tighten
the second half of Whisper's own test instead: past the no-speech threshold, a
segment has to look confident to survive.
"""

from __future__ import annotations

__all__ = ["DEFAULT_NO_SPEECH_THRESHOLD", "is_silence"]

DEFAULT_NO_SPEECH_THRESHOLD = 0.6

# exp(-0.5) ~= 0.61, so this is Whisper's log-probability test with the bar
# raised from -1.0, applied only to segments already flagged as likely silence.
_CONFIDENT_ENOUGH = 0.6


def is_silence(
    no_speech_prob: float | None,
    confidence: float | None,
    threshold: float = DEFAULT_NO_SPEECH_THRESHOLD,
) -> bool:
    """Whether a segment is probably the model talking over silence.

    Args:
        no_speech_prob: The model's own estimate that the window holds no
            speech. ``None`` (a backend that does not report it) means keep.
        confidence: Segment confidence in 0-1, as derived from the average token
            log-probability.
        threshold: No-speech probability above which a segment is suspect. Set
            it to ``1.0`` to keep everything.

    Returns:
        True when the segment should be dropped.
    """
    if no_speech_prob is None:
        return False
    try:
        prob = float(no_speech_prob)
    except (TypeError, ValueError):
        return False
    if prob <= threshold:
        return False
    return confidence is None or confidence < _CONFIDENT_ENOUGH
