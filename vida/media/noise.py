"""Measuring how noisy a source is, so the denoise chain can match it.

The fixed chain in :data:`vida.config.DEFAULT_AUDIO_FILTER` ends up asserting a
noise floor: ``afftdn=nf=-30`` tells the denoiser the noise sits at -30 dBFS,
and ``nr=20`` tells it to subtract 20 dB. Both are constants, and a constant is
wrong in two directions at once. Measured over a 120 s recorded address with
wind-like noise mixed in at three levels:

===================  =========  =========  ====
source               floor dB   speech dB   SNR
===================  =========  =========  ====
clean                   -53.9      -29.0   24.9
+ light noise           -48.8      -28.9   19.9
+ moderate noise        -38.3      -28.5    9.8
+ heavy noise           -28.7      -25.7    2.9
===================  =========  =========  ====

The speech level barely moves; the floor moves 25 dB. So on the clean take the
constant overstates the floor by 24 dB — ``afftdn`` is told to subtract a noise
floor that is not there and takes speech with it — while on the heavy take it
understates the noise and leaves it in. Measuring the floor instead costs one
bounded ffmpeg pass and removes the guess.

Deliberately off by default (``ASRConfig.adaptive_denoise``): per the project's
standing rule an audio change nobody measured on real fixtures does not become
a default, and the bands below are calibrated on synthetic noise over one
speaker. ``evals/asr`` is where that gets settled.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from vida.media.ffmpeg import arun, ffmpeg_path

__all__ = [
    "NoiseProfile",
    "measure_noise",
    "adaptive_filter",
    "CLEAN_SNR_DB",
    "NOISY_SNR_DB",
]

logger = logging.getLogger(__name__)

SAMPLE_SECONDS = 120.0
"""How much of the source to listen to.

A noise floor is a property of the microphone and the room, not of the minute
you sampled, so this is bounded rather than reading the whole file: the
measurement has to happen *before* extraction and would otherwise double the
decode cost of a feature-length input for no extra information.
"""

WINDOW_SECONDS = 1.0
"""Length of each RMS window.

Long enough that one window is either mostly speech or mostly not — the whole
measurement rests on that separation — and short enough that a 120 s sample
yields enough windows for a percentile to mean something.
"""

_MIN_WINDOWS = 8
"""Below this, report nothing rather than guess from a handful of windows."""

_FLOOR_PERCENTILE = 10.0
_SPEECH_PERCENTILE = 90.0
"""Percentiles, not min and max, because both extremes are outliers: the
quietest window is a digital-silence lead-in and the loudest is a door slam."""

CLEAN_SNR_DB = 20.0
"""At or above this, skip spectral denoising entirely.

The clean take above measured 24.9 dB and has no noise floor worth subtracting,
so running ``afftdn`` over it can only trade speech for artefacts.
"""

NOISY_SNR_DB = 10.0
"""Below this, denoise harder than the fixed chain does.

