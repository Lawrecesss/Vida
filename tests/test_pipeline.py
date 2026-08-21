"""End-to-end transcription against a real video with a stubbed ASR backend.

This exercises everything except the network call: audio extraction, chunking,
parallel dispatch, timeline stitching, and subtitle export.
"""

import os
import pathlib

import pytest
from _samples import sample_available, sample_path

from vida.asr.base import Transcriber
from vida.client import Vida
from vida.config import ASRConfig, VidaConfig
from vida.errors import MediaError
from vida.media.video import probe
from vida.types import Segment, Transcript

VIDEO = sample_path("test2.mp4")
pytestmark = pytest.mark.skipif(
    not sample_available(VIDEO),
    reason="sample video not fetched (run: git lfs pull)",
)


class StubTranscriber(Transcriber):
    """Returns two segments per file, so chunk stitching is observable."""

    name = "stub"

    def __init__(self, config):
        super().__init__(config)
        self.seen: list[str] = []

    @property
    def default_model(self):
        return "stub-1"

    def is_available(self):
        return True, ""

    async def transcribe_file(self, audio_path, *, language=None, prompt=None):
        self.seen.append(audio_path)
        duration = probe(audio_path).duration
        index = len(self.seen)
        return Transcript(
            language="en",
            segments=[
                Segment(id=0, start=0.0, end=duration / 2, text=f"chunk {index} first half"),
                Segment(id=1, start=duration / 2, end=duration, text=f"chunk {index} second half"),
            ],
            duration=duration,
            backend=self.name,
        )


def _client(**asr_kwargs) -> tuple[Vida, StubTranscriber]:
    config = VidaConfig(asr=ASRConfig(**asr_kwargs))
    vida = Vida(config)
    stub = StubTranscriber(config.asr)
    vida._transcriber = stub
    return vida, stub


async def test_single_chunk_path():
    vida, stub = _client(chunk_seconds=600)
    transcript = await vida.transcribe(VIDEO)

    assert len(stub.seen) == 1                       # no needless splitting
    assert len(transcript.segments) == 2
    assert transcript.source == VIDEO
    assert transcript.backend == "stub"
    assert transcript.duration == pytest.approx(probe(VIDEO).duration, abs=1.0)


async def test_multi_chunk_path_stitches_one_timeline():
    vida, stub = _client(chunk_seconds=10, chunk_overlap=2)
    transcript = await vida.transcribe(VIDEO)

    assert len(stub.seen) > 1                        # it actually fanned out
    starts = [s.start for s in transcript.segments]
    assert starts == sorted(starts)                  # monotonic after merging
    assert [s.id for s in transcript.segments] == list(range(len(transcript.segments)))
    # The last segment must reach roughly the end of the media.
    assert transcript.segments[-1].end == pytest.approx(probe(VIDEO).duration, abs=1.5)


async def test_chunk_files_are_cleaned_up():
    vida, stub = _client(chunk_seconds=10, chunk_overlap=2)
    await vida.transcribe(VIDEO)
    # Every scratch chunk, and the temp work dir itself, must be gone.
    assert not any(os.path.exists(path) for path in stub.seen)


def test_source_video_is_never_deleted():
    assert os.path.exists(VIDEO)


async def test_transcript_exports_to_subtitles(tmp_path):
    vida, _ = _client(chunk_seconds=10, chunk_overlap=2)
    transcript = await vida.transcribe(VIDEO)

    out = transcript.save(str(tmp_path / "out.srt"))
    body = pathlib.Path(out).read_text(encoding="utf-8")
    assert body.startswith("1\n00:00:00,000 -->")
    assert body.count("-->") == len(transcript.segments)


async def test_audio_input_skips_extraction_when_nothing_would_be_done_to_it(tmp_path):
    from vida.media.audio import extract_audio

    audio = await extract_audio(VIDEO, str(tmp_path / "a.flac"))
    vida, stub = _client(chunk_seconds=600, audio_filter="")
    await vida.transcribe(audio)
    assert stub.seen == [audio]  # used the file directly, no re-extraction


async def test_audio_input_is_still_cleaned_when_a_filter_is_configured(tmp_path):
    # Skipping the transcode is an optimisation, not a promise: noisy audio is
    # noisy whichever container it arrived in, and the filter is why Whisper
    # hears the quiet parts at all.
    from vida.media.audio import extract_audio

    audio = await extract_audio(VIDEO, str(tmp_path / "a.flac"))
    vida, stub = _client(chunk_seconds=600, audio_filter="highpass=f=100")
    await vida.transcribe(audio)
    assert stub.seen != [audio]
    assert stub.seen[0].endswith(".flac")


