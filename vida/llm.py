"""A small async OpenRouter client.

The core SDK deliberately avoids a framework here: translation and analysis are
single-shot chat completions, and a direct HTTP call is both faster and one
less dependency than routing them through an agent framework.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any

import httpx

from vida.errors import ConfigurationError, VidaError

__all__ = ["OpenRouterClient", "strip_reasoning"]

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
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
    """Minimal chat-completions client with retry and backoff."""

    def __init__(
        self,
        api_key: str | None,
        *,
        timeout: float = 180.0,
        max_retries: int = 3,
        referer: str = "https://github.com/lhshein/VidA",
        title: str = "VidA SDK",
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

        client = self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await client.post(
                    _API_URL, json=payload, timeout=timeout or self.timeout
                )
                if response.status_code in (408, 429, 500, 502, 503, 504):
                    raise _RetryableError(f"HTTP {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
                return _extract_text(response.json())

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


def _extract_text(body: dict) -> str:
    if "error" in body and body["error"]:
        message = body["error"]
        if isinstance(message, dict):
            message = message.get("message", message)
        raise VidaError(f"OpenRouter error: {message}")

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
