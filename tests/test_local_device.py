"""Device selection for the local backend.

`auto` means "use the GPU if it actually works". A machine with an NVIDIA
driver but no CUDA libraries looks GPU-capable right up until CTranslate2 tries
to load cuBLAS — which it does lazily, on the first inference rather than at
model load — so both failure points have to fall back.
"""

import pytest

from vida.asr import local_backend
from vida.asr.local_backend import LocalTranscriber
from vida.config import ASRConfig
from vida.errors import TranscriptionError

CUDA_ERROR = RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")


@pytest.fixture(autouse=True)
def _clean_module_state():
    """The device choice and the model cache both outlive a single call."""
    local_backend._MODEL_CACHE.clear()
    local_backend._AUTO_DEVICE = None
    yield
    local_backend._MODEL_CACHE.clear()
    local_backend._AUTO_DEVICE = None


class _Info:
    language = "en"
    duration = 2.0


class _Segment:
    def __init__(self):
        self.id = 0
        self.start = 0.0
        self.end = 2.0
        self.text = "hello"
        self.avg_logprob = -0.2


class _FakeModel:
    """Stands in for WhisperModel, optionally failing the way CUDA does."""

    instances: list["_FakeModel"] = []

    def __init__(self, model, device=None, compute_type=None, fail_on=()):
        self.model = model
        self.device = device
        self.compute_type = compute_type
        _FakeModel.instances.append(self)

    def transcribe(self, path, **kwargs):
        if self.device == "cuda":
            raise CUDA_ERROR
        return iter([_Segment()]), _Info()


@pytest.fixture
def whisper(monkeypatch):
    _FakeModel.instances = []

    def factory(load_fails_on=()):
        def _construct(model, device=None, compute_type=None):
            if device in load_fails_on:
                raise CUDA_ERROR
            return _FakeModel(model, device=device, compute_type=compute_type)

        monkeypatch.setattr("faster_whisper.WhisperModel", _construct)
        return _FakeModel

    return factory


async def test_auto_prefers_the_gpu(whisper):
    whisper()
    model = await LocalTranscriber(ASRConfig(backend="local"))._get_model()
    assert model.device == "cuda"
    assert model.compute_type == "float16"  # int8 would waste the hardware


async def test_auto_falls_back_when_the_gpu_will_not_load(whisper):
    whisper(load_fails_on={"cuda"})
    model = await LocalTranscriber(ASRConfig(backend="local"))._get_model()
    assert (model.device, model.compute_type) == ("cpu", "int8")


async def test_auto_falls_back_when_the_gpu_fails_mid_transcription(whisper):
    # The GPU model builds fine; cuBLAS only fails once inference starts.
    whisper()
    transcript = await LocalTranscriber(ASRConfig(backend="local")).transcribe_file("a.wav")

    assert transcript.segments[0].text == "hello"
    assert [m.device for m in _FakeModel.instances] == ["cuda", "cpu"]
    assert local_backend._AUTO_DEVICE == "cpu"


async def test_the_gpu_is_probed_only_once(whisper):
    whisper(load_fails_on={"cuda"})
    transcriber = LocalTranscriber(ASRConfig(backend="local"))
    await transcriber._get_model()
    await transcriber._get_model()

    assert [m.device for m in _FakeModel.instances] == ["cpu"]


async def test_an_explicit_gpu_choice_stays_fatal(whisper):
    # Asking for cuda by name and silently getting cpu would hide a real
    # misconfiguration behind a 10x slowdown.
    whisper()
    config = ASRConfig(backend="local", local_device="cuda")
    with pytest.raises(TranscriptionError, match="libcublas"):
        await LocalTranscriber(config).transcribe_file("a.wav")


async def test_an_explicit_compute_type_is_honoured(whisper):
    whisper()
    config = ASRConfig(backend="local", local_compute_type="int8_float16")
    model = await LocalTranscriber(config)._get_model()
    assert model.compute_type == "int8_float16"