async def test_missing_file_is_reported():
    vida, _ = _client()
    with pytest.raises(MediaError):
        await vida.transcribe("/nope/missing.mp4")


def test_sync_wrapper_refuses_inside_a_running_loop():
    import asyncio

    async def inner():
        vida, _ = _client()
        with pytest.raises(RuntimeError, match="running event loop"):
            vida.transcribe_sync(VIDEO)

    asyncio.run(inner())


class LanguageStub(StubTranscriber):
    """Records the language hint each call was given, and what it detects."""

    def __init__(self, config, detected="Malay", fail=False):
        super().__init__(config)
        self.detected = detected
        self.fail = fail
        self.hints: list[str | None] = []

    async def transcribe_file(self, audio_path, *, language=None, prompt=None):
        if self.fail and not self.hints:
            from vida.errors import TranscriptionError

            self.hints.append(language)
            raise TranscriptionError("detection blew up")
        self.hints.append(language)
        transcript = await super().transcribe_file(audio_path, language=language, prompt=prompt)
        transcript.language = self.detected
        return transcript


def _language_client(detected="Malay", fail=False, **asr_kwargs):
    config = VidaConfig(asr=ASRConfig(**asr_kwargs))
    vida = Vida(config)
    stub = LanguageStub(config.asr, detected=detected, fail=fail)
    vida._transcriber = stub
    return vida, stub


async def test_detected_language_is_pinned_for_every_chunk():
    # Whisper re-detects per 30s window and drifts; one detection up front,
    # applied to every chunk, is what stops half a file coming back in a
    # language nobody spoke.
    vida, stub = _language_client(detected="English", detect_seconds=5, chunk_seconds=10)
    await vida.transcribe(VIDEO)

    detection, *chunks = stub.hints
    assert detection is None                     # the probe itself auto-detects
    assert chunks and all(hint == "en" for hint in chunks)


async def test_a_caller_supplied_language_skips_detection():
    vida, stub = _language_client(detect_seconds=5, chunk_seconds=600)
    await vida.transcribe(VIDEO, language="fr")
    assert stub.hints == ["fr"]                  # no probe, no second opinion


async def test_audio_shorter_than_one_window_is_not_probed():
    # A file that fits in a single detection window has nothing to drift
    # between, so probing it would only ask the same question twice.
    vida, stub = _language_client(detect_seconds=600, chunk_seconds=600)
    await vida.transcribe(VIDEO)
    assert stub.hints == [None]


async def test_detection_can_be_turned_off():
    vida, stub = _language_client(detect_seconds=0, chunk_seconds=600)
    await vida.transcribe(VIDEO)
    assert stub.hints == [None]


async def test_an_unmappable_language_pins_nothing():
    vida, stub = _language_client(detected="Klingon", detect_seconds=5, chunk_seconds=600)
    await vida.transcribe(VIDEO)
    assert stub.hints == [None, None]            # probed, learned nothing, carried on


async def test_a_failed_probe_still_produces_a_transcript():
    vida, stub = _language_client(fail=True, detect_seconds=5, chunk_seconds=600)
    transcript = await vida.transcribe(VIDEO)
    assert transcript.segments                   # detection is an optimisation, not a gate
    assert stub.hints[1:] == [None]


async def test_probe_audio_is_cleaned_up(tmp_path):
    vida, stub = _language_client(detect_seconds=5, chunk_seconds=600)
    await vida.transcribe(VIDEO)
    assert not any(os.path.exists(path) for path in stub.seen)


async def test_a_language_name_is_accepted_where_a_code_is_meant():
    # "English" is what a person types and what Whisper reports back; "en" is
    # the only thing the API takes.
    vida, stub = _language_client(detect_seconds=5, chunk_seconds=600)
    await vida.transcribe(VIDEO, language="English")
    assert stub.hints == ["en"]


async def test_an_unknown_language_is_passed_through_untouched():
    vida, stub = _language_client(detect_seconds=5, chunk_seconds=600)
    await vida.transcribe(VIDEO, language="yue")
    assert stub.hints == ["yue"]
