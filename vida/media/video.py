"""Video probing and segmentation for the visual-analysis path."""

from __future__ import annotations

import asyncio
import os

from vida.media.ffmpeg import arun, ffmpeg_path, probe_raw
from vida.types import MediaInfo

__all__ = ["probe", "segment_video", "VideoSegment"]

_ANALYSIS_BITRATE_KBPS = 500
_ANALYSIS_AUDIO_KBPS = 128


def probe(path: str) -> MediaInfo:
    """Read duration, dimensions, and audio presence off a media file."""
    raw = probe_raw(path)
    return MediaInfo(
        path=path,
        duration=raw["duration"],
        size_mb=os.path.getsize(path) / (1024 * 1024),
        has_audio=raw["has_audio"],
        width=raw["width"],
        height=raw["height"],
    )


class VideoSegment:
    """A transcoded slice of video, with its position in the original timeline."""

    __slots__ = ("path", "start", "end", "index")

    def __init__(self, path: str, start: float, end: float, index: int) -> None:
        self.path = path
        self.start = start
        self.end = end
        self.index = index

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)


async def _cut_segment(
    src: str, dest: str, start: float, duration: float, timeout: float
) -> None:
    await arun(
        [
            ffmpeg_path(), "-y",
            "-ss", f"{start:.3f}",   # before -i for a fast seek
            "-t", f"{duration:.3f}",
            "-i", src,
            "-vf", "scale=854:-2",   # -2 keeps the aspect ratio on an even pixel count
            "-c:v", "libx264", "-preset", "ultrafast",
            "-b:v", f"{_ANALYSIS_BITRATE_KBPS}k",
            "-c:a", "aac", "-b:a", f"{_ANALYSIS_AUDIO_KBPS}k",
            "-loglevel", "error",
            dest,
        ],
        timeout=timeout,
    )


async def segment_video(
    video_path: str,
    total_duration: float,
    *,
    max_mb: float = 20.0,
    max_seconds: float = 60.0,
    overlap: float = 2.0,
    out_dir: str | None = None,
    concurrency: int = 0,
    timeout: float = 600.0,
) -> list[VideoSegment]:
    """Cut a video into overlapping chunks small enough to send to a vision model.

    Segment length is whichever is shorter: the duration that fits in ``max_mb``
    at our transcode bitrate, or ``max_seconds``.
    """
    out_dir = out_dir or os.path.dirname(os.path.abspath(video_path))
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video_path))[0]

    mb_per_second = (_ANALYSIS_BITRATE_KBPS + _ANALYSIS_AUDIO_KBPS) / 8 / 1024
    size_limited = (max_mb * 0.9) / mb_per_second  # 10% headroom for container overhead
    segment_seconds = max(min(size_limited, max_seconds), 5.0)

    stride = max(segment_seconds - overlap, 1.0)
    planned: list[tuple[str, float, float, int]] = []
    start = 0.0
    index = 0
    while start < total_duration:
        end = min(start + segment_seconds, total_duration)
        planned.append((os.path.join(out_dir, f"{stem}_seg{index:04d}.mp4"), start, end, index))
        index += 1
        if end >= total_duration:
            break
        start += stride

    limit = concurrency or (os.cpu_count() or 4)
    semaphore = asyncio.Semaphore(limit)

    async def _run(dest: str, seg_start: float, seg_end: float) -> None:
        async with semaphore:
            await _cut_segment(video_path, dest, seg_start, seg_end - seg_start, timeout)

    await asyncio.gather(*(_run(d, s, e) for d, s, e, _ in planned))

    return [VideoSegment(d, s, e, i) for d, s, e, i in planned]
