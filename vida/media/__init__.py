"""Media I/O: ffmpeg discovery, probing, audio extraction, segmentation, frames."""

from vida.media.audio import AudioChunk, extract_audio, split_audio
from vida.media.encode import data_url, encode_file
from vida.media.ffmpeg import ffmpeg_path, ffprobe_path, probe_raw
from vida.media.frames import extract_frames
from vida.media.video import VideoSegment, probe, segment_video

__all__ = [
    "AudioChunk",
    "VideoSegment",
    "data_url",
    "encode_file",
    "extract_audio",
    "extract_frames",
    "ffmpeg_path",
    "ffprobe_path",
    "probe",
    "probe_raw",
    "segment_video",
    "split_audio",
]
