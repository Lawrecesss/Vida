"""Word- and character-error rate against a reference transcript.

WER is only comparable when both sides are normalised the same way, and the
normalisation is where most of the judgement lives. Whisper punctuates and
capitalises; a hand-corrected reference does too, but never identically. Scoring
raw text therefore measures typography as much as recognition. What is stripped
here — case, punctuation, redundant whitespace — is the standard set for ASR
evaluation, and it is applied to reference and hypothesis alike.

Numbers are deliberately *not* normalised. "1995" against "nineteen ninety-five"
counts as an error, because for subtitles it is one: the two do not read the
same on screen.
"""

from __future__ import annotations

import re
import string
import unicodedata
from dataclasses import dataclass, field

__all__ = ["Score", "normalize", "score_transcript"]

_PUNCTUATION = str.maketrans({character: " " for character in string.punctuation + "—–…«»„“”‘’"})
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Case-fold, strip punctuation, and collapse whitespace."""
    # NFKC first so a curly apostrophe and a straight one become the same
    # character before the punctuation table sees either.
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_PUNCTUATION)
    return _WHITESPACE.sub(" ", text).strip().lower()


@dataclass
class Score:
    """One hypothesis measured against one reference."""

    fixture_id: str
    config: str
    wer: float
    cer: float
    reference_words: int
    hypothesis_words: int
    substitutions: int = 0
    deletions: int = 0
    insertions: int = 0
    seconds: float = 0.0
    error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def deletion_rate(self) -> float:
        """Share of reference words the system simply never returned.

        Broken out because it is the failure this project keeps hitting:
        Whisper goes silent under noise rather than mistranscribing, which
        shows up as deletions and is invisible in a WER number that a few
        substitutions could explain just as well.
        """
        if not self.reference_words:
            return 0.0
        return self.deletions / self.reference_words

    def to_dict(self) -> dict:
        return {
            "fixture_id": self.fixture_id,
            "config": self.config,
            "wer": self.wer,
            "cer": self.cer,
            "reference_words": self.reference_words,
            "hypothesis_words": self.hypothesis_words,
            "substitutions": self.substitutions,
            "deletions": self.deletions,
            "insertions": self.insertions,
            "deletion_rate": self.deletion_rate,
            "seconds": self.seconds,
            "error": self.error,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Score:
        return cls(
            fixture_id=data["fixture_id"],
            config=data["config"],
            wer=data["wer"],
            cer=data["cer"],
            reference_words=data["reference_words"],
            hypothesis_words=data["hypothesis_words"],
            substitutions=data.get("substitutions", 0),
            deletions=data.get("deletions", 0),
            insertions=data.get("insertions", 0),
            seconds=data.get("seconds", 0.0),
            error=data.get("error"),
            extra=data.get("extra", {}),
        )


def _require_jiwer():
    try:
        import jiwer
    except ImportError as exc:  # pragma: no cover - depends on the host
        raise SystemExit(
            "The ASR eval harness needs jiwer. Install it with:\n"
            "    uv pip install -e '.[eval]'"
        ) from exc
    return jiwer


def score_transcript(
    fixture_id: str,
    config: str,
    reference: str,
    hypothesis: str,
    *,
    seconds: float = 0.0,
    extra: dict | None = None,
) -> Score:
    """Measure ``hypothesis`` against ``reference``."""
    jiwer = _require_jiwer()

    reference_text = normalize(reference)
    hypothesis_text = normalize(hypothesis)
    reference_words = len(reference_text.split())

    if not reference_text:
        raise ValueError(f"Reference for {fixture_id!r} is empty after normalisation")

    output = jiwer.process_words(reference_text, hypothesis_text)
    cer = jiwer.cer(reference_text, hypothesis_text)

    return Score(
        fixture_id=fixture_id,
        config=config,
        wer=output.wer,
        cer=float(cer),
        reference_words=reference_words,
        hypothesis_words=len(hypothesis_text.split()),
        substitutions=output.substitutions,
        deletions=output.deletions,
        insertions=output.insertions,
        seconds=seconds,
        extra=extra or {},
    )
