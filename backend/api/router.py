"""HTTP endpoints. All of the real work lives in the `vida` SDK."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from api.deps import MAX_UPLOAD_MB, UPLOAD_DIR, get_vida, resolve_upload, safe_upload_name
from vida import Analysis, Transcript, VideoInsight, available_backends
from vida.errors import VidaError

router = APIRouter()

_CHUNK = 1024 * 1024


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    video_path: str
    filename: str
    size_mb: float
    duration: float
    has_audio: bool


class TranscribeRequest(BaseModel):
    video_path: str
    language: str | None = Field(default=None, description="Source language hint, e.g. 'en'.")
    prompt: str | None = Field(default=None, description="Vocabulary hint for the ASR model.")


class TranslateRequest(TranscribeRequest):
    target_languages: list[str] = Field(min_length=1)


class AnalyzeRequest(BaseModel):
    video_path: str
    query: str | None = None


class ProcessRequest(BaseModel):
    video_path: str
    transcribe: bool = True
    analyze: bool = False
    translate_to: list[str] = Field(default_factory=list)
    query: str | None = None
    language: str | None = None


class SubtitleRequest(BaseModel):
    video_path: str
    language: str | None = None
    translate_to: str | None = Field(
        default=None, description="Omit to get subtitles in the source language."
    )
    format: Literal["srt", "vtt"] = "srt"


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=UploadResponse)
async def upload_video(file: UploadFile = File(...)) -> UploadResponse:
    """Accept a video upload and return the handle used by the other endpoints."""
    if not (file.content_type or "").startswith(("video/", "audio/")):
        raise HTTPException(status_code=400, detail="File must be a video or audio file")

    name = safe_upload_name(file.filename)
    dest = os.path.join(UPLOAD_DIR, name)
    limit = MAX_UPLOAD_MB * 1024 * 1024
    written = 0

    try:
        # Stream to disk: a whole video must never be buffered in memory, and
        # the disk writes go to a thread so a slow upload can't stall the loop.
        buffer = await asyncio.to_thread(open, dest, "wb")
        try:
            while chunk := await file.read(_CHUNK):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        status_code=413, detail=f"File exceeds the {MAX_UPLOAD_MB:.0f}MB limit"
                    )
                await asyncio.to_thread(buffer.write, chunk)
        finally:
            await asyncio.to_thread(buffer.close)
    except Exception:
        if os.path.exists(dest):
            os.remove(dest)
        raise

    try:
        media = get_vida().probe(dest)
    except VidaError as exc:
        os.remove(dest)
        raise HTTPException(status_code=400, detail=f"Unreadable media file: {exc}") from exc

    return UploadResponse(
        video_path=dest,
        filename=file.filename or name,
        size_mb=round(media.size_mb, 2),
        duration=round(media.duration, 2),
        has_audio=media.has_audio,
    )


@router.delete("/upload")
async def delete_upload(video_path: str) -> dict:
    """Remove a previously uploaded file."""
    os.remove(resolve_upload(video_path))
    return {"deleted": True}


# ---------------------------------------------------------------------------
# SDK operations
# ---------------------------------------------------------------------------

@router.post("/transcribe", response_model=Transcript)
async def transcribe(request: TranscribeRequest) -> Transcript:
    """Transcribe the speech in an uploaded file."""
    path = resolve_upload(request.video_path)
    try:
        return await get_vida().transcribe(
            path, language=request.language, prompt=request.prompt
        )
    except VidaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/translate", response_model=dict[str, Transcript])
async def translate(request: TranslateRequest) -> dict[str, Transcript]:
    """Transcribe, then translate into one or more languages at once."""
    path = resolve_upload(request.video_path)
    vida = get_vida()
    try:
        transcript = await vida.transcribe(
            path, language=request.language, prompt=request.prompt
        )
        return await vida.translate_all(transcript, request.target_languages)
    except VidaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/analyze", response_model=Analysis)
async def analyze(request: AnalyzeRequest) -> Analysis:
    """Analyze what the video visually shows."""
    path = resolve_upload(request.video_path)
    try:
        return await get_vida().analyze(path, query=request.query)
    except VidaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/process", response_model=VideoInsight)
async def process(request: ProcessRequest) -> VideoInsight:
    """Run transcription, translation, and analysis in one call."""
    path = resolve_upload(request.video_path)
    try:
        return await get_vida().process(
            path,
            transcribe=request.transcribe,
            translate_to=request.translate_to,
            analyze=request.analyze,
            query=request.query,
            language=request.language,
        )
    except VidaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/subtitles", response_class=PlainTextResponse)
async def subtitles(request: SubtitleRequest) -> PlainTextResponse:
    """Return a subtitle file body, translated if a target language is given."""
    path = resolve_upload(request.video_path)
    vida = get_vida()
    try:
        transcript = await vida.transcribe(path, language=request.language)
        if request.translate_to:
            transcript = await vida.translate(transcript, request.translate_to)
    except VidaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    body = transcript.to_vtt() if request.format == "vtt" else transcript.to_srt()
    media_type = "text/vtt" if request.format == "vtt" else "application/x-subrip"
    stem = os.path.splitext(os.path.basename(path))[0]
    return PlainTextResponse(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.{request.format}"'
        },
    )


# ---------------------------------------------------------------------------
# Streaming progress
# ---------------------------------------------------------------------------

@router.post("/process/stream")
async def process_stream(request: ProcessRequest) -> StreamingResponse:
    """Same as /process, but emits stage-by-stage progress as SSE.

    Long videos take a while; this lets the UI show what's happening instead of
    a spinner.
    """
    path = resolve_upload(request.video_path)
    vida = get_vida()

    async def events():
        def emit(event: str, **data) -> str:
            return f"data: {json.dumps({'event': event, **data})}\n\n"

        try:
            media = vida.probe(path)
            yield emit("media", duration=media.duration, size_mb=round(media.size_mb, 2))

            transcript = None
            if request.transcribe or request.translate_to:
                yield emit("status", stage="transcribing")
                transcript = await vida.transcribe(path, language=request.language)
                yield emit(
                    "transcript",
                    language=transcript.language,
                    segments=len(transcript.segments),
                    text=transcript.text,
                )

            for language in request.translate_to:
                yield emit("status", stage="translating", language=language)
                translated = await vida.translate(transcript, language)
                yield emit(
                    "translation",
                    language=language,
                    text=translated.text,
                    srt=translated.to_srt(),
                )

            if request.analyze:
                yield emit("status", stage="analyzing")
                analysis = await vida.analyze(path, query=request.query, transcript=transcript)
                yield emit("analysis", summary=analysis.summary)

            yield "data: [DONE]\n\n"

        except VidaError as exc:
            yield emit("error", detail=str(exc))
        except Exception as exc:  # noqa: BLE001 - the stream must report, not 500
            yield emit("error", detail=f"Unexpected error: {exc}")

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Agent (optional extra)
# ---------------------------------------------------------------------------

def _get_agent():
    from api.agent_state import get_agent

    return get_agent()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Ask a question in natural language; the agent picks the tools."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        return ChatResponse(response=await _get_agent().run(request.message))
    except VidaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Streaming variant of /chat."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    async def generate():
        try:
            agent = _get_agent()
            async for chunk in agent.stream(request.message):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:  # noqa: BLE001 - reported through the stream
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@router.get("/backends")
async def backends() -> dict:
    """Which ASR backends this deployment can actually use."""
    report = available_backends()
    return {
        "backends": [
            {"name": name, "ready": not problem, "reason": problem or None}
            for name, problem in report.items()
        ]
    }
