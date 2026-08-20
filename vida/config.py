"""Runtime configuration.

Everything is overridable in code; the defaults come from the environment so a
bare ``Vida()`` works once the relevant key is exported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from dotenv import find_dotenv, load_dotenv

ASRBackend = Literal["groq", "openai", "local", "auto"]

# Loaded once at import. `.env.secret` is the convention this repo already used;
# `.env` is the one everyone else expects, so honour both. A bare relative name
# resolves against the working directory and stops there, so running from a
# subdirectory — backend/, or anywhere at all for an installed CLI — silently
# missed the file; search upward from the CWD instead.
for _candidate in (".env.secret", ".env"):
    _found = find_dotenv(_candidate, usecwd=True)
    if _found:
        load_dotenv(_found, override=False)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class ASRConfig:
    """Speech-to-text settings."""

    backend: ASRBackend = "auto"
    """Which engine to use. ``auto`` picks the fastest one whose key is present."""

    model: str | None = None
    """Backend-specific model id. ``None`` uses that backend's fast default."""

    groq_api_key: str | None = field(default_factory=lambda: os.getenv("GROQ_API_KEY"))
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))

    no_speech_threshold: float = field(
        default_factory=lambda: _env_float("VIDA_NO_SPEECH_THRESHOLD", 0.6)
    )
    """Drop segments the model flags as silence above this probability; 1.0 keeps everything."""

    local_device: str = field(default_factory=lambda: os.getenv("VIDA_LOCAL_DEVICE", "auto"))
    """``auto`` tries the GPU and falls back to the CPU; ``cuda``/``cpu`` force one."""

    local_compute_type: str = field(
        default_factory=lambda: os.getenv("VIDA_LOCAL_COMPUTE_TYPE", "auto")
    )
    """``auto`` picks float16 on a GPU and int8 on a CPU."""

    chunk_seconds: float = field(
        default_factory=lambda: _env_float("VIDA_ASR_CHUNK_SECONDS", 600.0)
    )
    """Audio longer than this is split and transcribed in parallel."""

    chunk_overlap: float = field(default_factory=lambda: _env_float("VIDA_ASR_CHUNK_OVERLAP", 2.0))
    """Seconds of overlap between audio chunks, so words on a seam aren't lost."""

    concurrency: int = field(default_factory=lambda: _env_int("VIDA_ASR_CONCURRENCY", 8))
    """How many audio chunks to transcribe at once."""

    timeout: float = field(default_factory=lambda: _env_float("VIDA_ASR_TIMEOUT", 300.0))


@dataclass
class TranslationConfig:
    """Settings for translating a transcript."""

    # Free-tier slugs get withdrawn without notice: the previous default here
    # started returning 404 and broke translation on a clean install. Verify a
    # replacement round-trips the <s id="N"> markers before changing this.
    model: str = field(
        default_factory=lambda: os.getenv(
            "VIDA_TRANSLATION_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"
        )
    )
    batch_size: int = field(default_factory=lambda: _env_int("VIDA_TRANSLATION_BATCH_SIZE", 40))
    """Segments per LLM call. Larger batches are cheaper; smaller ones parallelize better."""

    concurrency: int = field(default_factory=lambda: _env_int("VIDA_TRANSLATION_CONCURRENCY", 8))
    temperature: float = field(default_factory=lambda: _env_float("VIDA_TRANSLATION_TEMPERATURE", 0.0))
    timeout: float = field(default_factory=lambda: _env_float("VIDA_TRANSLATION_TIMEOUT", 180.0))
    retries: int = field(default_factory=lambda: _env_int("VIDA_TRANSLATION_RETRIES", 3))


@dataclass
class AnalysisConfig:
    """Settings for the visual (frames/video) analysis pipeline."""

    model: str = field(
        default_factory=lambda: os.getenv(
            "VIDA_VIDEO_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
        )
    )
    synthesis_model: str = field(
        default_factory=lambda: os.getenv(
            "VIDA_REASONING_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"
        )
    )
    max_segment_mb: float = field(default_factory=lambda: _env_float("VIDA_MAX_SEGMENT_MB", 20.0))
    max_segment_seconds: float = field(
        default_factory=lambda: _env_float("VIDA_MAX_SEGMENT_SECONDS", 60.0)
    )
    segment_overlap: float = field(default_factory=lambda: _env_float("VIDA_SEGMENT_OVERLAP", 2.0))
    concurrency: int = field(default_factory=lambda: _env_int("VIDA_ANALYSIS_CONCURRENCY", 5))
    temperature: float = field(default_factory=lambda: _env_float("VIDA_ANALYSIS_TEMPERATURE", 0.2))
    timeout: float = field(default_factory=lambda: _env_float("VIDA_ANALYSIS_TIMEOUT", 120.0))
    retries: int = field(default_factory=lambda: _env_int("VIDA_ANALYSIS_RETRIES", 3))
    frames_per_segment: int = field(default_factory=lambda: _env_int("VIDA_FRAMES_PER_SEGMENT", 6))


@dataclass
class VidaConfig:
    """Top-level config passed to :class:`vida.Vida`."""

    asr: ASRConfig = field(default_factory=ASRConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)

    openrouter_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY")
    )
    work_dir: str = field(
        default_factory=lambda: os.getenv("VIDA_WORK_DIR", "") or ""
    )
    """Scratch directory for extracted audio and video chunks. Empty means a temp dir."""

    @classmethod
    def from_env(cls) -> VidaConfig:
        return cls()
