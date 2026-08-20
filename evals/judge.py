"""Scoring: what information survived into an arm's output.

Each arm is run once per video with no query, producing a description. The judge
then tries to answer the question set *from that description alone*. This
measures what the representation captured, rather than how well a model answers
a question it was pointed at — and it keeps the run cost at
``videos x arms`` rather than ``videos x arms x questions``.

The judge never sees the video, only text, so it cannot leak information the arm
failed to capture.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from vida.llm import OpenRouterClient, strip_reasoning

__all__ = ["Question", "Verdict", "score_arm"]

_SCORE_RE = re.compile(r"SCORE:\s*([012])", re.IGNORECASE)
_WHY_RE = re.compile(r"WHY:\s*(.+)", re.IGNORECASE | re.DOTALL)

_SYSTEM = (
    "You grade whether a description of a video contains a specific piece of "
    "information. You are strict, and you never use outside knowledge."
)

_PROMPT = """Below is a description of a video, produced by an automated system.
You cannot see the video itself.

Description:
\"\"\"
{description}
\"\"\"

Question: {question}
Correct answer: {expected}

Decide whether the description contains enough information to answer the
question correctly.

SCORE 2 - the description clearly and correctly contains the answer.
SCORE 1 - the description gestures at it but is vague, partial, or hedged.
SCORE 0 - the description does not contain it, or contradicts the correct answer.

Judge only what is written. Do not give credit for something a reader would have
to already know, and do not penalize wording that differs from the correct
answer as long as the meaning matches.

Reply in exactly this form:
SCORE: <0, 1, or 2>
WHY: <one sentence>"""


@dataclass
class Question:
    id: str
    question: str
    expected: str
    kind: str  # "descriptive" | "temporal"

    @classmethod
    def from_dict(cls, raw: dict) -> Question:
        kind = raw.get("kind", "descriptive")
        if kind not in ("descriptive", "temporal"):
            raise ValueError(f"question {raw.get('id')!r}: kind must be descriptive or temporal")
        return cls(
            id=str(raw["id"]),
            question=raw["question"],
            expected=raw["expected"],
            kind=kind,
        )


@dataclass
class Verdict:
    question_id: str
    kind: str
    score: int
    why: str

    def to_dict(self) -> dict:
        return vars(self)


async def score_arm(
    description: str,
    questions: list[Question],
    *,
    client: OpenRouterClient,
    model: str,
    concurrency: int = 4,
    timeout: float = 120.0,
) -> list[Verdict]:
    """Grade one arm's description against the question set."""
    if not description.strip():
        return [Verdict(q.id, q.kind, 0, "arm produced no description") for q in questions]

    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def _one(question: Question) -> Verdict:
        prompt = _PROMPT.format(
            description=description[:24000],
            question=question.question,
            expected=question.expected,
        )
        try:
            async with semaphore:
                raw = await client.complete(
                    prompt, model=model, temperature=0.0, system=_SYSTEM, timeout=timeout
                )
        except Exception as exc:  # noqa: BLE001 - a failed grade is not a zero
            return Verdict(question.id, question.kind, -1, f"judge failed: {exc}")

        text = strip_reasoning(raw)
        match = _SCORE_RE.search(text)
        if not match:
            return Verdict(question.id, question.kind, -1, f"unparseable verdict: {text[:120]}")

        why = _WHY_RE.search(text)
        return Verdict(
            question.id,
            question.kind,
            int(match.group(1)),
            (why.group(1).strip().splitlines()[0] if why else "").strip(),
        )

    return await asyncio.gather(*(_one(q) for q in questions))
