"""Video in, transcript out.

Two steps and nothing else: ffmpeg turns whatever container arrives into a small
mono audio track, and one OpenRouter request turns that track into text.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from pathlib import Path

import httpx
from pydantic import BaseModel

from vida.errors import VidaError

DEFAULT_MODEL = "openai/whisper-large-v3"
_URL = "https://openrouter.ai/api/v1/audio/transcriptions"

# 16 kHz mono is what Whisper resamples to anyway, so sending more only costs
# upload. At 32 kbps an hour is ~14 MB, which keeps a long video inside one
# request body; there is no chunking yet, so very long inputs are the limit.
_FFMPEG_AUDIO = ["-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", "-f", "mp3"]


class Segment(BaseModel):
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    text: str
    language: str | None = None
    duration: float | None = None
    segments: list[Segment] = []


async def transcribe(
    video_path: str | os.PathLike[str],
    *,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = 300.0,
) -> Transcript:
    """Transcribe the speech in a video (or audio) file."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise VidaError("OPENROUTER_API_KEY is not set.")
    path = Path(video_path)
    if not path.is_file():
        raise VidaError(f"No such file: {path}")

    audio = await _extract_audio(path)
    body = await _request(audio, model or os.environ.get("VIDA_MODEL") or DEFAULT_MODEL, key, timeout)
    return _parse(body)


async def _extract_audio(path: Path) -> bytes:
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "audio.mp3"
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(path), *_FFMPEG_AUDIO, str(out),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise VidaError("ffmpeg is not installed or not on PATH.") from exc
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise VidaError(f"ffmpeg could not read the audio: {stderr.decode(errors='replace')[-300:]}")
        if out.stat().st_size == 0:
            raise VidaError("The file has no audio track.")
        return out.read_bytes()


async def _request(audio: bytes, model: str, key: str, timeout: float) -> dict:
    # Base64 in a JSON body rather than multipart: OpenRouter caps the
    # multipart path at 25 MB and routes anything larger through this one.
    payload = {
        "model": model,
        "input_audio": {"data": base64.b64encode(audio).decode("ascii"), "format": "mp3"},
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment"],
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(_URL, json=payload, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        raise VidaError(f"Could not reach OpenRouter: {exc!r}") from exc
    if response.status_code >= 400:
        raise VidaError(f"OpenRouter rejected the request ({response.status_code}): {response.text[:300]}")
    body = response.json()
    if isinstance(body, dict) and body.get("error"):
        raise VidaError(f"OpenRouter error: {body['error']}")
    return body


def _parse(body: dict) -> Transcript:
    # OpenRouter documents segments/language/duration as provider-dependent, so
    # every read tolerates absence and the plain text is the only guarantee.
    segments = [
        Segment(start=float(s.get("start", 0)), end=float(s.get("end", 0)), text=str(s.get("text", "")).strip())
        for s in body.get("segments") or []
        if isinstance(s, dict)
    ]
    return Transcript(
        text=str(body.get("text", "")).strip(),
        language=body.get("language"),
        duration=body.get("duration"),
        segments=segments,
    )
