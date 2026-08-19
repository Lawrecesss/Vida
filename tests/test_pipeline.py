"""End-to-end transcription against a real video with a stubbed ASR backend.

This exercises everything except the network call: audio extraction, chunking,
parallel dispatch, timeline stitching, and subtitle export.
"""

import os
import pathlib

import pytest

from vida.asr.base import Transcriber
from vida.client import Vida
from vida.config import ASRConfig, VidaConfig
from vida.errors import MediaError
from vida.media.video import probe
from vida.types import Segment, Transcript

VIDEO = os.path.join(os.path.dirname(__file__), "..", "vids", "test2.mp4")
pytestmark = pytest.mark.skipif(not os.path.exists(VIDEO), reason="sample video not present")


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


async def test_audio_input_skips_extraction(tmp_path):
    from vida.media.audio import extract_audio

    audio = await extract_audio(VIDEO, str(tmp_path / "a.flac"))
    vida, stub = _client(chunk_seconds=600)
    await vida.transcribe(audio)
    assert stub.seen == [audio]  # used the file directly, no re-extraction


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
