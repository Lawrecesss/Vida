"""The interface every speech-to-text backend implements."""

from __future__ import annotations

import abc

from vida.config import ASRConfig
from vida.types import Transcript

__all__ = ["Transcriber"]


class Transcriber(abc.ABC):
    """Turns one audio file into a :class:`~vida.types.Transcript`.

    Implementations only ever see a single, already-chunked audio file whose
    timeline starts at zero. Splitting long audio and shifting timestamps back
    onto the original timeline is the pipeline's job, not the backend's.
    """

    name: str = "base"

    def __init__(self, config: ASRConfig) -> None:
        self.config = config

    @property
    @abc.abstractmethod
    def default_model(self) -> str:
        """Model id used when the caller didn't pick one."""

    @property
    def model(self) -> str:
        return self.config.model or self.default_model

    @abc.abstractmethod
    async def transcribe_file(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> Transcript:
        """Transcribe one audio file.

        Args:
            audio_path: Path to a mono 16 kHz audio file.
            language: ISO-639-1 hint (e.g. ``"en"``). ``None`` auto-detects,
                which costs a little latency but handles unknown input.
            prompt: Optional context to bias decoding (names, jargon).

        Returns:
            A transcript whose segment timestamps are relative to this file.
        """

    @abc.abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Whether this backend can run right now.

        Returns ``(available, reason)`` — ``reason`` explains what's missing so
        backend selection can report something useful.
        """

    async def aclose(self) -> None:
        """Release any held resources. Override where it matters."""
        return
