"""The OpenRouter speech-to-text backend, with the HTTP call stubbed.

What matters here is the request: the model goes out exactly as handed in, the
glossary prompt survives as a provider option, and nothing about the backend is
specific to one model id.
"""

import json

import pytest

from vida.asr.openrouter_backend import OpenRouterTranscriber, audio_format_for
from vida.config import ASRConfig
from vida.errors import TranscriptionError

AUDIO = b"not really audio, but bytes are bytes"


@pytest.fixture
def transcriber(monkeypatch):
    """A backend whose only network call records its payload and replies."""
    config = ASRConfig(openrouter_api_key="test-key")
    backend = OpenRouterTranscriber(config)
    sent: list[dict] = []

    async def fake_post(self, url, payload, timeout):
        sent.append({"url": url, "payload": payload, "timeout": timeout})
        return {
            "language": "en",
            "duration": 2.0,
            "text": "hello",
            "segments": [{"id": 0, "start": 0.0, "end": 2.0, "text": "hello"}],
        }

    monkeypatch.setattr("vida.llm.OpenRouterClient._post", fake_post)
    backend.sent = sent
    return backend


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "chunk0000.flac"
    path.write_bytes(AUDIO)
    return str(path)


async def test_the_default_model_goes_out_when_nothing_overrides_it(transcriber, audio_file):
    await transcriber.transcribe_file(audio_file)
    assert transcriber.sent[0]["payload"]["model"] == "openai/whisper-large-v3"


async def test_a_per_call_model_is_sent_untouched(transcriber, audio_file):
    # The point of the per-call argument: a server passes through whatever its
    # own request named, including a model this SDK has never heard of.
    await transcriber.transcribe_file(audio_file, model="vendor/some-new-stt")
    assert transcriber.sent[0]["payload"]["model"] == "vendor/some-new-stt"


async def test_the_configured_model_is_the_fallback(monkeypatch, audio_file):
    backend = OpenRouterTranscriber(
        ASRConfig(openrouter_api_key="k", model="openai/whisper-large-v3-turbo")
    )
    sent = []

    async def fake_post(self, url, payload, timeout):
        sent.append(payload)
        return {"text": "hi", "duration": 1.0}

    monkeypatch.setattr("vida.llm.OpenRouterClient._post", fake_post)
    await backend.transcribe_file(audio_file)
    assert sent[0]["model"] == "openai/whisper-large-v3-turbo"


async def test_the_request_asks_for_segment_timestamps(transcriber, audio_file):
    # Without segments there are no subtitles, only a wall of text.
    await transcriber.transcribe_file(audio_file, language="en")
    payload = transcriber.sent[0]["payload"]
    assert payload["response_format"] == "verbose_json"
    assert payload["timestamp_granularities"] == ["segment"]
    assert payload["language"] == "en"
    assert payload["input_audio"]["format"] == "flac"


async def test_audio_is_base64_encoded_whole(transcriber, audio_file):
    import base64

    await transcriber.transcribe_file(audio_file)
    data = transcriber.sent[0]["payload"]["input_audio"]["data"]
    assert base64.b64decode(data) == AUDIO


async def test_no_language_hint_means_no_language_field(transcriber, audio_file):
    await transcriber.transcribe_file(audio_file)
    assert "language" not in transcriber.sent[0]["payload"]


async def test_the_prompt_rides_as_a_provider_option(transcriber, audio_file):
    # OpenRouter has no top-level `prompt` for transcription; the glossary would
    # vanish silently if it were sent as one.
    await transcriber.transcribe_file(audio_file, prompt="Vocabulary: Aelith.")
    options = transcriber.sent[0]["payload"]["provider"]["options"]
    assert options["groq"]["prompt"] == "Vocabulary: Aelith."


async def test_no_prompt_means_no_provider_block(transcriber, audio_file):
    await transcriber.transcribe_file(audio_file)
    assert "provider" not in transcriber.sent[0]["payload"]


async def test_configured_provider_options_are_merged_not_replaced(monkeypatch, audio_file):
    backend = OpenRouterTranscriber(
        ASRConfig(openrouter_api_key="k", provider_options={"groq": {"zdr": True}})
    )
    sent = []

    async def fake_post(self, url, payload, timeout):
        sent.append(payload)
        return {"text": "hi", "duration": 1.0}

    monkeypatch.setattr("vida.llm.OpenRouterClient._post", fake_post)
    await backend.transcribe_file(audio_file, prompt="Vocabulary: Aelith.")

    options = sent[0]["provider"]["options"]["groq"]
    assert options == {"zdr": True, "prompt": "Vocabulary: Aelith."}
    # The config object must not have grown the prompt: it outlives the call.
    assert backend.config.provider_options == {"groq": {"zdr": True}}


