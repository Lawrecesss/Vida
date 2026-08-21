"""Filtering the phrases Whisper invents over silence.

The numbers here are the ones a real silent clip produced: no_speech_prob 0.861
with avg_logprob -0.887, which Whisper's own gate (which also demands
avg_logprob < -1.0) happily lets through as the word "You".
"""

import pytest

from vida.asr.groq_backend import _to_transcript
from vida.asr.silence import is_repetition_loop, is_silence

HALLUCINATED = {"no_speech_prob": 0.861, "avg_logprob": -0.887}
SPOKEN = {"no_speech_prob": 0.02, "avg_logprob": -0.15}


def test_silence_over_the_threshold_is_dropped():
    assert is_silence(0.861, 0.41)


def test_ordinary_speech_survives():
    assert not is_silence(0.02, 0.86)


def test_confident_speech_survives_a_high_no_speech_score():
    # Two signals, not one: the model doubting itself is what makes it junk.
    assert not is_silence(0.9, 0.95)


def test_a_backend_that_reports_nothing_keeps_its_segments():
    assert not is_silence(None, None)


def test_a_threshold_of_one_keeps_everything():
    assert not is_silence(0.99, 0.1, threshold=1.0)


def test_unparseable_probabilities_are_ignored():
    assert not is_silence("very likely", 0.1)


def test_hosted_transcripts_drop_hallucinated_segments():
    transcript = _to_transcript(
        {
            "language": "en",
            "duration": 30.0,
            "segments": [
                {"start": 0.0, "end": 2.0, "text": " Hello there.", **SPOKEN},
                {"start": 12.9, "end": 14.9, "text": " You", **HALLUCINATED},
            ],
        },
        "a.flac",
        "groq",
    )
    assert [s.text for s in transcript.segments] == ["Hello there."]


def test_a_silent_file_produces_an_empty_transcript():
    transcript = _to_transcript(
        {"duration": 30.0, "segments": [{"start": 12.9, "end": 14.9, "text": " You", **HALLUCINATED}]},
        "a.flac",
        "groq",
    )
    assert transcript.segments == []
    assert transcript.text.strip() == ""


def test_the_flat_text_fallback_does_not_resurrect_what_was_filtered():
    # The real API returns the joined text alongside the segments. Falling back
    # to it whenever the segment list came out empty handed the hallucination
    # straight back as one long cue: a silent clip transcribed as "Thank you."
    transcript = _to_transcript(
        {
            "duration": 30.0,
            "text": " Thank you.",
            "segments": [{"start": 0.0, "end": 30.0, "text": " Thank you.", **HALLUCINATED}],
        },
        "a.flac",
        "groq",
    )
    assert transcript.segments == []


def test_the_flat_text_fallback_still_covers_a_response_without_segments():
    transcript = _to_transcript(
        {"duration": 4.0, "text": " Hello there."}, "a.flac", "groq"
    )
    assert [s.text for s in transcript.segments] == ["Hello there."]


def test_the_threshold_is_honoured_end_to_end():
    response = {"segments": [{"start": 0, "end": 2, "text": " You", **HALLUCINATED}]}
    kept = _to_transcript(response, "a.flac", "groq", 1.0)
    assert [s.text for s in kept.segments] == ["You"]


@pytest.mark.parametrize("phrase", [" You", " Thank you.", " Thanks for watching!"])
def test_the_usual_suspects_all_go(phrase):
    transcript = _to_transcript(
        {"segments": [{"start": 0, "end": 2, "text": phrase, **HALLUCINATED}]}, "a.flac", "groq"
    )
    assert transcript.segments == []


@pytest.mark.parametrize(
    "text",
    [
        "Bam bam bam bam bam.",
        "Some, some, some, some.",
        "And then, then, then, then.",
        "Niang Niang Niang Niang",
    ],
)
def test_a_word_stuttered_on_a_loop_is_dropped(text):
    assert is_repetition_loop(text)


@pytest.mark.parametrize(
    "text",
    [
        "Fish! Fish!",                      # real, and common in excited speech
        "Oh my god",
        "yeah two, two, don't do",
        "two for Laura",
        "",
        "Bam",
    ],
)
def test_real_speech_is_not_mistaken_for_a_loop(text):
    assert not is_repetition_loop(text)


def test_a_loop_is_dropped_even_when_the_model_sounds_sure_of_it():
    # The no-speech signals say nothing useful here: the model is confidently
    # repeating itself, so this needs its own test rather than a threshold.
    transcript = _to_transcript(
        {
            "duration": 10.0,
            "segments": [
                {"start": 0.0, "end": 2.0, "text": " Hello there.", **SPOKEN},
                {"start": 2.0, "end": 5.0, "text": " Bam bam bam bam bam.", **SPOKEN},
            ],
        },
        "a.flac",
        "groq",
    )
    assert [s.text for s in transcript.segments] == ["Hello there."]
