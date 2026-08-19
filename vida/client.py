"""The SDK's front door: :class:`Vida`."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import tempfile
import time
from collections.abc import Iterable
from typing import Literal, overload

from vida.analyze.core import analyze_video
from vida.asr import Transcriber, get_transcriber
from vida.asr.pipeline import extract_audio_for, transcribe_audio_file
from vida.config import ASRBackend, VidaConfig
from vida.errors import MediaError
from vida.llm import OpenRouterClient
from vida.media.video import probe
from vida.translate.core import translate_text, translate_transcript
from vida.types import Analysis, MediaInfo, Transcript, VideoInsight

__all__ = ["Vida"]

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}


class Vida:
    """Analyze, transcribe, and translate video.

    Every method is async. Wrap a whole workflow in ``async with`` so the
    underlying HTTP connections are reused across calls and closed at the end::

        async with Vida() as vida:
            transcript = await vida.transcribe("talk.mp4")
            spanish = await vida.translate(transcript, "Spanish")
            spanish.save("talk.es.srt")

    For synchronous code, every method has a ``*_sync`` twin::

        vida = Vida()
        transcript = vida.transcribe_sync("talk.mp4")
    """

    def __init__(
        self,
        config: VidaConfig | None = None,
        *,
        asr_backend: ASRBackend | None = None,
        asr_model: str | None = None,
        openrouter_api_key: str | None = None,
        translation_model: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        self.config = config or VidaConfig()

        # Constructor arguments are a convenience layer over the config object;
        # only override what the caller actually passed.
        if asr_backend is not None:
            self.config.asr.backend = asr_backend
        if asr_model is not None:
            self.config.asr.model = asr_model
        if openrouter_api_key is not None:
            self.config.openrouter_api_key = openrouter_api_key
        if translation_model is not None:
            self.config.translation.model = translation_model
        if work_dir is not None:
            self.config.work_dir = work_dir

        self._transcriber: Transcriber | None = None
        self._llm: OpenRouterClient | None = None

    # ------------------------------------------------------------------
    # Lazily built collaborators
    # ------------------------------------------------------------------

    @property
    def transcriber(self) -> Transcriber:
        """The active ASR backend, resolved on first use.

        Resolution is deferred so that constructing ``Vida()`` never fails for
        someone who only wants translation.
        """
        if self._transcriber is None:
            self._transcriber = get_transcriber(self.config.asr)
        return self._transcriber

    @property
    def llm(self) -> OpenRouterClient:
        """The OpenRouter client used for translation and analysis."""
        if self._llm is None:
            self._llm = OpenRouterClient(
                self.config.openrouter_api_key,
                timeout=self.config.translation.timeout,
                max_retries=self.config.translation.retries,
            )
        return self._llm

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def probe(self, source: str) -> MediaInfo:
        """Read duration, size, dimensions, and audio presence off a file."""
        return probe(source)

    async def transcribe(
        self,
        source: str,
        *,
        language: str | None = None,
        prompt: str | None = None,
    ) -> Transcript:
        """Transcribe the speech in a video or audio file.

        Args:
            source: Path to a video or audio file.
            language: ISO-639-1 hint such as ``"en"``. Omit to auto-detect.
            prompt: Optional context (names, acronyms, jargon) to bias decoding.

        Returns:
            A timestamped :class:`~vida.types.Transcript`. Call
            :meth:`~vida.types.Transcript.to_srt` on it for subtitles.
        """
        media = probe(source)
        with self._work_dir() as work_dir:
            audio_path = await self._audio_for(media, work_dir)
            return await transcribe_audio_file(
                self.transcriber,
                audio_path,
                media.duration,
                self.config.asr,
                language=language,
                prompt=prompt,
                work_dir=work_dir,
                source=source,
            )

    @overload
    async def translate(self, content: Transcript, target_language: str) -> Transcript: ...

    @overload
    async def translate(self, content: str, target_language: str) -> str: ...

    async def translate(
        self, content: Transcript | str, target_language: str
    ) -> Transcript | str:
        """Translate a transcript or a block of text.

        A transcript comes back as a transcript, with every timestamp preserved,
        so it can be exported as subtitles directly. Text comes back as text.

        Args:
            content: A :class:`~vida.types.Transcript` or plain string.
            target_language: Language name or code, e.g. ``"Japanese"`` or ``"ja"``.
        """
        if isinstance(content, Transcript):
            return await translate_transcript(
                content, target_language, client=self.llm, config=self.config.translation
            )
        return await translate_text(
            content, target_language, client=self.llm, config=self.config.translation
        )

    async def translate_all(
        self, transcript: Transcript, target_languages: Iterable[str]
    ) -> dict[str, Transcript]:
        """Translate one transcript into several languages at once.

        The languages run concurrently, so N languages cost roughly the time of
        the slowest one rather than the sum.
        """
        languages = list(target_languages)
        if not languages:
            return {}
        results = await asyncio.gather(
            *(self.translate(transcript, language) for language in languages)
        )
        return dict(zip(languages, results, strict=True))

    async def analyze(
        self,
        source: str,
        *,
        query: str | None = None,
        transcript: Transcript | None = None,
    ) -> Analysis:
        """Analyze what a video *shows*, as opposed to what is said in it.

        Args:
            source: Path to the video file.
            query: An optional question to focus the analysis on.
            transcript: Supplying one grounds the visual descriptions in what is
                actually being said, which measurably improves them.
        """
        media = probe(source)
        with self._work_dir() as work_dir:
            return await analyze_video(
                media,
                client=self.llm,
                config=self.config.analysis,
                user_query=query,
                transcript=transcript,
                work_dir=work_dir,
            )

    async def process(
        self,
        source: str,
        *,
        transcribe: bool = True,
        translate_to: Iterable[str] | None = None,
        analyze: bool = False,
        query: str | None = None,
        language: str | None = None,
        prompt: str | None = None,
    ) -> VideoInsight:
        """Run the whole pipeline over one video in a single call.

        Transcription and visual analysis run concurrently when both are
        requested, since neither blocks the other.

        Args:
            source: Path to the video file.
            transcribe: Produce a timestamped transcript.
            translate_to: Language codes or names to translate the transcript into.
            analyze: Also analyze the visual content.
            query: Question to focus the analysis on.
            language: Source-language hint for ASR.
            prompt: Vocabulary hint for ASR.

        Returns:
            A :class:`~vida.types.VideoInsight` holding everything produced,
            plus per-stage wall-clock timings.
        """
        media = probe(source)
        targets = list(translate_to or [])
        timings: dict[str, float] = {}

        # Translation needs the transcript, so ask for one if the caller only
        # requested translations.
        need_transcript = transcribe or bool(targets)

        with self._work_dir() as work_dir:
            transcript: Transcript | None = None

            async def _transcribe_stage() -> Transcript | None:
                if not need_transcript:
                    return None
                started = time.perf_counter()
                audio_path = await self._audio_for(media, work_dir)
                result = await transcribe_audio_file(
                    self.transcriber,
                    audio_path,
                    media.duration,
                    self.config.asr,
                    language=language,
                    prompt=prompt,
                    work_dir=work_dir,
                    source=source,
                )
                timings["transcribe"] = time.perf_counter() - started
                return result

            async def _analyze_stage() -> Analysis | None:
                if not analyze:
                    return None
                started = time.perf_counter()
                # Deliberately not waiting on the transcript here: running both
                # stages concurrently is the whole point, and the analysis is
                # still coherent without transcript grounding.
                result = await analyze_video(
                    media,
                    client=self.llm,
                    config=self.config.analysis,
                    user_query=query,
                    transcript=None,
                    work_dir=work_dir,
                    )
                timings["analyze"] = time.perf_counter() - started
                return result

            transcript, analysis = await asyncio.gather(
                _transcribe_stage(), _analyze_stage()
            )

            translations: dict[str, Transcript] = {}
            if targets and transcript is not None:
                started = time.perf_counter()
                translations = await self.translate_all(transcript, targets)
                timings["translate"] = time.perf_counter() - started

        return VideoInsight(
            media=media,
            transcript=transcript if transcribe else None,
            translations=translations,
            analysis=analysis,
            timings=timings,
        )

    async def subtitles(
        self,
        source: str,
        *,
        languages: Iterable[str] | None = None,
        out_dir: str | None = None,
        fmt: Literal["srt", "vtt"] = "srt",
        language: str | None = None,
    ) -> dict[str, str]:
        """Transcribe, translate, and write subtitle files in one call.

        Args:
            source: Path to the video.
            languages: Target languages to translate into. The original is
                always written too.
            out_dir: Where to write. Defaults to the video's own directory.
            fmt: ``"srt"`` or ``"vtt"``.
            language: Source-language hint for ASR.

        Returns:
            A mapping of language code to the subtitle file written.
        """
        insight = await self.process(
            source, transcribe=True, translate_to=languages, language=language
        )
        out_dir = out_dir or os.path.dirname(os.path.abspath(source))
        stem = os.path.splitext(os.path.basename(source))[0]

        written: dict[str, str] = {}
        if insight.transcript is not None:
            code = insight.transcript.language or "original"
            path = os.path.join(out_dir, f"{stem}.{code}.{fmt}")
            written[code] = insight.transcript.save(path, fmt)

        for code, translated in insight.translations.items():
            path = os.path.join(out_dir, f"{stem}.{_slug(code)}.{fmt}")
            written[code] = translated.save(path, fmt)

        return written

    # ------------------------------------------------------------------
    # Synchronous twins
    # ------------------------------------------------------------------

    def transcribe_sync(self, source: str, **kwargs) -> Transcript:
        """Blocking :meth:`transcribe`."""
        return _run(self.transcribe(source, **kwargs), self)

    def translate_sync(self, content: Transcript | str, target_language: str):
        """Blocking :meth:`translate`."""
        return _run(self.translate(content, target_language), self)

    def analyze_sync(self, source: str, **kwargs) -> Analysis:
        """Blocking :meth:`analyze`."""
        return _run(self.analyze(source, **kwargs), self)

    def process_sync(self, source: str, **kwargs) -> VideoInsight:
        """Blocking :meth:`process`."""
        return _run(self.process(source, **kwargs), self)

    def subtitles_sync(self, source: str, **kwargs) -> dict[str, str]:
        """Blocking :meth:`subtitles`."""
        return _run(self.subtitles(source, **kwargs), self)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the HTTP clients this instance opened."""
        if self._llm is not None:
            await self._llm.aclose()
            self._llm = None
        if self._transcriber is not None:
            await self._transcriber.aclose()
            self._transcriber = None

    async def __aenter__(self) -> Vida:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _audio_for(self, media: MediaInfo, work_dir: str) -> str:
        """Path to transcribable audio for ``media``, extracting it if needed."""
        extension = os.path.splitext(media.path)[1].lower()
        if extension in _AUDIO_EXTENSIONS:
            return media.path
        if not media.has_audio:
            raise MediaError(
                f"{media.path} has no audio track, so there is nothing to transcribe."
            )
        return await extract_audio_for(media.path, work_dir, media.has_audio)

    @contextlib.contextmanager
    def _work_dir(self):
        """A scratch directory, removed on exit unless the user configured one."""
        if self.config.work_dir:
            os.makedirs(self.config.work_dir, exist_ok=True)
            path = tempfile.mkdtemp(prefix="vida_", dir=self.config.work_dir)
        else:
            path = tempfile.mkdtemp(prefix="vida_")
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)


def _slug(language: str) -> str:
    """Turn a language name into something safe for a filename."""
    return "".join(char if char.isalnum() else "-" for char in language.strip().lower()).strip("-")


def _run(coro, client: Vida):
    """Run a coroutine from sync code, closing the client's connections after.

    The clients are bound to the event loop that created them, so a fresh
    ``asyncio.run`` per call must also tear them down — otherwise the next call
    inherits sockets attached to a dead loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        # The coroutine was already built by the caller's expression; close it
        # so it doesn't surface as a "never awaited" warning.
        coro.close()
        raise RuntimeError(
            "The *_sync methods cannot be called from inside a running event loop. "
            "Await the async method instead."
        )

    async def _wrapped():
        try:
            return await coro
        finally:
            await client.aclose()

    return asyncio.run(_wrapped())
