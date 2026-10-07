"""ASR backend selection and per-call model resolution."""

import pytest

from vida.asr import BACKENDS, available_backends, get_transcriber
from vida.config import ASRConfig
from vida.errors import ConfigurationError


def test_unknown_backend_is_rejected_by_name():
    with pytest.raises(ConfigurationError, match="Unknown ASR backend"):
        get_transcriber(ASRConfig(backend="whisper.cpp"))


def test_explicit_backend_without_a_key_explains_why():
    config = ASRConfig(backend="openrouter", openrouter_api_key=None)
    with pytest.raises(ConfigurationError) as excinfo:
        get_transcriber(config)
    assert "openrouter" in str(excinfo.value)


def test_auto_reports_every_backend_when_none_are_usable(monkeypatch):
    for cls in BACKENDS.values():
        monkeypatch.setattr(cls, "is_available", lambda self: (False, "nope"))
    with pytest.raises(ConfigurationError) as excinfo:
        get_transcriber(ASRConfig(backend="auto"))
    message = str(excinfo.value)
    assert all(name in message for name in BACKENDS)


def test_auto_prefers_openrouter_when_several_are_usable(monkeypatch):
    for cls in BACKENDS.values():
        monkeypatch.setattr(cls, "is_available", lambda self: (True, ""))
    assert get_transcriber(ASRConfig(backend="auto")).name == "openrouter"


def test_auto_falls_through_to_the_next_usable_backend(monkeypatch):
    from vida.asr import LocalTranscriber, OpenAITranscriber, OpenRouterTranscriber

    monkeypatch.setattr(OpenRouterTranscriber, "is_available", lambda self: (False, "no key"))
    monkeypatch.setattr(OpenAITranscriber, "is_available", lambda self: (False, "no key"))
    monkeypatch.setattr(LocalTranscriber, "is_available", lambda self: (True, ""))
    assert get_transcriber(ASRConfig(backend="auto")).name == "local"


def test_available_backends_reports_a_reason_for_each():
    report = available_backends(ASRConfig())
    assert set(report) == set(BACKENDS)
    assert all(isinstance(reason, str) for reason in report.values())


def test_model_falls_back_to_the_backend_default():
    from vida.asr import OpenRouterTranscriber

    assert OpenRouterTranscriber(ASRConfig()).model == "openai/whisper-large-v3"
    assert OpenRouterTranscriber(ASRConfig(model="openai/whisper-large-v3-turbo")).model == (
        "openai/whisper-large-v3-turbo"
    )


def test_a_per_call_model_wins_over_the_configured_one():
    """Call > config > default, which is what lets a server choose per request."""
    from vida.asr import OpenRouterTranscriber

    transcriber = OpenRouterTranscriber(ASRConfig(model="configured"))
    assert transcriber.model_for(None) == "configured"
    assert transcriber.model_for("per-call") == "per-call"
    assert OpenRouterTranscriber(ASRConfig()).model_for("per-call") == "per-call"


def test_an_unknown_model_id_is_passed_through_untouched():
    """No allowlist anywhere: a model published tomorrow has to work today."""
    from vida.asr import OpenRouterTranscriber

    assert OpenRouterTranscriber(ASRConfig()).model_for("vendor/released-later") == (
        "vendor/released-later"
    )
