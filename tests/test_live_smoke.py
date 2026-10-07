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

import math
import os
import struct
import wave

import pytest

from vida import Vida
from vida.config import ASRConfig, VidaConfig
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


def _tone_wav(path: str, seconds: float = 1.0, rate: int = 16000) -> str:
    """A second of a 440 Hz tone, so the ASR gate needs no fixture media.

    Deliberately not speech: this checks that the model id resolves and the
    endpoint answers in the documented shape, which is the failure a withdrawn
    slug produces. What it transcribes to is not the point, and asserting on
    that would make the gate flaky for reasons that break no user.
    """
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(
            b"".join(
                struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
                for i in range(int(rate * seconds))
            )
        )
    return path


async def test_default_asr_model_is_alive(tmp_path):
    """The shipped ASR default resolves on OpenRouter and answers.

    Transcription moved onto OpenRouter's /audio/transcriptions, so the ASR
    model id is now exactly as exposed to a withdrawn slug as the translation
    one that broke 0.1.0 — and just as invisible to the stubbed suite.
    """
    from vida.asr.openrouter_backend import OpenRouterTranscriber

    audio = _tone_wav(str(tmp_path / "tone.wav"))
    config = ASRConfig()
    transcriber = OpenRouterTranscriber(config)
    try:
        transcript = await transcriber.transcribe_file(audio)
    finally:
        await transcriber.aclose()

    assert transcript.backend == "openrouter"
    # A Transcript at all means the model id resolved and the response parsed;
    # the segment list may legitimately be empty for a tone.
    assert transcript.duration >= 0.0
