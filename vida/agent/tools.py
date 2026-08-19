"""LangChain tools wrapping the SDK, for the optional agent layer."""

from __future__ import annotations

import json

from vida.client import Vida
from vida.errors import VidaError

__all__ = ["build_tools"]

_MAX_TRANSCRIPT_CHARS = 12_000
"""Transcripts are fed back into a chat model, so cap what a tool returns."""


def build_tools(vida: Vida | None = None) -> list:
    """Build the tool set an agent can call.

    Args:
        vida: An existing client to share connections with. One is created if
            omitted.

    Returns:
        A list of LangChain ``StructuredTool`` objects.
    """
    try:
        from langchain_core.tools import tool
    except ImportError as exc:  # pragma: no cover - optional extra
        from vida.errors import MissingDependencyError

        raise MissingDependencyError("langchain-core", "agent") from exc

    client = vida or Vida()

    @tool
    async def analyze_video(video_path: str, user_query: str | None = None) -> str:
        """Describe what is visually shown in a video.

        Use this when the user asks what happens on screen, what a video shows,
        or about events, scenes, objects, or people visible in it.

        Args:
            video_path: Path to the video file.
            user_query: An optional question to focus the analysis on.

        Returns:
            A summary of the video's visual content.
        """
        try:
            analysis = await client.analyze(video_path, query=user_query)
        except VidaError as exc:
            return f"Analysis failed: {exc}"
        return analysis.summary

    @tool
    async def transcribe_video(video_path: str, language: str | None = None) -> str:
        """Transcribe the speech in a video or audio file.

        Use this when the user asks what is *said* in a video, wants the
        transcript, or wants subtitles.

        Args:
            video_path: Path to the video or audio file.
            language: Optional ISO-639-1 source language hint, e.g. 'en'.

        Returns:
            The transcript text, with detected language and duration.
        """
        try:
            transcript = await client.transcribe(video_path, language=language)
        except VidaError as exc:
            return f"Transcription failed: {exc}"

        text = transcript.text
        truncated = len(text) > _MAX_TRANSCRIPT_CHARS
        if truncated:
            text = text[:_MAX_TRANSCRIPT_CHARS] + "\n...[transcript truncated]"

        return (
            f"Language: {transcript.language or 'unknown'}\n"
            f"Duration: {transcript.duration:.0f}s\n"
            f"Segments: {len(transcript.segments)}\n\n{text}"
        )

    @tool
    async def translate_video(
        video_path: str, target_language: str, output_path: str | None = None
    ) -> str:
        """Transcribe a video and translate it into another language.

        Use this when the user wants a video's speech in a different language,
        or wants translated subtitles.

        Args:
            video_path: Path to the video file.
            target_language: The language to translate into, e.g. 'Spanish'.
            output_path: If given, an .srt or .vtt file is written there.

        Returns:
            The translated text, and the subtitle path when one was written.
        """
        try:
            transcript = await client.transcribe(video_path)
            translated = await client.translate(transcript, target_language)
        except VidaError as exc:
            return f"Translation failed: {exc}"

        note = ""
        if output_path:
            translated.save(output_path)
            note = f"\n\nSubtitles written to {output_path}"

        text = translated.text
        if len(text) > _MAX_TRANSCRIPT_CHARS:
            text = text[:_MAX_TRANSCRIPT_CHARS] + "\n...[truncated]"

        return f"Translated to {target_language}:\n\n{text}{note}"

    @tool
    def video_info(video_path: str) -> str:
        """Get a video's duration, size, resolution, and whether it has audio.

        Use this before deciding how to process a file, or when the user asks
        about a video's properties.

        Args:
            video_path: Path to the video file.

        Returns:
            A JSON object describing the media.
        """
        try:
            return json.dumps(client.probe(video_path).model_dump(mode="json"), indent=2)
        except VidaError as exc:
            return f"Could not read the file: {exc}"

    return [analyze_video, transcribe_video, translate_video, video_info]
