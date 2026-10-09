"""Noise measurement and the filter chain it builds.

The parsing and the band boundaries are checked against constructed input,
because what has to hold is a decision rule rather than a number from one
recording. One end-to-end case runs a real ffmpeg over the sample media to
confirm the graph this produces is something ffmpeg actually accepts.
"""

import pytest
from _samples import sample_available, sample_path

from vida.config import ASRConfig, VidaConfig
from vida.media.audio import extract_audio
from vida.media.ffmpeg import arun, ffmpeg_path
from vida.media.noise import (
    CLEAN_SNR_DB,
    NOISY_SNR_DB,
    NoiseProfile,
    _parse_windows,
    _percentile,
    adaptive_filter,
    measure_noise,
)

VIDEO = sample_path("test2.mp4")


def _profile(floor: float, speech: float, **kwargs) -> NoiseProfile:
    return NoiseProfile(
        noise_floor_db=floor,
        speech_level_db=speech,
        windows=kwargs.get("windows", 60),
        silent_windows=kwargs.get("silent_windows", 0),
    )


# ---------------------------------------------------------------------------
# Parsing ffmpeg's per-window output
# ---------------------------------------------------------------------------

def test_window_levels_are_read_off_the_metadata_lines():
    output = (
        "frame:0    pts:0       pts_time:0\n"
        "lavfi.astats.Overall.RMS_level=-53.861000\n"
        "frame:1    pts:16000   pts_time:1\n"
        "lavfi.astats.Overall.RMS_level=-28.970000\n"
    )
    levels, silent = _parse_windows(output)
    assert levels == [-53.861, -28.97]
    assert silent == 0


def test_digital_silence_is_counted_not_averaged_in():
    # float("-inf") parses happily and would drag every percentile to -inf, so
    # this is the one parse case that matters most.
    output = (
        "lavfi.astats.Overall.RMS_level=-inf\n"
        "lavfi.astats.Overall.RMS_level=-40.0\n"
        "lavfi.astats.Overall.RMS_level=-inf\n"
    )
    levels, silent = _parse_windows(output)
    assert levels == [-40.0]
    assert silent == 2


def test_unrelated_output_is_ignored():
    levels, silent = _parse_windows("Press [q] to stop\nlavfi.astats.Overall.Peak_level=-1.0\n")
    assert levels == []
    assert silent == 0


def test_percentiles_pick_the_quiet_and_loud_ends():
    values = [-60.0, -55.0, -50.0, -35.0, -30.0, -28.0]
    assert _percentile(values, 0) == -60.0
    assert _percentile(values, 100) == -28.0
    assert _percentile(values, 50) in (-50.0, -35.0)


def test_a_profile_reports_the_margin_between_the_two_ends():
    assert _profile(-54.0, -29.0).snr_db == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# The decision rule
# ---------------------------------------------------------------------------

def test_clean_audio_is_not_spectrally_denoised():
    # The measured clean take sat at 24.9 dB. afftdn has no floor to subtract
    # there and can only trade speech for artefacts.
    chain = adaptive_filter(_profile(-54.0, -29.0))
    assert "afftdn" not in chain
    assert chain == "highpass=f=100,lowpass=f=7000,loudnorm=I=-16:TP=-1.5:LRA=11"


def test_band_limiting_and_loudness_are_unconditional():
    for floor, speech in ((-54.0, -29.0), (-38.0, -28.5), (-29.0, -26.0)):
        chain = adaptive_filter(_profile(floor, speech))
        assert chain.startswith("highpass=f=100")
        assert chain.endswith("lowpass=f=7000,loudnorm=I=-16:TP=-1.5:LRA=11")


def test_the_measured_floor_is_what_afftdn_is_told():
    # The entire point of measuring: nf is the floor we found, not a constant.
    assert "nf=-38" in adaptive_filter(_profile(-38.31, -28.53))
    assert "nf=-49" in adaptive_filter(_profile(-48.82, -28.94))


def test_noisier_audio_is_denoised_harder():
    moderate = adaptive_filter(_profile(-40.0, -40.0 + (CLEAN_SNR_DB - 1)))
    noisy = adaptive_filter(_profile(-40.0, -40.0 + (NOISY_SNR_DB - 1)))
    assert "afftdn" in moderate and "afftdn" in noisy
    moderate_nr = int(moderate.split("afftdn=nr=")[1].split(":")[0])
    noisy_nr = int(noisy.split("afftdn=nr=")[1].split(":")[0])
    assert noisy_nr > moderate_nr


def test_the_floor_stays_inside_the_range_afftdn_accepts():
    # afftdn takes nf in -80..-20; a profile outside that must not produce a
    # chain ffmpeg refuses to build.
    assert "nf=-80" in adaptive_filter(_profile(-120.0, -115.0))
    assert "nf=-20" in adaptive_filter(_profile(-5.0, -3.0))


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

