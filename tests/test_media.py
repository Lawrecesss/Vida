"""Media I/O against real files and a real ffmpeg."""

import os

import pytest
from _samples import sample_available, sample_path

from vida.errors import MediaError
from vida.media.audio import extract_audio, split_audio
from vida.media.frames import extract_frames
from vida.media.video import probe, segment_video

VIDEO = sample_path("test2.mp4")
pytestmark = pytest.mark.skipif(
    not sample_available(VIDEO),
    reason="sample video not fetched (run: git lfs pull)",
)


def test_probe_reads_real_metadata():
    media = probe(VIDEO)
    assert media.duration > 0
    assert media.size_mb > 0
    assert media.width and media.height
    assert media.has_audio is True


def test_probe_rejects_a_missing_file():
    with pytest.raises(MediaError, match="File not found"):
        probe("/nope/missing.mp4")


async def test_extract_audio_produces_a_much_smaller_file(tmp_path):
    out = await extract_audio(VIDEO, str(tmp_path / "audio.flac"))
    assert os.path.exists(out)
    # Stripping video is the point: the audio must be a fraction of the source.
    assert os.path.getsize(out) < os.path.getsize(VIDEO) / 2
    assert probe(out).duration == pytest.approx(probe(VIDEO).duration, abs=1.0)


async def test_short_audio_is_not_split(tmp_path):
    out = await extract_audio(VIDEO, str(tmp_path / "audio.flac"))
    duration = probe(out).duration
    chunks = await split_audio(out, duration, chunk_seconds=600, overlap=2)
    assert len(chunks) == 1
    assert chunks[0].path == out  # reuses the file rather than transcoding again


async def test_split_audio_covers_the_timeline_with_overlap(tmp_path):
    out = await extract_audio(VIDEO, str(tmp_path / "audio.flac"))
    duration = probe(out).duration

    chunks = await split_audio(
        out, duration, chunk_seconds=10, overlap=2, out_dir=str(tmp_path)
    )
    assert len(chunks) > 1
    assert chunks[0].start == 0.0
    assert chunks[-1].end == pytest.approx(duration, abs=0.5)

    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start < previous.end          # they overlap
        assert previous.end - current.start == pytest.approx(2.0, abs=0.01)
        assert os.path.exists(current.path)


async def test_segment_video_produces_clips_under_the_size_cap(tmp_path):
    duration = probe(VIDEO).duration
    segments = await segment_video(
        VIDEO, duration, max_mb=1.0, max_seconds=10, overlap=1, out_dir=str(tmp_path)
    )
    assert len(segments) > 1
    for segment in segments:
        assert os.path.exists(segment.path)
        assert os.path.getsize(segment.path) / (1024 * 1024) < 2.0
    assert segments[-1].end == pytest.approx(duration, abs=0.5)


async def test_extract_frames_returns_evenly_spaced_stills(tmp_path):
    frames = await extract_frames(VIDEO, str(tmp_path / "frames"), count=6)
    assert len(frames) == 6
    assert all(os.path.getsize(path) > 0 for path in frames)
