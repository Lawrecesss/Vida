"""Local faster-whisper backend.

Nothing leaves the machine, and there's no per-call cost — but the first call
downloads the model, and CPU inference is far slower than the hosted backends.
Model instances are cached per (model, device, compute type) since loading one
is expensive.
"""

from __future__ import annotations

import asyncio
import logging

from vida.asr.base import Transcriber
from vida.asr.groq_backend import _logprob_to_confidence
from vida.errors import MissingDependencyError, TranscriptionError
from vida.types import Segment, Transcript

__all__ = ["LocalTranscriber"]

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[tuple[str, str, str], object] = {}
_CACHE_LOCK = asyncio.Lock()

# What "auto" settled on, remembered for the life of the process. Probing the
# GPU costs a model load and, when it fails, a wasted transcription attempt;
# there is no reason to pay that more than once.
_AUTO_DEVICE: str | None = None

# int8 is the sensible CPU default; on a GPU it wastes the hardware.
_DEFAULT_COMPUTE = {"cuda": "float16", "cpu": "int8"}

# CUDA breaks in two places — loading the model, and the first inference, since
# CTranslate2 pulls in cuBLAS lazily. Matching the message is a heuristic, but
# the alternative is retrying genuine audio errors on CPU at great expense.
_CUDA_MARKERS = ("cuda", "cublas", "cudnn", "libcu", "gpu")


def _is_cuda_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _CUDA_MARKERS)


_CUDA_PRELOADED = False

# cublasLt has to come before cublas, which links against it.
_CUDA_LIBS = ("libcublasLt.so.*", "libcublas.so.*", "libcudnn*.so.*")


def _preload_cuda_libraries() -> None:
    """Make pip-installed CUDA libraries loadable without LD_LIBRARY_PATH.

    The ``nvidia-*`` wheels put their shared objects inside site-packages,
    which the dynamic loader never searches. LD_LIBRARY_PATH would fix that but
    only if it is set before the process starts, which is not something a
    library can arrange for its caller. Opening them RTLD_GLOBAL puts them in
    the process image under their sonames, where CTranslate2's own dlopen finds
    them already resident. Best effort throughout: if the wheels are absent the
    GPU attempt simply fails as before and we fall back to the CPU.
    """
    global _CUDA_PRELOADED
    if _CUDA_PRELOADED:
        return
    _CUDA_PRELOADED = True

    import ctypes
    import glob
    import os
    import sysconfig

    roots = sorted(glob.glob(os.path.join(sysconfig.get_paths()["purelib"], "nvidia", "*", "lib")))
    for pattern in _CUDA_LIBS:
        for root in roots:
            for path in sorted(glob.glob(os.path.join(root, pattern))):
                try:
                    ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                except OSError as exc:  # noqa: PERF203 - one bad library is not fatal
                    logger.debug("Could not preload %s: %s", path, exc)


class LocalTranscriber(Transcriber):
    name = "local"

    @property
    def default_model(self) -> str:
        # `small` is the sweet spot for CPU: usable accuracy without the
        # multi-gigabyte download and latency of `large-v3`.
        return "small"

    def is_available(self) -> tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return (
                False,
                "the 'faster-whisper' package is not installed (pip install 'vida-sdk[local]')",
            )
        return True, ""

    def _compute_type(self, device: str) -> str:
        configured = self.config.local_compute_type
        if configured and configured != "auto":
            return configured
        return _DEFAULT_COMPUTE.get(device, "int8")

    async def _load(self, device: str):
        """Build (or reuse) a model on `device`. Caller holds the cache lock."""
        key = (self.model, device, self._compute_type(device))
        if key not in _MODEL_CACHE:
            if device == "cuda":
                _preload_cuda_libraries()
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise MissingDependencyError("faster-whisper", "local") from exc

            # Loading pulls weights from disk (or the network on first run);
            # keep it off the event loop.
            _MODEL_CACHE[key] = await asyncio.to_thread(
                WhisperModel, self.model, device=device, compute_type=key[2]
            )
        return _MODEL_CACHE[key]

    async def _get_model(self):
        global _AUTO_DEVICE

        configured = self.config.local_device
        if configured != "auto":
            async with _CACHE_LOCK:
                return await self._load(configured)

        async with _CACHE_LOCK:
            if _AUTO_DEVICE is not None:
                return await self._load(_AUTO_DEVICE)

            # Prefer the GPU, but never let its absence be fatal.
            try:
                model = await self._load("cuda")
            except Exception as exc:
                if not _is_cuda_failure(exc):
                    raise
                logger.warning(
                    "Could not load the model on the GPU (%s); using the CPU instead. "
                    "Set VIDA_LOCAL_DEVICE=cpu to skip this probe.",
                    exc,
                )
                _AUTO_DEVICE = "cpu"
                return await self._load("cpu")

            _AUTO_DEVICE = "cuda"
            return model

    async def _demote_to_cpu(self, exc: Exception):
        """Drop the unusable GPU model and return a CPU one in its place."""
        global _AUTO_DEVICE

        async with _CACHE_LOCK:
            _MODEL_CACHE.pop((self.model, "cuda", self._compute_type("cuda")), None)
            _AUTO_DEVICE = "cpu"
            logger.warning(
                "GPU transcription failed (%s); retrying on the CPU. "
                "Set VIDA_LOCAL_DEVICE=cpu to skip this probe.",
                exc,
            )
            return await self._load("cpu")

    async def transcribe_file(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> Transcript:
        model = await self._get_model()

        def _run(active):
            segments, info = active.transcribe(
                audio_path,
                language=language,
                initial_prompt=prompt,
                vad_filter=True,           # skip silence instead of hallucinating over it
                beam_size=5,
                temperature=0.0,
            )
            # `segments` is a lazy generator; materialise it inside the thread.
            return list(segments), info

        try:
            raw_segments, info = await asyncio.to_thread(_run, model)
        except Exception as exc:
            # CTranslate2 loads cuBLAS on first use, so a GPU we picked
            # ourselves can fail here rather than at load time. An explicit
            # VIDA_LOCAL_DEVICE=cuda is the user's call and stays fatal.
            if self.config.local_device != "auto" or not _is_cuda_failure(exc):
                raise TranscriptionError(f"Local transcription failed: {exc}") from exc

            model = await self._demote_to_cpu(exc)
            try:
                raw_segments, info = await asyncio.to_thread(_run, model)
            except Exception as retry_exc:
                raise TranscriptionError(
                    f"Local transcription failed on the CPU fallback: {retry_exc}"
                ) from retry_exc

        segments: list[Segment] = []
        for index, item in enumerate(raw_segments):
            text = (item.text or "").strip()
            if not text:
                continue
            segments.append(
                Segment(
                    id=index,
                    start=float(item.start),
                    end=float(item.end),
                    text=text,
                    confidence=_logprob_to_confidence(getattr(item, "avg_logprob", None)),
                )
            )

        return Transcript(
            language=getattr(info, "language", None) or language,
            segments=segments,
            duration=float(getattr(info, "duration", 0.0) or 0.0)
            or (segments[-1].end if segments else 0.0),
            source=audio_path,
            backend=self.name,
        )
