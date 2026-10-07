"""OpenRouter speech-to-text — the default hosted backend.

OpenRouter is this SDK's one hosted provider, for transcription as much as for
translation and analysis: the same key, the same pooled client, the same retry
policy, and one bill. Nothing here knows which Whisper it is talking to. The
model id is a string that arrives from config or from a single call and goes
straight into the request, so a model published after this release works
without a code change, and a server can pick one per request from its own
payload.

Two things vary by provider behind an OpenRouter model id, and both are
handled rather than assumed:

* Segment fields are optional. ``avg_logprob`` and ``no_speech_prob`` are not
  in the documented response schema, and without them the silence filter in
  :mod:`vida.asr.silence` keeps everything it is shown — which is the right
  failure, since the alternative is dropping real speech on missing evidence.
* A vocabulary prompt is a *provider* option, not a request field. See
  :data:`PROMPT_PROVIDERS`.
* ``verbose_json`` is not universal. The Whisper models serve it; the newer
  token-priced STT models reject it outright. See :data:`_FLAT_ONLY`.
* How much audio a model takes in one request is its own business. Some reject a
  payload the Whisper models accept ("does not support large audio inputs"), and
  the lever for that is ``ASRConfig.chunk_seconds`` — the pipeline already
  splits long audio, so a smaller chunk is the whole fix.
"""

from __future__ import annotations

import asyncio
import copy
import os

from vida.asr.base import Transcriber
from vida.asr.whisper_response import get_field, read_bytes, to_transcript
from vida.config import ASRConfig
from vida.errors import TranscriptionError, VidaError
from vida.llm import OpenRouterClient
from vida.media.video import probe
from vida.types import Transcript

__all__ = ["OpenRouterTranscriber", "PROMPT_PROVIDERS"]

DEFAULT_MODEL = "openai/whisper-large-v3"
"""Not ``...-turbo``: turbo's distilled 4-layer decoder mishears accented
speech in ways that read as plausible English ("the crap that we are eating"),
and at these speeds the difference between the two is seconds on an hour of
video. Set ``VIDA_ASR_MODEL=openai/whisper-large-v3-turbo`` to trade back."""

PROMPT_PROVIDERS = ("groq",)
"""Provider slugs documented to accept a transcription ``prompt``.

Whisper's only vocabulary mechanism is that free-text prompt, and OpenRouter
exposes it under ``provider.options.<slug>`` rather than as a request field —
there is no provider-neutral spelling. Options are keyed by slug and OpenRouter
forwards only the entry belonging to whichever provider served the request, so
naming one that didn't costs nothing. Add a slug through
:attr:`ASRConfig.provider_options` to carry the glossary somewhere else too.
"""

_FLAT_ONLY: set[str] = set()
"""Model ids measured to reject ``verbose_json``, remembered for the process.

Asking for segment timestamps is the right first move — they are what makes a
subtitle track — but it is not a request every STT model accepts. Measured:
``openai/whisper-1`` and ``openai/whisper-large-v3`` answer it, while
``openai/gpt-4o-transcribe`` returns 400 and says to use ``json`` instead. Since
a model id here can be anything a caller names, the backend finds out by asking
and then retries flat rather than refusing a model that works fine.

The set exists so only the *first* chunk of a file pays that failed request;
without it a long video would pay one per chunk. Keyed by model id alone, which
is all the answer depends on.
"""

# OpenRouter's own wording for the refusal. Matching a message is a heuristic,
# as it is for the CUDA probe in local_backend — but the alternative is retrying
# every 400, including the ones that mean the audio or the key is wrong.
#
# Split into quoteless fragments on purpose: the error reaches us as the raw
# JSON body, so the format name in it arrives backslash-escaped and a pattern
# written with real quotes silently never matches.
_VERBOSE_UNSUPPORTED = ("does not support response_format", "verbose_json")

# OpenRouter names the container rather than sniffing it. The pipeline hands
# over FLAC in every case it transcodes; the rest are the formats a caller's
# own audio file can arrive in and be sent untouched.
_FORMATS = {
    ".flac": "flac",
    ".wav": "wav",
    ".mp3": "mp3",
    ".m4a": "m4a",
    ".aac": "aac",
    ".ogg": "ogg",
    ".oga": "ogg",
    ".webm": "webm",
    ".mp4": "m4a",
}


