"""Building the vocabulary prompt Whisper actually accepts.

Whisper has exactly one vocabulary-biasing mechanism: a free-text prompt,
treated as if it were the transcript of the audio immediately preceding this
one. There is no term list, no weights, no phone hints. So a glossary becomes
text — but text with a budget, because the prompt window is about 224 tokens
and anything past it is silently dropped from the *front*, which is the worst
possible failure mode: the terms fall out and nothing says so.

Hence the explicit word cap here. When the budget binds, the glossary wins and
the free-text prompt is what gets trimmed: a caller who passed a glossary named
those terms deliberately, whereas prose context is a hint about tone.
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["build_prompt", "merge_glossaries"]

MAX_PROMPT_WORDS = 180
"""Conservative proxy for Whisper's ~224-token prompt window.

Words, not tokens, because counting tokens would mean shipping a tokenizer for
every backend. Proper nouns — exactly what a glossary holds — often cost more
than one token each, so the gap is deliberate headroom rather than slack.
"""


def merge_glossaries(*sources: Iterable[str] | None) -> list[str]:
    """Combine glossaries in order, dropping blanks and repeats.

    Order is preserved because it is priority: config-level terms come first,
    call-level ones extend them, and truncation bites at the end.
    """
    merged: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for term in source or ():
            cleaned = " ".join(str(term).split())
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                merged.append(cleaned)
    return merged


def build_prompt(
    prompt: str | None,
    glossary: Iterable[str] | None,
    *,
    max_words: int = MAX_PROMPT_WORDS,
) -> str | None:
    """Combine free text and glossary terms into one prompt string.

    Returns ``None`` when there is nothing to say, so callers can pass the
    result straight through to a backend that treats ``None`` as "no prompt".
    """
    terms = merge_glossaries(glossary)
    words = (prompt or "").split()

    if not terms:
        if not words:
            return None
        return " ".join(words[:max_words])

    # Reserve the glossary's space first, then spend what is left on the prose.
    rendered = _fit_terms(terms, max_words - 1)  # -1 for the "Vocabulary:" label
    used = sum(len(term.split()) for term in rendered) + 1
    remaining = max(max_words - used, 0)

    lead = " ".join(words[:remaining])
    vocabulary = "Vocabulary: " + ", ".join(rendered) + "."
    return f"{lead} {vocabulary}".strip() if lead else vocabulary


def _fit_terms(terms: list[str], budget: int) -> list[str]:
    """As many whole terms as fit in ``budget`` words.

    Whole terms only — half of "the Sundering" biases toward the wrong thing.
    """
    fitted: list[str] = []
    used = 0
    for term in terms:
        cost = len(term.split())
        if used + cost > budget:
            break
        fitted.append(term)
        used += cost
    return fitted
