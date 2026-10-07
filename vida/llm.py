"""A small async OpenRouter client.

The core SDK deliberately avoids a framework here: translation, analysis and
transcription are single HTTP calls against one provider, and going direct is
both faster and one less dependency than routing them through an agent
framework or a per-provider vendor SDK.

Every stage reaching OpenRouter shares this client, so the retry, backoff and
connection pooling are written once and the model id is just an argument.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
from typing import Any

import httpx

from vida.errors import ConfigurationError, VidaError

__all__ = ["OpenRouterClient", "strip_reasoning"]

_BASE_URL = "https://openrouter.ai/api/v1"
_CHAT_URL = f"{_BASE_URL}/chat/completions"
_TRANSCRIPTION_URL = f"{_BASE_URL}/audio/transcriptions"
_THINK_BLOCK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove ``<think>`` blocks that reasoning models leave in their output."""
    if not text:
        return ""
    cleaned = _THINK_BLOCK.sub("", text)
    # A truncated response can open a think block and never close it; drop the
    # dangling tail rather than returning half a chain of thought.
    if "<think>" in cleaned.lower() and "</think>" not in cleaned.lower():
        cleaned = re.split(r"<think>", cleaned, flags=re.IGNORECASE)[0]
    return cleaned.strip()


class OpenRouterClient:
    """Minimal OpenRouter client with retry and backoff."""

    def __init__(
        self,
        api_key: str | None,
        *,
        timeout: float = 180.0,
        max_retries: int = 3,
        referer: str = "https://github.com/Lawrecesss/Vida",
        title: str = "Vida SDK",
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "OPENROUTER_API_KEY is not set. Export it, put it in a .env file, "
                "or pass VidaConfig(openrouter_api_key=...)."
            )
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": referer,
            "X-Title": title,
        }
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers=self._headers,
                # Chunked audio and video fan out wide; allow the connections.
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            )
        return self._client

    async def complete(
        self,
        content: Any,
        *,
        model: str,
        temperature: float = 0.0,
        system: str | None = None,
        reasoning: bool | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        extra_body: dict | None = None,
        timeout: float | None = None,
    ) -> str:
        """Run one chat completion and return the assistant's text.

        ``content`` is either a string or a list of OpenAI-style content parts
        (so callers can inline images or video).
        """
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if reasoning is not None:
            payload["reasoning"] = {"enabled": reasoning}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        if extra_body:
            payload.update(extra_body)

        return _extract_text(await self._post(_CHAT_URL, payload, timeout))

    async def transcribe(
        self,
        audio: bytes,
        *,
        model: str,
        audio_format: str,
        language: str | None = None,
        temperature: float = 0.0,
        provider: dict | None = None,
        verbose: bool = True,
        timeout: float | None = None,
    ) -> dict:
        """Run one speech-to-text request and return the decoded JSON body.

        Base64 in a JSON body rather than a multipart upload: OpenRouter caps
        the OpenAI-compatible multipart path at 25 MB and routes anything
        larger through this one, so taking it always means the pipeline's
        chunk length — not the transport — decides what fits.

        ``verbose`` asks for ``verbose_json`` and segment timestamps, which is
        what subtitles need. Not every STT model serves it; see
        :mod:`vida.asr.openrouter_backend` for what happens when one doesn't.

        ``provider`` is passed through untouched. It is the only place
        provider-specific transcription options live (a vocabulary prompt among
        them), and OpenRouter keys them by provider slug, so an entry for a
        provider that did not serve the request is simply unused.
        """
        payload: dict[str, Any] = {
            "model": model,
            "input_audio": {
                "data": base64.b64encode(audio).decode("ascii"),
                "format": audio_format,
            },
            "response_format": "verbose_json" if verbose else "json",
            "temperature": temperature,
        }
        if verbose:
            payload["timestamp_granularities"] = ["segment"]
        if language:
            payload["language"] = language
        if provider:
            payload["provider"] = provider

        return await self._post(_TRANSCRIPTION_URL, payload, timeout)

    async def _post(self, url: str, payload: dict, timeout: float | None) -> dict:
        """POST a JSON payload, retrying the failures worth retrying."""
        client = self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await client.post(
                    url, json=payload, timeout=timeout or self.timeout
                )
                if response.status_code in (408, 429, 500, 502, 503, 504):
                    raise _RetryableError(f"HTTP {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
                body = response.json()
                _raise_for_error(body)
                return body

            except (_RetryableError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                # Exponential backoff with jitter, so a burst of parallel
                # chunks doesn't retry in lockstep and re-trigger the limit.
                await asyncio.sleep((2**attempt) + random.uniform(0, 1))

            except httpx.HTTPStatusError as exc:
                raise VidaError(
                    f"OpenRouter rejected the request ({exc.response.status_code}): "
                    f"{exc.response.text[:300]}"
                ) from exc

        raise VidaError(f"OpenRouter request failed after {self.max_retries} attempts: {last_error}")

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> OpenRouterClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()


class _RetryableError(Exception):
    """Internal marker for a response worth retrying."""


def _raise_for_error(body: dict) -> None:
    """Surface an error OpenRouter reported inside a 200 response."""
    if isinstance(body, dict) and body.get("error"):
        message = body["error"]
        if isinstance(message, dict):
            message = message.get("message", message)
        raise VidaError(f"OpenRouter error: {message}")


def _extract_text(body: dict) -> str:
    _raise_for_error(body)

    choices = body.get("choices") or []
    if not choices:
        raise VidaError(f"OpenRouter returned no choices: {json.dumps(body)[:300]}")

    message = choices[0].get("message") or {}
    content = message.get("content")

    # Some providers return content as a list of parts rather than a string.
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )

    return content or ""
