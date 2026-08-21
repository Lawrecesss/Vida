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

Both thresholds below are calibrated against a pair of measured cases rather
than one, which matters because the two overlap on raw noisy audio: a silent
clip hallucinated "Thank you." at no_speech_prob 0.607 / confidence 0.518,
while real speech under action-camera wind scored 0.607 / 0.567 — close enough
that no threshold separates them. Cleaning the audio first (see
``ASRConfig.audio_filter``) is what re-opens the gap: the same real speech then
scores at most 0.50 and the same hallucination 0.67. The filter is therefore
not only an accuracy win, it is what makes this test mean anything.
"""

from __future__ import annotations

import collections
import re
import string

__all__ = ["DEFAULT_NO_SPEECH_THRESHOLD", "is_silence", "is_repetition_loop"]

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


# Four is deliberately above "Fish! Fish!" and other real doubled exclamations,
# which are common in excited speech and must survive.
_LOOP_MINIMUM = 4

# One word owning four fifths of a segment is a loop; three quarters is still
# reachable by a real stutter ("I I I think"), so the bar sits above it.
_LOOP_DOMINANCE = 0.8


def is_repetition_loop(text: str) -> bool:
    """Whether a segment is one word stuttered on a loop.

    Whisper's other failure over noise is not invention but repetition: given
    a stretch of wind or clatter it latches onto a syllable and emits it until
    the window ends — "Bam bam bam bam bam", "and then, then, then, then".
    Cleaning the audio surfaces more real speech and, with it, more of these,
    so they are worth naming: when four or more words are almost all the same
    word, the segment is not a transcription of anything.
    """
    words = [
        word.strip(string.punctuation + "\u2026\u2019")
        for word in re.split(r"\s+", text.strip().lower())
    ]
    words = [word for word in words if word]
    if len(words) < _LOOP_MINIMUM:
        return False
    return collections.Counter(words).most_common(1)[0][1] / len(words) >= _LOOP_DOMINANCE
