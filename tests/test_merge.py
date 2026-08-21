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


def _lang_chunk(index, start, end, language, spans):
    """A chunk whose ASR request detected ``language`` for the whole of it."""
    return (
        AudioChunk(f"/tmp/chunk{index}.flac", start, end, index),
        Transcript(
            language=language,
            segments=[
                Segment(id=i, start=s, end=e, text=t) for i, (s, e, t) in enumerate(spans)
            ],
            duration=end - start,
        ),
    )


def test_each_chunks_language_lands_on_its_own_segments():
    """A bilingual recording keeps both languages, one per segment.

    Whisper decides a single language per request, so a chunk boundary is the
    only place the language can change. Losing that on the merge is what made
    a bilingual video report as monolingual.
    """
    merged = merge_chunk_transcripts(
        [
            _lang_chunk(0, 0.0, 60.0, "en", [(1.0, 3.0, "hello"), (3.0, 6.0, "there")]),
            _lang_chunk(1, 58.0, 118.0, "my", [(0.5, 3.0, "မင်္ဂလာပါ")]),
        ]
    )
    assert [s.language for s in merged.segments] == ["en", "en", "my"]
    assert merged.languages == ["en", "my"]
    assert merged.is_multilingual


def test_transcript_language_is_the_majority_by_speech_duration():
    """A near-silent chunk must not outvote one carrying most of the speech."""
    merged = merge_chunk_transcripts(
        [
            _lang_chunk(0, 0.0, 60.0, "my", [(0.0, 30.0, "long stretch of speech")]),
            _lang_chunk(1, 58.0, 118.0, "en", [(0.5, 1.0, "hi")]),
            _lang_chunk(2, 116.0, 176.0, "en", [(0.5, 1.0, "ok")]),
        ]
    )
    # Two English chunks against one Burmese, but Burmese carries 30s of the
    # 31s of speech — counting chunks would have picked the wrong one.
    assert merged.language == "my"
    assert merged.languages == ["my", "en"]


def test_monolingual_audio_still_reports_one_language():
    merged = merge_chunk_transcripts(
        [
            _lang_chunk(0, 0.0, 60.0, "en", [(1.0, 3.0, "one")]),
            _lang_chunk(1, 58.0, 118.0, "en", [(0.5, 2.0, "two")]),
        ]
    )
    assert merged.language == "en"
    assert merged.languages == ["en"]
    assert not merged.is_multilingual
