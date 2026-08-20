"""OpenAI Whisper backend.

Note the 25 MB per-request cap: the pipeline's audio chunking already keeps
requests well under it at the default chunk length.
"""

from __future__ import annotations

import asyncio

from vida.asr.base import Transcriber
from vida.asr.groq_backend import _read_bytes, _to_transcript
from vida.config import ASRConfig
from vida.errors import MissingDependencyError, TranscriptionError
from vida.types import Transcript

__all__ = ["OpenAITranscriber"]

MAX_REQUEST_MB = 25.0


class OpenAITranscriber(Transcriber):
    name = "openai"

    def __init__(self, config: ASRConfig) -> None:
        super().__init__(config)
        self._client = None

    @property
    def default_model(self) -> str:
        return "whisper-1"

    def is_available(self) -> tuple[bool, str]:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False, "the 'openai' package is not installed (pip install 'vida-sdk[openai]')"
        if not self.config.openai_api_key:
            return False, "OPENAI_API_KEY is not set"
        return True, ""

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise MissingDependencyError("openai", "openai") from exc
            if not self.config.openai_api_key:
                raise TranscriptionError("OPENAI_API_KEY is not set")
            self._client = AsyncOpenAI(
                api_key=self.config.openai_api_key, timeout=self.config.timeout
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
        payload = await asyncio.to_thread(_read_bytes, audio_path)

        size_mb = len(payload) / (1024 * 1024)
        if size_mb > MAX_REQUEST_MB:
            raise TranscriptionError(
                f"{audio_path} is {size_mb:.1f}MB, over OpenAI's {MAX_REQUEST_MB}MB limit. "
                "Lower ASRConfig.chunk_seconds so the pipeline splits it further."
            )

        kwargs: dict = {
            "file": (audio_path.rsplit("/", 1)[-1], payload),
            "model": self.model,
            "response_format": "verbose_json",
            "temperature": 0.0,
        }
        # Only whisper-1 exposes segment timestamps; the newer 4o transcribe
        # models reject the parameter outright.
        if self.model == "whisper-1":
            kwargs["timestamp_granularities"] = ["segment"]
        if language:
            kwargs["language"] = language
        if prompt:
            kwargs["prompt"] = prompt

        try:
            response = await client.audio.transcriptions.create(**kwargs)
        except Exception as exc:
            raise TranscriptionError(f"OpenAI transcription failed: {exc}") from exc

        return _to_transcript(response, audio_path, self.name)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
