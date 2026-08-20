"""Groq Whisper backend — the fastest hosted option we support.

``whisper-large-v3-turbo`` on Groq runs at well over 100x realtime, which is
what makes "transcribe an hour of video in seconds" achievable.
"""

from __future__ import annotations

import asyncio
import math

from vida.asr.base import Transcriber
from vida.config import ASRConfig
from vida.errors import MissingDependencyError, TranscriptionError
from vida.types import Segment, Transcript

__all__ = ["GroqTranscriber"]


class GroqTranscriber(Transcriber):
    name = "groq"

    def __init__(self, config: ASRConfig) -> None:
        super().__init__(config)
        self._client = None

    @property
    def default_model(self) -> str:
        return "whisper-large-v3-turbo"

    def is_available(self) -> tuple[bool, str]:
        try:
            import groq  # noqa: F401
        except ImportError:
            return False, "the 'groq' package is not installed (pip install 'vida-sdk[groq]')"
        if not self.config.groq_api_key:
            return False, "GROQ_API_KEY is not set"
        return True, ""

    def _get_client(self):
        if self._client is None:
            try:
                from groq import AsyncGroq
            except ImportError as exc:
                raise MissingDependencyError("groq", "groq") from exc
            if not self.config.groq_api_key:
                raise TranscriptionError("GROQ_API_KEY is not set")
            self._client = AsyncGroq(
                api_key=self.config.groq_api_key, timeout=self.config.timeout
            )
        return self._client

    async def transcribe_file(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> Transcript:
        client = self._get_client()

        # The SDK wants bytes it can stream; read once so a retry doesn't need
        # to rewind a consumed file handle.
        payload = await asyncio.to_thread(_read_bytes, audio_path)

        kwargs: dict = {
            "file": (audio_path.rsplit("/", 1)[-1], payload),
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities": ["segment"],
            "temperature": 0.0,
        }
        if language:
            kwargs["language"] = language
        if prompt:
            kwargs["prompt"] = prompt

        try:
            response = await client.audio.transcriptions.create(**kwargs)
        except Exception as exc:
            raise TranscriptionError(f"Groq transcription failed: {exc}") from exc

        return _to_transcript(response, audio_path, self.name)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _get(obj, key, default=None):
    """Read a field whether the SDK handed back a model object or a plain dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_transcript(response, source: str, backend: str) -> Transcript:
    raw_segments = _get(response, "segments") or []
    segments: list[Segment] = []

    for index, item in enumerate(raw_segments):
        text = (_get(item, "text") or "").strip()
        if not text:
            continue
        avg_logprob = _get(item, "avg_logprob")
        segments.append(
            Segment(
                id=index,
                start=float(_get(item, "start", 0.0) or 0.0),
                end=float(_get(item, "end", 0.0) or 0.0),
                text=text,
                confidence=_logprob_to_confidence(avg_logprob),
            )
        )

    # Some models return only flat text with no segment breakdown; keep the
    # transcript usable rather than returning nothing.
    if not segments:
        text = (_get(response, "text") or "").strip()
        duration = float(_get(response, "duration", 0.0) or 0.0)
        if text:
            segments = [Segment(id=0, start=0.0, end=duration, text=text)]

    return Transcript(
        language=_get(response, "language"),
        segments=segments,
        duration=float(_get(response, "duration", 0.0) or 0.0)
        or (segments[-1].end if segments else 0.0),
        source=source,
        backend=backend,
    )


def _logprob_to_confidence(avg_logprob) -> float | None:
    """Map Whisper's average token log-probability to a rough 0-1 confidence."""
    if avg_logprob is None:
        return None
    try:
        return max(0.0, min(1.0, math.exp(float(avg_logprob))))
    except (TypeError, ValueError, OverflowError):
        return None
