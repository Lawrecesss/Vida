"""Liveness checks against the real OpenRouter API.

Every other test in this suite stubs the network, which is why 0.1.0 shipped
with translation completely broken: the default model slug had been withdrawn
and returned 404, and no amount of stubbed testing could see that. These tests
exist to catch exactly that class of failure before a release goes out.

They are skipped unless ``VIDA_LIVE_SMOKE`` is set, so a normal ``pytest`` run
stays offline and free. CI sets it on tag pushes only.

Keep these minimal. They are a liveness gate, not a quality benchmark — every
assertion here should be one that fails *only* when the SDK is genuinely broken
for a new user, because a false failure blocks a release.
"""

from __future__ import annotations

import os

import pytest

from vida import Vida
from vida.config import VidaConfig
from vida.types import Segment, Transcript

pytestmark = pytest.mark.skipif(
    not os.getenv("VIDA_LIVE_SMOKE"),
    reason="live API check; set VIDA_LIVE_SMOKE=1 to run",
)


async def test_default_translation_model_is_alive():
    """The shipped default must actually translate and keep the timeline.

    Covers both `translation.model` and `analysis.synthesis_model`, which
    currently resolve to the same slug.
    """
    original = Transcript(
        language="en",
        duration=4.0,
        segments=[
            Segment(id=0, start=0.0, end=2.0, text="Hello, and welcome to the demo."),
            Segment(id=1, start=2.0, end=4.0, text="First we extract the audio track."),
        ],
    )

    async with Vida() as vida:
        translated = await vida.translate(original, "Spanish")

    assert [s.id for s in translated.segments] == [0, 1], "segment ids did not survive"
    for before, after in zip(original.segments, translated.segments, strict=True):
        assert after.start == before.start and after.end == before.end, "timestamps drifted"
        assert after.text.strip(), "empty translation"

    # If every line came back identical the model answered but ignored the task,
    # which is as broken for a user as a 404.
    assert any(
        a.text.strip() != b.text.strip()
        for a, b in zip(original.segments, translated.segments, strict=True)
    ), "nothing was actually translated"


async def test_default_analysis_model_is_alive():
    """The video model resolves and responds.

    Sent as plain text rather than with a clip: this is checking that the slug
    still exists, and a real video would make the gate slow and expensive
    without making it much more informative.
    """
    config = VidaConfig()
    async with Vida(config) as vida:
        reply = await vida.llm.complete(
            "Reply with the single word: ready",
            model=config.analysis.model,
            temperature=0.0,
            reasoning=False,
            timeout=90.0,
        )

    assert reply.strip(), f"{config.analysis.model} returned an empty response"