class OpenRouterTranscriber(Transcriber):
    name = "openrouter"

    def __init__(self, config: ASRConfig) -> None:
        super().__init__(config)
        self._client: OpenRouterClient | None = None

    @property
    def default_model(self) -> str:
        return DEFAULT_MODEL

    def is_available(self) -> tuple[bool, str]:
        if not self.config.openrouter_api_key:
            return False, "OPENROUTER_API_KEY is not set"
        return True, ""

    def _get_client(self) -> OpenRouterClient:
        if self._client is None:
            if not self.config.openrouter_api_key:
                raise TranscriptionError("OPENROUTER_API_KEY is not set")
            self._client = OpenRouterClient(
                self.config.openrouter_api_key, timeout=self.config.timeout
            )
        return self._client

    def _provider(self, prompt: str | None) -> dict | None:
        """Build the ``provider`` block: configured options plus the prompt."""
        options: dict = copy.deepcopy(self.config.provider_options)
        if prompt:
            for slug in PROMPT_PROVIDERS:
                # An explicit prompt in provider_options is the caller being
                # specific; don't overwrite it with the assembled one.
                options.setdefault(slug, {}).setdefault("prompt", prompt)
        return {"options": options} if options else None

    async def transcribe_file(
        self,
        audio_path: str,
        *,
        language: str | None = None,
        prompt: str | None = None,
        model: str | None = None,
    ) -> Transcript:
        client = self._get_client()
        name = self.model_for(model)
        audio_format = audio_format_for(audio_path)
        provider = self._provider(prompt)

        # Read once so a retry doesn't need to rewind a consumed file handle.
        payload = await asyncio.to_thread(read_bytes, audio_path)

        async def _send(verbose: bool) -> dict:
            try:
                return await client.transcribe(
                    payload,
                    model=name,
                    audio_format=audio_format,
                    language=language,
                    provider=provider,
                    verbose=verbose,
                )
            except Exception as exc:
                raise TranscriptionError(f"OpenRouter transcription failed: {exc}") from exc

        verbose = name not in _FLAT_ONLY
        try:
            response = await _send(verbose)
        except TranscriptionError as exc:
            message = str(exc)
            if not verbose or not all(part in message for part in _VERBOSE_UNSUPPORTED):
                raise
            # The model is real but serves flat text only. One cue for the
            # whole chunk is a poor subtitle track and far better than no
            # transcript: the caller chose this model, and the alternative is a
            # 400 about a request field they never set.
            #
            # Note this says nothing about whether the model exists. OpenRouter
            # reports whichever constraint it happens to check first, so a
            # nonexistent id can come back as this refusal, as "does not support
            # large audio inputs", or as the honest "does not exist" — the retry
            # is not a existence check and must not be read as one.
            _FLAT_ONLY.add(name)
            response = await _send(verbose=False)

        if not get_field(response, "duration"):
            response = await self._with_duration(response, audio_path)

        return to_transcript(response, audio_path, self.name, self.config.no_speech_threshold)

    async def _with_duration(self, response, audio_path: str):
        """Give a flat response a duration, so its one cue has an end time.

        ``response_format=json`` carries no ``duration`` and no segments, so the
        single fallback cue would otherwise run from 0.0 to 0.0 and render as an
        empty subtitle. Whisper's ``usage.seconds`` has the answer where it is
        reported; a token-priced model bills in tokens and does not, so the file
        itself is measured instead. Only the flat path pays for that probe.
        """
        if not isinstance(response, dict):
            return response

        seconds = (response.get("usage") or {}).get("seconds")
        if not seconds:
            try:
                seconds = (await asyncio.to_thread(probe, audio_path)).duration
            except VidaError:
                return response

        return {**response, "duration": float(seconds or 0.0)}

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def audio_format_for(audio_path: str) -> str:
    """Name the container for a file OpenRouter is about to be handed."""
    extension = os.path.splitext(audio_path)[1].lower()
    try:
        return _FORMATS[extension]
    except KeyError:
        raise TranscriptionError(
            f"{audio_path} is in a container OpenRouter transcription does not accept "
            f"({extension or 'no extension'}). Audio reaches this backend untouched only "
            "when ASRConfig.audio_filter is empty; leave the default filter on and the "
            "pipeline transcodes to FLAC on the way through."
        ) from None