The moderate take measured 9.8 dB, which is where noise stops being a tint on
the recording and starts masking consonants.
"""

_NR_MODERATE = 16
_NR_NOISY = 28
"""Reduction in dB for the two bands that get denoised, bracketing the fixed
chain's 20. Provisional: the band boundaries are measured, these two numbers
are a bracket around a value that itself was tuned by ear on one clip."""


@dataclass(frozen=True)
class NoiseProfile:
    """What one bounded listen to a source says about its noise."""

    noise_floor_db: float
    """Level of the quiet windows, in dBFS — the noise floor."""

    speech_level_db: float
    """Level of the loud windows, in dBFS — roughly the speech level."""

    windows: int
    """Windows the measurement is based on, excluding digital silence."""

    silent_windows: int
    """Windows of true digital silence, excluded from both percentiles.

    Tracked separately because they are not a noise floor — a file with a
    muted lead-in has no noise *there*, and averaging it in would report a
    floor the rest of the file never reaches.
    """

    @property
    def snr_db(self) -> float:
        """Rough speech-to-noise margin. Not an SNR in the signal-processing
        sense — the loud windows contain noise too — but it orders sources by
        how much noise is sitting on the speech, which is all that is needed
        to pick a filter strength."""
        return self.speech_level_db - self.noise_floor_db


def _percentile(values: list[float], percentile: float) -> float:
    """Nearest-rank percentile of an already-finite list."""
    ordered = sorted(values)
    index = int(round((percentile / 100.0) * (len(ordered) - 1)))
    return ordered[min(max(index, 0), len(ordered) - 1)]


def _parse_windows(output: str) -> tuple[list[float], int]:
    """Pull per-window RMS levels out of ``ametadata`` output.

    Returns the finite levels and a count of the silent ones. ffmpeg prints
    ``-inf`` for a window of pure digital silence, and ``float()`` parses that
    happily into a value that poisons every percentile downstream — so they are
    separated here rather than filtered by accident.
    """
    levels: list[float] = []
    silent = 0
    for line in output.splitlines():
        key, separator, raw = line.partition("=")
        if not separator or not key.endswith("RMS_level"):
            continue
        try:
            value = float(raw.strip())
        except ValueError:
            continue
        if math.isfinite(value):
            levels.append(value)
        else:
            silent += 1
    return levels, silent


async def measure_noise(
    path: str,
    *,
    sample_seconds: float = SAMPLE_SECONDS,
    window_seconds: float = WINDOW_SECONDS,
    sample_rate: int = 16_000,
    timeout: float = 120.0,
) -> NoiseProfile | None:
    """Measure ``path``'s noise floor and speech level, or ``None`` if it can't.

    ``None`` means "no opinion" and callers must keep whatever filter they were
    already going to use. That is the safe direction: this runs ahead of the one
    decode that matters, and a source it cannot read a floor from — too short,
    an odd codec, an ffmpeg that moved its metadata output — is not a reason to
    transcribe unfiltered audio.
    """
    graph = (
        f"aformat=channel_layouts=mono,aresample={sample_rate},"
        # Fixed-size frames, because astats resets per frame and the decoder's
        # own frame size varies by codec — without this the window length, and
        # so the speech/silence separation, depends on the input format.
        f"asetnsamples=n={max(int(sample_rate * window_seconds), 1)},"
        "astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level,"
        "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-"
    )
    command = [
        ffmpeg_path(), "-hide_banner", "-nostats",
        "-t", f"{max(sample_seconds, 0.0):.3f}",
        "-i", path,
        "-map", "0:a:0",
        "-af", graph,
        "-loglevel", "error",
        "-f", "null", "-",
    ]
    try:
        completed = await arun(command, timeout=timeout)
    except Exception as exc:
        logger.debug("noise measurement failed for %s: %s", path, exc)
        return None

    levels, silent = _parse_windows(completed.stdout or "")
    if len(levels) < _MIN_WINDOWS:
        logger.debug(
            "noise measurement gave %d usable windows for %s, need %d",
            len(levels), path, _MIN_WINDOWS,
        )
        return None

    profile = NoiseProfile(
        noise_floor_db=_percentile(levels, _FLOOR_PERCENTILE),
        speech_level_db=_percentile(levels, _SPEECH_PERCENTILE),
        windows=len(levels),
        silent_windows=silent,
    )
    logger.info(
        "measured %s: floor %.1f dB, speech %.1f dB, margin %.1f dB over %d windows",
        path, profile.noise_floor_db, profile.speech_level_db,
        profile.snr_db, profile.windows,
    )
    return profile


def adaptive_filter(profile: NoiseProfile) -> str:
    """Build a denoise chain shaped to ``profile``.

    The band-limit and the loudness pass are unconditional: nothing above 7 kHz
    survives a 16 kHz model, speech has nothing below 100 Hz, and a quiet
    talker needs bringing up whether or not the recording is noisy. Only
    spectral denoising is conditional, because it is the only stage that can
    make a clean recording *worse*.
    """
    stages = ["highpass=f=100"]
    if profile.snr_db < CLEAN_SNR_DB:
        reduction = _NR_NOISY if profile.snr_db < NOISY_SNR_DB else _NR_MODERATE
        # nf is the measured floor rather than a constant, which is the point
        # of measuring at all. Clamped to afftdn's accepted range (-80..-20);
        # a floor above -20 dB means the noise is as loud as the speech and no
        # subtraction saves it.
        floor = min(max(profile.noise_floor_db, -80.0), -20.0)
        stages.append(f"afftdn=nr={reduction}:nf={floor:.0f}")
    stages += ["lowpass=f=7000", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    return ",".join(stages)
