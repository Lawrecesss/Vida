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


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var, accepting the spellings people actually type."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    """Split a comma-separated env var into terms.

    Commas rather than spaces because the entries are phrases — a character
    name is routinely two words, and splitting those apart would bias the
    model toward each half separately.
    """
    raw = os.getenv(name)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


DEFAULT_AUDIO_FILTER = (
    # Band-limit to the speech range first: an action camera's wind rumble is
    # mostly below 100 Hz, and nothing above 7 kHz survives Whisper's 16 kHz
    # input anyway. afftdn then subtracts what is left of the noise floor, and
    # loudnorm brings quiet talkers up to a consistent level.
    "highpass=f=100,"
    "afftdn=nr=20:nf=-30,"
    "lowpass=f=7000,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)
"""Measured on wind-heavy action-camera audio: see ``docs`` note in :mod:`vida.asr.silence`."""


@dataclass
class ASRConfig:
    """Speech-to-text settings."""

    backend: ASRBackend = "auto"
    """Which engine to use. ``auto`` picks the fastest one whose key is present."""

    model: str | None = field(default_factory=lambda: os.getenv("VIDA_ASR_MODEL"))
    """Backend-specific model id. ``None`` uses that backend's default.

    Set ``VIDA_ASR_MODEL`` to override without touching code. On Groq the
    choice that matters is the default ``whisper-large-v3`` against
    ``whisper-large-v3-turbo``: turbo is a distilled decoder (4 layers rather
    than 32) and gives up real accuracy on accented and non-English speech in
    exchange for speed both are already fast enough at.

    On ``local`` the default is ``small``, chosen for interactive latency on a
    CPU. Batch work is the opposite trade: for a movie nobody is waiting on,
    ``medium`` or ``large-v3`` is the single cheapest accuracy improvement
    available here, and it costs no new configuration — this one field feeds
    every backend.
    """

    groq_api_key: str | None = field(default_factory=lambda: os.getenv("GROQ_API_KEY"))
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))

    glossary: list[str] = field(default_factory=lambda: _env_list("VIDA_ASR_GLOSSARY"))
    """Names and jargon to bias decoding toward; ``VIDA_ASR_GLOSSARY`` is comma-separated.

    Whisper's only vocabulary mechanism is the free-text ``prompt``, so these
    are rendered into it (see :mod:`vida.asr.glossary`). Terms set here apply to
    every call; ``Vida.transcribe(glossary=[...])`` extends them per call, which
    is the level that matters for film, where the vocabulary is per title.
    """

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

    audio_filter: str = field(
        default_factory=lambda: os.getenv("VIDA_ASR_AUDIO_FILTER", DEFAULT_AUDIO_FILTER)
    )
    """ffmpeg filter chain applied once during audio extraction; empty disables it.

    Real-world video is noisy — wind on a phone or an action camera sits right
    on top of the speech — and Whisper does not merely mistranscribe through
    noise, it goes quiet: whole exchanges come back as nothing at all. Cleaning
    the audio before it reaches the model recovers them, and it also restores
    the confidence scores :mod:`vida.asr.silence` depends on, which noise
    otherwise pushes into the range real speech and hallucinations share.
    """

    dialogue_filter: str | None = field(
        default_factory=lambda: os.getenv("VIDA_ASR_DIALOGUE_FILTER") or None
    )
    """ffmpeg filter applied in the *source* channel layout, before the mono downmix.

    Off by default, and deliberately so: the presets in :mod:`vida.media.audio`
    each assume something about how the source was mixed — ``pan=mono|c0=FC``
    needs a real 5.1 centre channel and fails outright without one — and the
    material reaching a general-purpose SDK is unknown. Film dialogue lives on
    that centre channel, so where it applies it removes the score and effects
    bed rather than trying to denoise them back out.

    Note that turning this on moves the noise floor that
    :attr:`no_speech_threshold` and :mod:`vida.asr.silence` were calibrated
    against, so re-measure hallucination rate before relying on it.
    """

    detect_seconds: float = field(
        default_factory=lambda: _env_float("VIDA_ASR_DETECT_SECONDS", 30.0)
    )
    """Seconds of audio used to detect the language before transcribing; 0 disables.

    Whisper picks a language per 30-second window, so left to itself it can
    change its mind halfway through a recording and start decoding English as
    a language that merely sounds like it. Detecting once up front and pinning
    the answer for every window costs one short extra request and removes that
    failure entirely. Set it to 0 to let each window decide for itself, which
    is what a genuinely multilingual recording wants.
    """

    chunk_seconds: float = field(
        default_factory=lambda: _env_float("VIDA_ASR_CHUNK_SECONDS", 600.0)
    )
    """Audio longer than this is split and transcribed in parallel."""

    chunk_overlap: float = field(default_factory=lambda: _env_float("VIDA_ASR_CHUNK_OVERLAP", 2.0))
    """Seconds of overlap between audio chunks, so words on a seam aren't lost."""

    silence_aware_chunking: bool = field(
        default_factory=lambda: _env_bool("VIDA_ASR_SILENCE_AWARE_CHUNKING", False)
    )
    """Snap chunk boundaries to a gap in the speech instead of cutting on the clock.

    Off by default. The overlap already rescues a word split across a seam, so
    this is the smaller, second-order win — not splitting the word at all —
    bought with one ``silencedetect`` pass per boundary. Measure it with
    ``evals/asr`` on real fixtures before turning it on: on material with no
    real gaps, every boundary falls back to the fixed one and the pass is pure
    cost.
    """

    chunk_boundary_search_seconds: float = field(
        default_factory=lambda: _env_float("VIDA_ASR_CHUNK_BOUNDARY_SEARCH", 3.0)
    )
    """How far either side of a boundary to look for silence.

    Bounded on purpose: chunks stay within a few seconds of the configured
    length, so the parallelism the chunking exists for is unaffected.
    """

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