async def test_a_file_that_is_not_audio_reports_no_opinion(tmp_path):
    broken = tmp_path / "short.flac"
    broken.write_bytes(b"not audio")
    assert await measure_noise(str(broken)) is None


async def test_too_short_to_judge_reports_no_opinion(tmp_path):
    # A clip shorter than _MIN_WINDOWS seconds must not get a filter shaped by
    # three windows of audio; it keeps the calibrated chain instead.
    clip = tmp_path / "short.flac"
    await arun([
        ffmpeg_path(), "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=16000:duration=3",
        "-c:a", "flac", "-loglevel", "error", str(clip),
    ], timeout=60)
    assert clip.stat().st_size > 0
    assert await measure_noise(str(clip)) is None


async def test_an_unreadable_source_reports_no_opinion():
    assert await measure_noise("/nope/missing.wav") is None


@pytest.mark.skipif(
    not sample_available(VIDEO), reason="sample video not fetched (run: git lfs pull)"
)
async def test_a_real_source_measures_and_the_chain_it_builds_runs(tmp_path):
    profile = await measure_noise(VIDEO, sample_seconds=30.0)
    assert profile is not None
    assert profile.windows >= 8
    assert profile.noise_floor_db < 0
    assert profile.speech_level_db > profile.noise_floor_db

    # The real check: ffmpeg accepts the chain this profile produced.
    out = await extract_audio(
        VIDEO, str(tmp_path / "adaptive.flac"), audio_filter=adaptive_filter(profile)
    )
    assert out and (tmp_path / "adaptive.flac").stat().st_size > 0


# ---------------------------------------------------------------------------
# How the client chooses a chain
# ---------------------------------------------------------------------------

async def test_an_empty_audio_filter_still_means_no_filtering(monkeypatch):
    # Two knobs can disagree; "off" has to win, or there is no way to turn
    # cleanup off while adaptive is enabled somewhere up the stack.
    from vida.client import Vida

    called = False

    async def _never(*args, **kwargs):
        nonlocal called
        called = True
        return

    monkeypatch.setattr("vida.client.measure_noise", _never)
    vida = Vida(config=VidaConfig(
        asr=ASRConfig(audio_filter="", adaptive_denoise=True, openrouter_api_key="k")
    ))
    captured = {}

    async def _extract(path, work_dir, has_audio, *, audio_filter, dialogue_filter):
        captured["audio_filter"] = audio_filter
        return "audio.flac"

    monkeypatch.setattr("vida.client.extract_audio_for", _extract)
    from vida.types import MediaInfo

    await vida._audio_for(MediaInfo(path="v.mp4", duration=10.0, size_mb=1.0, has_audio=True), "/tmp")
    assert captured["audio_filter"] == ""
    assert called is False


async def test_an_unmeasurable_source_keeps_the_calibrated_chain(monkeypatch):
    from vida.client import Vida
    from vida.types import MediaInfo

    async def _no_opinion(*args, **kwargs):
        return None

    monkeypatch.setattr("vida.client.measure_noise", _no_opinion)
    vida = Vida(config=VidaConfig(
        asr=ASRConfig(audio_filter="highpass=f=100", adaptive_denoise=True,
                      openrouter_api_key="k")
    ))
    captured = {}

    async def _extract(path, work_dir, has_audio, *, audio_filter, dialogue_filter):
        captured["audio_filter"] = audio_filter
        return "audio.flac"

    monkeypatch.setattr("vida.client.extract_audio_for", _extract)
    await vida._audio_for(MediaInfo(path="v.mp4", duration=10.0, size_mb=1.0, has_audio=True), "/tmp")
    assert captured["audio_filter"] == "highpass=f=100"


async def test_a_measured_source_gets_the_shaped_chain(monkeypatch):
    from vida.client import Vida
    from vida.types import MediaInfo

    async def _measured(*args, **kwargs):
        return _profile(-54.0, -29.0)

    monkeypatch.setattr("vida.client.measure_noise", _measured)
    vida = Vida(config=VidaConfig(
        asr=ASRConfig(adaptive_denoise=True, openrouter_api_key="k")
    ))
    captured = {}

    async def _extract(path, work_dir, has_audio, *, audio_filter, dialogue_filter):
        captured["audio_filter"] = audio_filter
        return "audio.flac"

    monkeypatch.setattr("vida.client.extract_audio_for", _extract)
    await vida._audio_for(MediaInfo(path="v.mp4", duration=10.0, size_mb=1.0, has_audio=True), "/tmp")
    assert "afftdn" not in captured["audio_filter"]
    assert captured["audio_filter"] != ASRConfig().audio_filter


async def test_adaptive_is_off_by_default(monkeypatch):
    assert ASRConfig().adaptive_denoise is False