async def test_an_explicit_provider_prompt_is_not_overwritten(monkeypatch, audio_file):
    backend = OpenRouterTranscriber(
        ASRConfig(openrouter_api_key="k", provider_options={"groq": {"prompt": "mine"}})
    )
    sent = []

    async def fake_post(self, url, payload, timeout):
        sent.append(payload)
        return {"text": "hi", "duration": 1.0}

    monkeypatch.setattr("vida.llm.OpenRouterClient._post", fake_post)
    await backend.transcribe_file(audio_file, prompt="assembled")
    assert sent[0]["provider"]["options"]["groq"]["prompt"] == "mine"


async def test_the_response_becomes_a_transcript(transcriber, audio_file):
    transcript = await transcriber.transcribe_file(audio_file)
    assert transcript.backend == "openrouter"
    assert transcript.language == "en"
    assert [s.text for s in transcript.segments] == ["hello"]


async def test_segments_without_confidence_fields_are_kept(transcriber, audio_file):
    """OpenRouter does not document no_speech_prob, so nothing may be dropped on
    its absence — losing real speech is worse than keeping a hallucination."""
    transcript = await transcriber.transcribe_file(audio_file)
    assert transcript.segments[0].confidence is None
    assert len(transcript.segments) == 1


def test_an_unsupported_container_is_refused_by_name(tmp_path):
    with pytest.raises(TranscriptionError, match="does not accept"):
        audio_format_for(str(tmp_path / "voice.opus"))


def test_the_containers_the_pipeline_produces_are_accepted():
    assert audio_format_for("/tmp/x.flac") == "flac"
    assert audio_format_for("/tmp/X.FLAC") == "flac"


def test_a_missing_key_is_reported_not_guessed():
    backend = OpenRouterTranscriber(ASRConfig(openrouter_api_key=None))
    ok, reason = backend.is_available()
    assert not ok
    assert "OPENROUTER_API_KEY" in reason


async def test_the_payload_is_json_serialisable(transcriber, audio_file):
    # It goes out through httpx's json=, so anything unserialisable is a 500
    # at request time rather than a test failure here.
    await transcriber.transcribe_file(audio_file, prompt="p", language="en")
    json.dumps(transcriber.sent[0]["payload"])


# ---------------------------------------------------------------------------
# Flat-JSON fallback: not every STT model serves verbose_json
# ---------------------------------------------------------------------------

# Verbatim from OpenRouter, and the escaping is the point: the message reaches
# the SDK as the raw JSON body, so the format name arrives backslash-escaped. A
# matcher written with real quotes passes a hand-written test and never fires in
# production, which is exactly what happened before this test existed.
VERBOSE_REFUSAL = (
    'OpenRouter rejected the request (400): {"error":{"message":"The selected model '
    'does not support response_format \\"verbose_json\\". Use \\"json\\" instead.",'
    '"code":400}}'
)


@pytest.fixture(autouse=True)
def _forget_flat_only():
    """The flat-only memo is process-wide; don't leak it between tests."""
    from vida.asr import openrouter_backend

    openrouter_backend._FLAT_ONLY.clear()
    yield
    openrouter_backend._FLAT_ONLY.clear()


def _refusing_client(monkeypatch, *, refuse_verbose=True, flat_body=None):
    """Stub `_post` that refuses verbose_json the way OpenRouter really does."""
    from vida.errors import VidaError

    calls: list[dict] = []

    async def fake_post(self, url, payload, timeout):
        calls.append(payload)
        if payload["response_format"] == "verbose_json":
            if refuse_verbose:
                raise VidaError(VERBOSE_REFUSAL)
            return {"text": "hi", "duration": 2.0, "segments": [
                {"id": 0, "start": 0.0, "end": 2.0, "text": "hi"}
            ]}
        return flat_body if flat_body is not None else {"text": "flat text"}

    monkeypatch.setattr("vida.llm.OpenRouterClient._post", fake_post)
    return calls


async def test_a_model_that_rejects_verbose_json_still_transcribes(monkeypatch, audio_file):
    calls = _refusing_client(monkeypatch, flat_body={"text": "flat text", "usage": {"seconds": 9}})
    backend = OpenRouterTranscriber(ASRConfig(openrouter_api_key="k"))

    transcript = await backend.transcribe_file(audio_file, model="vendor/flat-only")

    assert [p["response_format"] for p in calls] == ["verbose_json", "json"]
    assert [s.text for s in transcript.segments] == ["flat text"]


