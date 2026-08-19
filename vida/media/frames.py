"""Frame extraction, used as a fallback when a model rejects raw video input."""

from __future__ import annotations

import os

from vida.media.ffmpeg import arun, ffmpeg_path

__all__ = ["extract_frames"]


async def extract_frames(
    video_path: str,
    out_dir: str,
    *,
    count: int = 6,
    duration: float | None = None,
    timeout: float = 180.0,
) -> list[str]:
    """Grab ``count`` evenly spaced JPEG stills from ``video_path``.

    Uses one ffmpeg seek per frame rather than a decode of the whole file, which
    is far faster on long segments.
    """
    os.makedirs(out_dir, exist_ok=True)

    if duration is None:
        from vida.media.ffmpeg import probe_raw

        duration = probe_raw(video_path)["duration"]

    # Step back slightly from the very end; seeking to exactly `duration` often
    # lands past the last frame and produces nothing.
    usable = max(duration - 0.1, 0.0)
    paths: list[str] = []

    for i in range(count):
        timestamp = usable * i / max(count - 1, 1)
        dest = os.path.join(out_dir, f"frame_{i:02d}.jpg")
        await arun(
            [
                ffmpeg_path(), "-y",
                "-ss", f"{timestamp:.3f}",
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "4",
                "-loglevel", "error",
                dest,
            ],
            timeout=timeout,
        )
        if os.path.exists(dest):
            paths.append(dest)

    return paths
