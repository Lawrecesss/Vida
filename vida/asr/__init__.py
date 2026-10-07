"""Speech-to-text backends and selection."""

from __future__ import annotations

from vida.asr.base import Transcriber
from vida.asr.local_backend import LocalTranscriber
from vida.asr.openai_backend import OpenAITranscriber
from vida.asr.openrouter_backend import OpenRouterTranscriber
from vida.config import ASRConfig
from vida.errors import ConfigurationError

__all__ = [
    "Transcriber",
    "OpenRouterTranscriber",
    "OpenAITranscriber",
    "LocalTranscriber",
    "BACKENDS",
    "get_transcriber",
    "available_backends",
]

BACKENDS: dict[str, type[Transcriber]] = {
    "openrouter": OpenRouterTranscriber,
    "openai": OpenAITranscriber,
    "local": LocalTranscriber,
}

# `auto` walks this order and takes the first usable one. OpenRouter leads
# because it is the provider the rest of the SDK already needs a key for, so
# on a working install it is the one backend that is always configured.
_AUTO_ORDER = ("openrouter", "openai", "local")


def available_backends(config: ASRConfig | None = None) -> dict[str, str]:
    """Map every backend name to ``""`` if usable, or why it isn't."""
    config = config or ASRConfig()
    result: dict[str, str] = {}
    for name, cls in BACKENDS.items():
        ok, reason = cls(config).is_available()
        result[name] = "" if ok else reason
    return result


def get_transcriber(config: ASRConfig | None = None) -> Transcriber:
    """Build the transcriber described by ``config``.

    With ``backend="auto"`` the first usable backend in ``_AUTO_ORDER`` wins;
    if none are usable the error names what each one is missing.
    """
    config = config or ASRConfig()
    requested = config.backend

    if requested != "auto":
        cls = BACKENDS.get(requested)
        if cls is None:
            raise ConfigurationError(
                f"Unknown ASR backend {requested!r}. Choose one of: "
                f"{', '.join(sorted(BACKENDS))}, or 'auto'."
            )
        transcriber = cls(config)
        ok, reason = transcriber.is_available()
        if not ok:
            raise ConfigurationError(f"ASR backend {requested!r} is unavailable: {reason}")
        return transcriber

    problems: list[str] = []
    for name in _AUTO_ORDER:
        candidate = BACKENDS[name](config)
        ok, reason = candidate.is_available()
        if ok:
            return candidate
        problems.append(f"  - {name}: {reason}")

    raise ConfigurationError(
        "No ASR backend is available.\n"
        + "\n".join(problems)
        + "\n\nThe quickest fix is to export OPENROUTER_API_KEY, which the "
        "translation and analysis stages need anyway."
    )
