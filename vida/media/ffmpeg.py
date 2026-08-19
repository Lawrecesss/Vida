"""Locating and driving ffmpeg.

A system ffmpeg is preferred, but many machines don't have one, so we fall back
to the static binary that ``imageio-ffmpeg`` ships. ffprobe is *not* bundled
with imageio-ffmpeg, so :func:`probe` parses ``ffmpeg -i`` stderr when ffprobe
is unavailable.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import re
import shutil
import subprocess

from vida.errors import FFmpegNotFoundError, MediaError

__all__ = ["ffmpeg_path", "ffprobe_path", "run", "arun", "probe_raw"]


@functools.lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """Absolute path to a usable ffmpeg binary."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - depends on the host
        raise FFmpegNotFoundError(
            "No ffmpeg binary found. Install ffmpeg (apt install ffmpeg / brew install ffmpeg) "
            "or install the bundled one with: pip install imageio-ffmpeg"
        ) from exc


@functools.lru_cache(maxsize=1)
def ffprobe_path() -> str | None:
    """Absolute path to ffprobe, or ``None`` if the host has no ffprobe.

    imageio-ffmpeg does not ship ffprobe, so this legitimately returns ``None``
    on many systems; callers must have a fallback.
    """
    return shutil.which("ffprobe")


def run(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run an ffmpeg-family command, raising :class:`MediaError` on failure."""
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError(f"Could not execute {args[0]!r}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{os.path.basename(args[0])} timed out after {timeout}s") from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-8:]
        raise MediaError(
            f"{os.path.basename(args[0])} failed (exit {proc.returncode}):\n" + "\n".join(tail)
        )
    return proc


async def arun(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Async wrapper around :func:`run`, so many transcodes can overlap."""
    return await asyncio.to_thread(run, args, timeout=timeout)


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_VIDEO_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?:\s*Video:.*?(\d{2,5})x(\d{2,5})")
_AUDIO_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?:\s*Audio:")


def _probe_with_ffprobe(path: str, probe_bin: str) -> dict:
    proc = run(
        [
            probe_bin,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            path,
        ],
        timeout=60,
    )
    data = json.loads(proc.stdout)

    duration = 0.0
    fmt_duration = data.get("format", {}).get("duration")
    if fmt_duration:
        duration = float(fmt_duration)

    width = height = None
    has_audio = False
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind == "video" and width is None:
            width = stream.get("width")
            height = stream.get("height")
            if not duration and stream.get("duration"):
                duration = float(stream["duration"])
        elif kind == "audio":
            has_audio = True

    return {"duration": duration, "width": width, "height": height, "has_audio": has_audio}


def _probe_with_ffmpeg(path: str) -> dict:
    """Parse ``ffmpeg -i`` stderr. Used when the host has no ffprobe.

    ``ffmpeg -i`` with no output file always exits non-zero, so we read the
    process output directly instead of going through :func:`run`.
    """
    try:
        proc = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-i", path],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"Probing {path!r} timed out") from exc

    output = proc.stderr or ""
    if "Invalid data found" in output or "No such file" in output:
        raise MediaError(f"Could not read media file: {path}")

    duration = 0.0
    if (m := _DURATION_RE.search(output)) :
        hours, minutes, seconds = int(m.group(1)), int(m.group(2)), float(m.group(3))
        duration = hours * 3600 + minutes * 60 + seconds

    width = height = None
    if (m := _VIDEO_STREAM_RE.search(output)) :
        width, height = int(m.group(1)), int(m.group(2))

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": bool(_AUDIO_STREAM_RE.search(output)),
    }


def probe_raw(path: str) -> dict:
    """Return ``{duration, width, height, has_audio}`` for a media file."""
    if not os.path.exists(path):
        raise MediaError(f"File not found: {path}")

    probe_bin = ffprobe_path()
    if probe_bin:
        try:
            return _probe_with_ffprobe(path, probe_bin)
        except (MediaError, json.JSONDecodeError, ValueError):
            pass  # fall through to the ffmpeg parser
    return _probe_with_ffmpeg(path)
