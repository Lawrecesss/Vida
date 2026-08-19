"""Normalising ASR and LLM responses."""

import pytest

from vida.asr.groq_backend import _logprob_to_confidence, _to_transcript
from vida.errors import VidaError
from vida.llm import _extract_text, strip_reasoning


def test_verbose_json_becomes_a_transcript():
    transcript = _to_transcript(
        {
            "language": "en",
            "duration": 4.2,
            "text": "hello world",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": " hello", "avg_logprob": -0.1},
                {"start": 2.0, "end": 4.2, "text": " world", "avg_logprob": -0.2},
            ],
        },
        "a.flac",
        "groq",
    )
    assert [s.text for s in transcript.segments] == ["hello", "world"]
    assert transcript.language == "en"
    assert transcript.duration == 4.2
    assert transcript.segments[0].confidence == pytest.approx(0.9048, abs=1e-3)


def test_blank_segments_are_dropped():
    transcript = _to_transcript(
        {"segments": [{"start": 0, "end": 1, "text": "   "}, {"start": 1, "end": 2, "text": "hi"}]},
        "a.flac",
        "groq",
    )
    assert len(transcript.segments) == 1


def test_response_without_segments_falls_back_to_flat_text():
    transcript = _to_transcript(
        {"text": "just the text", "duration": 3.0, "language": "en"}, "a.flac", "groq"
    )
    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == "just the text"
    assert transcript.segments[0].end == 3.0


def test_object_style_responses_work_too():
    class Segment:
        start, end, text, avg_logprob = 0.0, 1.0, "hi", None

    class Response:
        language, duration, text = "fr", 1.0, "hi"

        def __init__(self):
            self.segments = [Segment()]

    transcript = _to_transcript(Response(), "a.flac", "openai")
    assert transcript.language == "fr"
    assert transcript.segments[0].text == "hi"


def test_confidence_is_clamped_and_none_safe():
    assert _logprob_to_confidence(None) is None
    assert _logprob_to_confidence("bad") is None
    assert _logprob_to_confidence(0.0) == 1.0
    assert 0.0 <= _logprob_to_confidence(-5.0) <= 1.0


def test_strip_reasoning_removes_closed_blocks():
    assert strip_reasoning("<think>hmm</think>Answer") == "Answer"
    assert strip_reasoning("<reasoning>a</reasoning> B") == "B"


def test_strip_reasoning_drops_an_unclosed_block():
    assert strip_reasoning("Partial answer<think>never closed") == "Partial answer"


def test_extract_text_handles_list_content():
    body = {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}
    assert _extract_text(body) == "ab"


def test_extract_text_surfaces_api_errors():
    with pytest.raises(VidaError, match="rate limited"):
        _extract_text({"error": {"message": "rate limited"}})


def test_extract_text_rejects_an_empty_choice_list():
    with pytest.raises(VidaError, match="no choices"):
        _extract_text({"choices": []})
