"""Public data types returned by the SDK.

These are pydantic models so they serialize straight to JSON in a FastAPI
response, and so timestamps survive the round trip through translation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = [
    "MediaInfo",
    "Segment",
    "Transcript",
    "SegmentAnalysis",
    "Analysis",
    "VideoInsight",
]


class MediaInfo(BaseModel):
    """What we know about a media file before touching a model."""

    path: str
    duration: float = Field(description="Duration in seconds.")
    size_mb: float
    has_audio: bool = True
    width: int | None = None
    height: int | None = None


class Segment(BaseModel):
    """One timestamped span of speech.

    ``start``/``end`` are seconds from the beginning of the *original* media,
    not of whatever chunk the ASR backend happened to see.
    """

    id: int
    start: float
    end: float
    text: str
    speaker: str | None = None
    confidence: float | None = None

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)


class Transcript(BaseModel):
    """A full transcript: timestamped segments plus their joined text."""

    language: str | None = Field(
        default=None, description="BCP-47-ish code the audio was detected as, e.g. 'en'."
    )
    segments: list[Segment] = Field(default_factory=list)
    duration: float = 0.0
    source: str | None = Field(default=None, description="Path of the media it came from.")
    backend: str | None = Field(default=None, description="ASR backend that produced it.")

    @property
    def text(self) -> str:
        """The whole transcript as one block of text."""
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    def to_srt(self) -> str:
        """Render as SubRip (.srt)."""
        from vida.export.subtitles import to_srt

        return to_srt(self)

    def to_vtt(self) -> str:
        """Render as WebVTT (.vtt)."""
        from vida.export.subtitles import to_vtt

        return to_vtt(self)

    def save(self, path: str, fmt: Literal["srt", "vtt", "txt", "json"] | None = None) -> str:
        """Write the transcript to ``path``.

        The format is inferred from the file extension unless ``fmt`` is given.
        Returns the path written, so it chains.
        """
        from vida.export.subtitles import save_transcript

        return save_transcript(self, path, fmt)


class SegmentAnalysis(BaseModel):
    """Visual analysis of one chunk of video."""

    index: int
    status: Literal["ok", "error"]
    analysis: str
    mode: Literal["video", "frames", "failed"] = "video"
    start: float | None = None
    end: float | None = None


class Analysis(BaseModel):
    """The result of watching a video (as opposed to listening to it)."""

    summary: str
    segments: list[SegmentAnalysis] = Field(default_factory=list)
    query: str | None = None
    source: str | None = None


class VideoInsight(BaseModel):
    """Everything :meth:`vida.Vida.process` produced for one video."""

    media: MediaInfo
    transcript: Transcript | None = None
    translations: dict[str, Transcript] = Field(
        default_factory=dict, description="Target language code -> translated transcript."
    )
    analysis: Analysis | None = None
    timings: dict[str, float] = Field(
        default_factory=dict, description="Wall-clock seconds per stage, for profiling."
    )

    def transcript_for(self, language: str | None = None) -> Transcript | None:
        """The transcript in ``language``, or the source transcript if omitted."""
        if language is None:
            return self.transcript
        return self.translations.get(language)

    def to_srt(self, language: str | None = None) -> str:
        tr = self.transcript_for(language)
        if tr is None:
            raise KeyError(f"No transcript available for language {language!r}")
        return tr.to_srt()

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
