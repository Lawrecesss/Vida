"""Media I/O against real files and a real ffmpeg."""

import os

import pytest
from _samples import sample_available, sample_path

from vida.config import DEFAULT_AUDIO_FILTER
from vida.errors import MediaError
from vida.media.audio import (
    DIALOGUE_FILTER_CENTER_51,
    DIALOGUE_FILTER_MIDSIDE_STEREO,
    _best_silence_point,
    _detect_silences,
    _filter_graph,
    _snap_boundary,
    extract_audio,
    split_audio,
)
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


# ---------------------------------------------------------------------------
# Dialogue isolation
#
# These assert on the filter graph rather than on the audio, because what the
# stage is worth depends on the source mix — and what must not change is the
# *order*, which is checkable without a 5.1 fixture.
# ---------------------------------------------------------------------------

def test_the_default_path_graph_is_unchanged():
    # The one guarantee dialogue isolation had to keep: with no dialogue filter
    # configured, the graph is exactly what it was before this existed.
    assert _filter_graph(DEFAULT_AUDIO_FILTER, None, 16000) == (
        f"aformat=channel_layouts=mono,aresample=16000,{DEFAULT_AUDIO_FILTER}"
    )


def test_no_filters_at_all_is_no_graph():
    assert _filter_graph(None, None, 16000) == ""
    assert _filter_graph("", "", 16000) == ""


def test_dialogue_isolation_runs_before_the_downmix():
    # It reads the source channel layout, which the downmix destroys.
    graph = _filter_graph(DEFAULT_AUDIO_FILTER, DIALOGUE_FILTER_CENTER_51, 16000)
    assert graph.index(DIALOGUE_FILTER_CENTER_51) < graph.index("aformat=")


def test_denoise_runs_after_the_downmix():
    # It is calibrated against 16 kHz mono; running it earlier changes what it
    # was measured to do.
    graph = _filter_graph(DEFAULT_AUDIO_FILTER, DIALOGUE_FILTER_CENTER_51, 16000)
    assert graph.index("aresample=16000") < graph.index(DEFAULT_AUDIO_FILTER)


def test_dialogue_isolation_alone_still_downmixes():
    graph = _filter_graph("", DIALOGUE_FILTER_CENTER_51, 16000)
    assert graph == f"{DIALOGUE_FILTER_CENTER_51},aformat=channel_layouts=mono,aresample=16000"


async def test_a_stereo_dialogue_filter_survives_a_real_extraction(tmp_path):
    # The mid/side preset is the one that works on any source, so it is the one
    # that can be checked end to end against the sample media.
    out = await extract_audio(
        VIDEO,
        str(tmp_path / "dialogue.flac"),
        audio_filter="",
        dialogue_filter=DIALOGUE_FILTER_MIDSIDE_STEREO,
    )
    assert os.path.exists(out)
    assert probe(out).duration == pytest.approx(probe(VIDEO).duration, abs=1.0)


# ---------------------------------------------------------------------------
# Silence-aware chunk boundaries
# ---------------------------------------------------------------------------

def test_the_nearest_silence_is_chosen_by_its_midpoint():
    # Midpoint, not edge: cutting where a gap begins clips the tail of the word
    # before it, and cutting where it ends clips the head of the next one.
    spans = [(4.0, 6.0), (20.0, 21.0)]
    assert _best_silence_point(spans, target=10.0) == 5.0
    assert _best_silence_point(spans, target=19.0) == 20.5


def test_no_silence_means_no_opinion():
    assert _best_silence_point([], target=10.0) is None


async def test_a_boundary_with_no_silence_nearby_does_not_move(monkeypatch):
    async def _none(*args, **kwargs):
        return []

    monkeypatch.setattr("vida.media.audio._detect_silences", _none)
    snapped = await _snap_boundary(
        "unused.flac", 100.0, search_seconds=3.0, total_duration=200.0
    )
    assert snapped == 100.0


async def test_a_failed_detection_leaves_the_boundary_alone():
    # Best effort throughout: losing the optimisation must never lose the split.
    # A path ffmpeg cannot open is the cheapest real failure to provoke, and it
    # must come back as "no silence found" rather than as an exception.
    snapped = await _snap_boundary(
        "/nonexistent/audio.flac", 100.0, search_seconds=3.0, total_duration=200.0
    )
    assert snapped == 100.0


async def test_detection_failure_is_reported_as_no_silence():
    assert await _detect_silences("/nonexistent/audio.flac", 0.0, 10.0) == []


async def test_a_snap_never_moves_further_than_the_search_window(monkeypatch):
    async def _far_away(*args, **kwargs):
        return [(500.0, 600.0)]        # a silence well outside the window

    monkeypatch.setattr("vida.media.audio._detect_silences", _far_away)
    snapped = await _snap_boundary(
        "unused.flac", 100.0, search_seconds=3.0, total_duration=1000.0
    )
    assert 97.0 <= snapped <= 103.0


async def test_searching_zero_seconds_is_a_no_op():
    assert await _snap_boundary(
        "unused.flac", 100.0, search_seconds=0.0, total_duration=200.0
    ) == 100.0


async def test_silence_aware_chunks_still_honour_the_overlap_contract(tmp_path, monkeypatch):
    # The invariant the anchored search exists to protect. Boundaries are pushed
    # around by a stub so the assertion does not depend on where the sample clip
    # happens to be quiet.
    moved = iter([7.5, 13.25])

    async def _snap(audio_path, target, **kwargs):
        return next(moved, target)

    monkeypatch.setattr("vida.media.audio._snap_boundary", _snap)

    out = await extract_audio(VIDEO, str(tmp_path / "audio.flac"))
    duration = probe(out).duration
    chunks = await split_audio(
        out,
        duration,
        chunk_seconds=10,
        overlap=2,
        out_dir=str(tmp_path),
        silence_aware=True,
    )

    assert [chunk.end for chunk in chunks][:2] == [7.5, 13.25]  # the snaps took
    for previous, current in zip(chunks, chunks[1:], strict=False):
        # Measured from where the previous boundary actually landed, so a snap
        # cannot make the overlap drift.
        assert previous.end - current.start == pytest.approx(2.0, abs=0.01)
    assert chunks[0].start == 0.0
    assert chunks[-1].end == pytest.approx(duration, abs=0.5)


async def test_silence_aware_chunking_covers_the_whole_timeline(tmp_path):
    # Against real audio and a real silencedetect pass, with no stubbing.
    out = await extract_audio(VIDEO, str(tmp_path / "audio.flac"))
    duration = probe(out).duration
    chunks = await split_audio(
        out,
        duration,
        chunk_seconds=10,
        overlap=2,
        out_dir=str(tmp_path),
        silence_aware=True,
        search_seconds=1.5,
    )

    assert len(chunks) > 1
    assert chunks[0].start == 0.0
    assert chunks[-1].end == pytest.approx(duration, abs=0.5)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start < previous.end             # no gap in coverage
        assert current.end > current.start              # no empty chunk
        assert os.path.exists(current.path)


async def test_the_default_path_is_untouched_by_the_new_argument(tmp_path):
    # split_audio's old behaviour must be exactly reproducible, since that is
    # what every existing measurement was taken against.
    out = await extract_audio(VIDEO, str(tmp_path / "audio.flac"))
    duration = probe(out).duration
    chunks = await split_audio(
        out, duration, chunk_seconds=10, overlap=2, out_dir=str(tmp_path)
    )
    for index, chunk in enumerate(chunks):
        assert chunk.start == pytest.approx(index * 8.0, abs=0.001)
