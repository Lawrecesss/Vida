"""Vocabulary biasing: turning a glossary into the prompt Whisper accepts."""

import pytest

from vida.asr.base import Transcriber
from vida.asr.glossary import MAX_PROMPT_WORDS, build_prompt, merge_glossaries
from vida.asr.pipeline import transcribe_audio_file
from vida.config import ASRConfig
from vida.types import Segment, Transcript


def test_nothing_to_say_is_no_prompt():
    # None rather than "", so a backend that treats a prompt as optional can
    # keep omitting the field entirely.
    assert build_prompt(None, None) is None
    assert build_prompt("", []) is None


def test_free_text_survives_untouched():
    assert build_prompt("A talk about Kubernetes.", None) == "A talk about Kubernetes."


def test_glossary_alone_becomes_a_vocabulary_line():
    assert build_prompt(None, ["Aelith", "Marrowgate"]) == "Vocabulary: Aelith, Marrowgate."


def test_prompt_and_glossary_are_combined():
    result = build_prompt("Fantasy film.", ["Aelith"])
    assert result == "Fantasy film. Vocabulary: Aelith."


def test_terms_are_deduplicated_case_insensitively_in_order():
    assert merge_glossaries(["Aelith", "Corvain"], ["aelith", "Marrowgate"]) == [
        "Aelith",
        "Corvain",
        "Marrowgate",
    ]


def test_blank_terms_are_dropped():
    assert merge_glossaries(["", "  ", "Aelith"]) == ["Aelith"]


def test_internal_whitespace_is_normalised():
    assert merge_glossaries(["the   Sundering\n"]) == ["the Sundering"]


def test_the_glossary_wins_the_budget():
    # Whisper drops overflow from the front of the prompt silently, so the
    # terms someone deliberately named must not be what falls off the edge.
    prose = " ".join(["filler"] * MAX_PROMPT_WORDS)
    result = build_prompt(prose, ["Aelith", "Corvain"])
    assert "Aelith" in result and "Corvain" in result
    assert len(result.split()) <= MAX_PROMPT_WORDS


def test_free_text_alone_is_still_capped():
    result = build_prompt(" ".join(["filler"] * (MAX_PROMPT_WORDS * 2)), None)
    assert len(result.split()) == MAX_PROMPT_WORDS


def test_a_term_is_never_half_included():
    # Half of "the Sundering" biases toward the wrong word.
    terms = [f"term{i}" for i in range(MAX_PROMPT_WORDS)] + ["the Sundering"]
    result = build_prompt(None, terms)
    assert "the Sundering" not in result
    assert "Sundering" not in result


class RecordingTranscriber(Transcriber):
    """Captures the prompt the pipeline actually handed the backend."""

    name = "recording"

    def __init__(self, config):
        super().__init__(config)
        self.prompts: list[str | None] = []

    @property
    def default_model(self):
        return "recording-1"

    def is_available(self):
        return True, ""

    async def transcribe_file(self, audio_path, *, language=None, prompt=None):
        self.prompts.append(prompt)
        return Transcript(
            language="en",
            segments=[Segment(id=0, start=0.0, end=1.0, text="hello")],
            duration=1.0,
        )


async def _run(config: ASRConfig, **kwargs) -> RecordingTranscriber:
    """Drive the single-chunk path, which touches no ffmpeg and no disk."""
    stub = RecordingTranscriber(config)
    await transcribe_audio_file(
        stub, "/nonexistent/audio.flac", 5.0, config, **kwargs
    )
    return stub


async def test_config_level_glossary_reaches_the_backend():
    config = ASRConfig(glossary=["Aelith"], detect_seconds=0, chunk_seconds=600)
    stub = await _run(config)
    assert stub.prompts == ["Vocabulary: Aelith."]


async def test_call_level_glossary_extends_the_configured_one():
    # Config-level terms are the ones that apply to everything; a call adds the
    # vocabulary of this particular title rather than replacing the set.
    config = ASRConfig(glossary=["Aelith"], detect_seconds=0, chunk_seconds=600)
    stub = await _run(config, glossary=["Marrowgate"])
    assert stub.prompts == ["Vocabulary: Aelith, Marrowgate."]


async def test_prompt_and_glossary_arrive_together():
    config = ASRConfig(glossary=["Aelith"], detect_seconds=0, chunk_seconds=600)
    stub = await _run(config, prompt="Fantasy film.")
    assert stub.prompts == ["Fantasy film. Vocabulary: Aelith."]


async def test_no_glossary_leaves_the_prompt_exactly_as_given():
    config = ASRConfig(detect_seconds=0, chunk_seconds=600)
    stub = await _run(config, prompt="Fantasy film.")
    assert stub.prompts == ["Fantasy film."]


async def test_no_vocabulary_at_all_sends_no_prompt():
    config = ASRConfig(detect_seconds=0, chunk_seconds=600)
    stub = await _run(config)
    assert stub.prompts == [None]


def test_glossary_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("VIDA_ASR_GLOSSARY", "Aelith, the Sundering ,Corvain")
    assert ASRConfig().glossary == ["Aelith", "the Sundering", "Corvain"]


def test_an_empty_environment_glossary_is_no_glossary(monkeypatch):
    monkeypatch.setenv("VIDA_ASR_GLOSSARY", " , ")
    assert ASRConfig().glossary == []


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_env_bool_accepts_the_spellings_people_type(monkeypatch, raw):
    from vida.config import _env_bool

    monkeypatch.setenv("VIDA_TEST_FLAG", raw)
    assert _env_bool("VIDA_TEST_FLAG", False) is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "   "])
def test_env_bool_rejects_everything_else(monkeypatch, raw):
    from vida.config import _env_bool

    monkeypatch.setenv("VIDA_TEST_FLAG", raw)
    # A blank value means "unset", not "false" — it falls back to the default.
    assert _env_bool("VIDA_TEST_FLAG", False) is False
    if raw.strip():
        assert _env_bool("VIDA_TEST_FLAG", True) is False
