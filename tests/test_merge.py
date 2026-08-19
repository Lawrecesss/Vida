"""Stitching parallel chunk transcripts back onto one timeline."""

from vida.asr.pipeline import merge_chunk_transcripts
from vida.media.audio import AudioChunk
from vida.types import Segment, Transcript


def _chunk_result(index, start, end, spans):
    """A chunk plus its transcript, whose timestamps are chunk-relative."""
    return (
        AudioChunk(f"/tmp/chunk{index}.flac", start, end, index),
        Transcript(
            language="en",
            segments=[
                Segment(id=i, start=s, end=e, text=t) for i, (s, e, t) in enumerate(spans)
            ],
            duration=end - start,
        ),
    )


def test_timestamps_are_shifted_onto_the_global_timeline():
    merged = merge_chunk_transcripts(
        [
            _chunk_result(0, 0.0, 10.0, [(0.0, 3.0, "one"), (3.0, 6.0, "two")]),
            _chunk_result(1, 8.0, 18.0, [(4.0, 7.0, "three"), (7.0, 9.0, "four")]),
        ]
    )
    starts = [s.start for s in merged.segments]
    # Chunk 1 starts at 8s, so its 4.0s segment lands at 12.0s.
    assert 12.0 in starts
    assert 15.0 in starts


def test_segments_are_renumbered_sequentially():
    merged = merge_chunk_transcripts(
        [
            _chunk_result(0, 0.0, 10.0, [(0.0, 3.0, "a"), (3.0, 6.0, "b")]),
            _chunk_result(1, 8.0, 18.0, [(4.0, 7.0, "c")]),
        ]
    )
    assert [s.id for s in merged.segments] == [0, 1, 2]


def test_out_of_order_chunks_are_sorted():
    merged = merge_chunk_transcripts(
        [
            _chunk_result(1, 8.0, 18.0, [(4.0, 7.0, "second")]),
            _chunk_result(0, 0.0, 10.0, [(0.0, 3.0, "first")]),
        ]
    )
    assert [s.text for s in merged.segments] == ["first", "second"]


def test_duplicate_text_at_a_seam_is_dropped():
    # The overlap means chunk 1 re-hears what chunk 0 already covered at 8-9s.
    merged = merge_chunk_transcripts(
        [
            _chunk_result(0, 0.0, 10.0, [(0.0, 3.0, "intro"), (8.0, 9.0, "repeated line")]),
            _chunk_result(1, 8.0, 18.0, [(0.0, 1.0, "repeated line"), (2.0, 5.0, "new line")]),
        ]
    )
    assert [s.text for s in merged.segments] == ["intro", "repeated line", "new line"]


def test_segment_truncated_at_a_chunk_boundary_is_replaced():
    # Chunk 0's last segment runs right up to its 10s edge, so it was cut off.
    # Chunk 1 has the complete utterance and should win.
    merged = merge_chunk_transcripts(
        [
            _chunk_result(0, 0.0, 10.0, [(0.0, 3.0, "intro"), (8.5, 10.0, "half a sen")]),
            _chunk_result(1, 8.0, 18.0, [(0.5, 4.0, "half a sentence and the rest")]),
        ]
    )
    texts = [s.text for s in merged.segments]
    assert "half a sen" not in texts
    assert "half a sentence and the rest" in texts


def test_timeline_is_monotonic():
    merged = merge_chunk_transcripts(
        [
            _chunk_result(0, 0.0, 10.0, [(0.0, 4.0, "a"), (4.0, 9.0, "b")]),
            _chunk_result(1, 8.0, 18.0, [(1.5, 5.0, "c"), (5.0, 9.0, "d")]),
            _chunk_result(2, 16.0, 24.0, [(1.5, 4.0, "e")]),
        ]
    )
    starts = [s.start for s in merged.segments]
    assert starts == sorted(starts)


def test_language_is_the_majority_vote_across_chunks():
    results = [
        _chunk_result(0, 0.0, 10.0, [(0.0, 3.0, "hola")]),
        _chunk_result(1, 8.0, 18.0, [(1.0, 3.0, "adios")]),
        _chunk_result(2, 16.0, 24.0, [(1.0, 3.0, "que tal")]),
    ]
    results[0][1].language = "es"
    results[1][1].language = "es"
    results[2][1].language = "en"  # one bad detection shouldn't win
    assert merge_chunk_transcripts(results).language == "es"


def test_duration_reflects_the_last_segment():
    merged = merge_chunk_transcripts(
        [
            _chunk_result(0, 0.0, 10.0, [(0.0, 3.0, "a")]),
            _chunk_result(1, 8.0, 18.0, [(1.0, 7.5, "b")]),
        ]
    )
    assert merged.duration == 15.5


def test_empty_chunks_do_not_break_the_merge():
    merged = merge_chunk_transcripts(
        [
            _chunk_result(0, 0.0, 10.0, []),
            _chunk_result(1, 8.0, 18.0, [(1.0, 3.0, "only line")]),
        ]
    )
    assert [s.text for s in merged.segments] == ["only line"]
