"""Vida — fast video analysis, transcription, and translation.

Quick start::

    import asyncio
    from vida import Vida

    async def main():
        async with Vida() as vida:
            insight = await vida.process(
                "talk.mp4",
                translate_to=["Spanish", "Japanese"],
                analyze=True,
            )
            print(insight.analysis.summary)
            print(insight.transcript.text)
            insight.translations["Spanish"].save("talk.es.srt")

    asyncio.run(main())

Or from synchronous code::

    from vida import Vida

    paths = Vida().subtitles_sync("talk.mp4", languages=["Spanish"])
"""

from __future__ import annotations

from vida.asr import available_backends, get_transcriber
from vida.client import Vida
from vida.config import AnalysisConfig, ASRConfig, TranslationConfig, VidaConfig
from vida.errors import (
    AnalysisError,
    ConfigurationError,
    FFmpegNotFoundError,
    MediaError,
    MissingDependencyError,
    TranscriptionError,
    TranslationError,
    VidaError,
)
from vida.export import save_transcript, to_srt, to_vtt
from vida.types import (
    Analysis,
    MediaInfo,
    Segment,
    SegmentAnalysis,
    Transcript,
    VideoInsight,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # Client
    "Vida",
    # Config
    "VidaConfig",
    "ASRConfig",
    "TranslationConfig",
    "AnalysisConfig",
    # Types
    "Transcript",
    "Segment",
    "Analysis",
    "SegmentAnalysis",
    "MediaInfo",
    "VideoInsight",
    # Export helpers
    "to_srt",
    "to_vtt",
    "save_transcript",
    # Backends
    "get_transcriber",
    "available_backends",
    # Errors
    "VidaError",
    "ConfigurationError",
    "MissingDependencyError",
    "MediaError",
    "FFmpegNotFoundError",
    "TranscriptionError",
    "TranslationError",
    "AnalysisError",
]
