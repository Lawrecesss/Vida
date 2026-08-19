"""Subtitle rendering."""

from vida.export.subtitles import format_timestamp, to_srt, to_vtt
from vida.types import Segment, Transcript


def _transcript(*spans) -> Transcript:
    return Transcript(
        language="en",
        segments=[
            Segment(id=i, start=start, end=end, text=text)
            for i, (start, end, text) in enumerate(spans)
        ],
        duration=spans[-1][1] if spans else 0.0,
    )


def test_format_timestamp_srt_and_vtt():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(1.5) == "00:00:01,500"
    assert format_timestamp(3661.25) == "01:01:01,250"
    assert format_timestamp(3661.25, separator=".") == "01:01:01.250"


def test_format_timestamp_clamps_negative():
    assert format_timestamp(-5) == "00:00:00,000"


def test_srt_structure():
    srt = to_srt(_transcript((0.0, 2.0, "Hello there"), (2.0, 4.5, "General Kenobi")))
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,000\nHello there")
    assert "2\n00:00:02,000 --> 00:00:04,500\nGeneral Kenobi" in srt


def test_vtt_has_header_and_dot_separator():
    vtt = to_vtt(_transcript((0.0, 2.0, "Hi")))
    assert vtt.startswith("WEBVTT")
    assert "Language: en" in vtt
    assert "00:00:00.000 --> 00:00:02.000" in vtt


def test_empty_segments_are_skipped():
    srt = to_srt(_transcript((0.0, 1.0, "  "), (1.0, 2.0, "real")))
    assert srt.count("-->") == 1
    assert "real" in srt


def test_zero_length_cue_gets_a_readable_floor():
    srt = to_srt(_transcript((5.0, 5.0, "blink")))
    assert "00:00:05,000 --> 00:00:05,400" in srt


def test_overlapping_cues_are_trimmed():
    srt = to_srt(_transcript((0.0, 5.0, "first"), (2.0, 6.0, "second")))
    # The first cue must end no later than the second one starts.
    assert "00:00:00,000 --> 00:00:02,000" in srt


def test_long_lines_wrap_without_losing_words():
    text = "This is a considerably longer caption that will not fit on one line at all"
    srt = to_srt(_transcript((0.0, 4.0, text)))
    body = srt.split("\n", 2)[2].strip()
    assert "\n" in body
    assert " ".join(body.split()) == text


def test_save_infers_format_from_extension(tmp_path):
    transcript = _transcript((0.0, 1.0, "hola"))

    vtt = transcript.save(str(tmp_path / "out.vtt"))
    assert (tmp_path / "out.vtt").read_text().startswith("WEBVTT")

    transcript.save(str(tmp_path / "out.txt"))
    assert (tmp_path / "out.txt").read_text().strip() == "hola"

    transcript.save(str(tmp_path / "out.json"))
    assert '"segments"' in (tmp_path / "out.json").read_text()
    assert vtt.endswith("out.vtt")


def test_transcript_text_joins_segments():
    assert _transcript((0.0, 1.0, "one"), (1.0, 2.0, "two")).text == "one two"