async def test_the_flat_cue_gets_an_end_time_from_usage_seconds(monkeypatch, audio_file):
    # A 0.0 -> 0.0 cue renders as an empty subtitle, so the duration matters.
    _refusing_client(monkeypatch, flat_body={"text": "flat text", "usage": {"seconds": 9}})
    backend = OpenRouterTranscriber(ASRConfig(openrouter_api_key="k"))

    transcript = await backend.transcribe_file(audio_file, model="vendor/flat-only")
    assert transcript.duration == 9.0
    assert transcript.segments[0].end == 9.0


async def test_the_flat_cue_falls_back_to_measuring_the_file(monkeypatch, audio_file):
    """A token-priced model bills in tokens and reports no seconds at all."""
    from vida.types import MediaInfo

    _refresh = _refusing_client(
        monkeypatch, flat_body={"text": "flat text", "usage": {"total_tokens": 24}}
    )
    assert _refresh is not None

    def fake_probe(path):
        return MediaInfo(path=path, duration=42.0, size_mb=1.0, has_audio=True)

    monkeypatch.setattr("vida.asr.openrouter_backend.probe", fake_probe)
    backend = OpenRouterTranscriber(ASRConfig(openrouter_api_key="k"))

    transcript = await backend.transcribe_file(audio_file, model="vendor/flat-only")
    assert transcript.segments[0].end == 42.0


async def test_only_the_first_chunk_pays_the_failed_probe(monkeypatch, audio_file):
    # Without the memo a long video would burn one rejected request per chunk.
    calls = _refusing_client(monkeypatch, flat_body={"text": "a", "usage": {"seconds": 1}})
    backend = OpenRouterTranscriber(ASRConfig(openrouter_api_key="k"))

    await backend.transcribe_file(audio_file, model="vendor/flat-only")
    await backend.transcribe_file(audio_file, model="vendor/flat-only")
    await backend.transcribe_file(audio_file, model="vendor/flat-only")

    formats = [p["response_format"] for p in calls]
    assert formats == ["verbose_json", "json", "json", "json"]


async def test_the_memo_is_per_model(monkeypatch, audio_file):
    calls = _refusing_client(monkeypatch, flat_body={"text": "a", "usage": {"seconds": 1}})
    backend = OpenRouterTranscriber(ASRConfig(openrouter_api_key="k"))

    await backend.transcribe_file(audio_file, model="vendor/flat-one")
    await backend.transcribe_file(audio_file, model="vendor/flat-two")

    # Each model is asked once; one model's answer says nothing about another's.
    assert [p["response_format"] for p in calls] == [
        "verbose_json", "json", "verbose_json", "json",
    ]


async def test_a_verbose_capable_model_never_takes_the_flat_path(monkeypatch, audio_file):
    calls = _refusing_client(monkeypatch, refuse_verbose=False)
    backend = OpenRouterTranscriber(ASRConfig(openrouter_api_key="k"))

    await backend.transcribe_file(audio_file, model="vendor/good")
    assert [p["response_format"] for p in calls] == ["verbose_json"]


async def test_an_unrelated_400_is_not_retried(monkeypatch, audio_file):
    """Only the verbose_json refusal earns a second request. A bad key or
    oversized payload must fail once and say so, not cost twice."""
    from vida.errors import VidaError

    calls = []

    async def fake_post(self, url, payload, timeout):
        calls.append(payload)
        raise VidaError(
            'OpenRouter rejected the request (400): {"error":{"message":"The selected '
            'model does not support large audio inputs","code":400}}'
        )

    monkeypatch.setattr("vida.llm.OpenRouterClient._post", fake_post)
    backend = OpenRouterTranscriber(ASRConfig(openrouter_api_key="k"))

    with pytest.raises(TranscriptionError, match="large audio inputs"):
        await backend.transcribe_file(audio_file, model="vendor/picky")
    assert len(calls) == 1


async def test_the_flat_request_drops_the_timestamp_parameter(monkeypatch, audio_file):
    # Asking for segment granularity alongside response_format=json is the
    # combination the model already refused.
    calls = _refusing_client(monkeypatch, flat_body={"text": "a", "usage": {"seconds": 1}})
    backend = OpenRouterTranscriber(ASRConfig(openrouter_api_key="k"))

    await backend.transcribe_file(audio_file, model="vendor/flat-only")
    assert "timestamp_granularities" not in calls[1]
