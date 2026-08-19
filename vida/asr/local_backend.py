"""Local faster-whisper backend.

Nothing leaves the machine, and there's no per-call cost — but the first call
downloads the model, and CPU inference is far slower than the hosted backends.
Model instances are cached per (model, device, compute type) since loading one
is expensive.
"""

from __future__ import annotations

import asyncio

from vida.asr.base import Transcriber
from vida.asr.groq_backend import _logprob_to_confidence
from vida.errors import MissingDependencyError, TranscriptionError
from vida.types import Segment, Transcript

__all__ = ["LocalTranscriber"]

_MODEL_CACHE: dict[tuple[str, str, str], object] = {}
_CACHE_LOCK = asyncio.Lock()


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
                "the 'faster-whisper' package is not installed (pip install 'vida[local]')",
            )
        return True, ""

    async def _get_model(self):
        device = self.config.local_device
        compute_type = self.config.local_compute_type
        key = (self.model, device, compute_type)

        async with _CACHE_LOCK:
            if key not in _MODEL_CACHE:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise MissingDependencyError("faster-whisper", "local") from exc

                # Loading pulls weights from disk (or the network on first run);
                # keep it off the event loop.
                _MODEL_CACHE[key] = await asyncio.to_thread(
                    WhisperModel, self.model, device=device, compute_type=compute_type
                )
            return _MODEL_CACHE[key]

    async def transcribe_file(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> Transcript:
        model = await self._get_model()

        def _run():
            segments, info = model.transcribe(
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
            raw_segments, info = await asyncio.to_thread(_run)
        except Exception as exc:
            raise TranscriptionError(f"Local transcription failed: {exc}") from exc

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
