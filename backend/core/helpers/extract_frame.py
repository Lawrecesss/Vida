import os
from moviepy import VideoFileClip

def extract_frames(segment_path: str, index: int, n: int = 6) -> list[str]:
    out_dir = f"frames/seg{index}"
    os.makedirs(out_dir, exist_ok=True)
    clip = VideoFileClip(segment_path)
    safe_duration = max(clip.duration - 0.1, 0)
    paths = []
    for i in range(n):
        t = safe_duration * i / (n - 1)
        path = f"{out_dir}/frame_{i}.jpg"
        clip.save_frame(path, t=t)
        paths.append(path)
    clip.close()
    return paths

def cleanup_frames(index: int):
    out_dir = f"frames/seg{index}"
    if os.path.exists(out_dir):
        for f in os.listdir(out_dir):
            os.remove(os.path.join(out_dir, f))
        os.rmdir(out_dir)