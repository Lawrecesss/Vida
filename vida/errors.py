"""Exception hierarchy for the Vida SDK.

Every error raised by the SDK derives from :class:`VidaError`, so callers can
wrap an entire pipeline in a single ``except VidaError``.
"""

from __future__ import annotations


class VidaError(Exception):
    """Base class for every error raised by the SDK."""


class ConfigurationError(VidaError):
    """A required credential or setting is missing or invalid."""


class MissingDependencyError(VidaError):
    """An optional dependency is needed for the requested backend.

    Carries the pip extra that installs it so the message is actionable.
    """

    def __init__(self, package: str, extra: str) -> None:
        super().__init__(
            f"{package!r} is required for this backend. "
            f"Install it with: pip install 'vida[{extra}]'"
        )
        self.package = package
        self.extra = extra


class MediaError(VidaError):
    """The media file could not be read, probed, or transcoded."""


class FFmpegNotFoundError(MediaError):
    """No usable ffmpeg binary was found on the system or in imageio-ffmpeg."""


class TranscriptionError(VidaError):
    """The ASR backend failed to produce a transcript."""


class TranslationError(VidaError):
    """The translation backend failed."""


class AnalysisError(VidaError):
    """The visual analysis pipeline failed."""
