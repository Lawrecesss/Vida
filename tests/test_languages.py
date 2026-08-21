"""Turning what Whisper reports into what its API accepts.

Whisper answers with an English name and takes an ISO-639-1 code, so pinning a
detected language for the rest of a file depends entirely on this mapping.
"""

import pytest

from vida.asr.languages import LANGUAGE_NAMES, to_code


@pytest.mark.parametrize(
    "value,expected",
    [
        ("English", "en"),
        ("english", "en"),
        ("  Malay  ", "ms"),
        ("Japanese", "ja"),
        ("en", "en"),
        ("EN", "en"),
    ],
)
def test_names_and_codes_both_resolve(value, expected):
    assert to_code(value) == expected


def test_burmese_is_reported_by_a_name_the_table_does_not_use():
    # Whisper's own table calls it "myanmar"; the models say "Burmese".
    assert LANGUAGE_NAMES["my"] == "myanmar"
    assert to_code("Burmese") == "my"


@pytest.mark.parametrize("value", [None, "", "   ", "Klingon", "Simlish"])
def test_anything_unrecognised_means_do_not_pin(value):
    # None is the signal to let the backend detect; it must never be an error.
    assert to_code(value) is None


def test_every_name_round_trips_to_its_own_code():
    assert all(to_code(name) == code for code, name in LANGUAGE_NAMES.items())
