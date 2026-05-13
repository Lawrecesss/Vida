import os
import subprocess
from concurrent.futures import ProcessPoolExecutor

# Optimized Constants
MAX_SIZE_MB = 20
MAX_DURATION_S = 60
OUTPUT_BITRATE_KBPS = 500

def get_video_duration(video_path):
    """Uses ffprobe to get duration without loading the video into memory."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path
    ]
    return float(subprocess.check_output(cmd))

def process_single_segment(args) -> str:
    video_path, start_time, end_time, segment_index = args
    output_path = f"{video_path}_segment_{segment_index + 1}.mp4"
    duration = end_time - start_time
    
    # Optimized FFMPEG command: 
    # -ss BEFORE -i for fast seeking
    # -preset ultrafast for speed
    # -vf scale=854:-2 to maintain aspect ratio with even pixels
    cmd = [
        "ffmpeg", "-y", "-ss", str(start_time), "-t", str(duration),
        "-i", video_path,
        "-vf", "scale=854:-2",
        "-c:v", "libx264", "-preset", "ultrafast", 
        "-b:v", f"{OUTPUT_BITRATE_KBPS}k",
        "-c:a", "aac", "-b:a", "128k",
        "-loglevel", "quiet",
        output_path
    ]
    
    try:
        subprocess.run(cmd, check=True)
        return output_path
    except Exception as e:
        return f"Error in segment {segment_index}: {e}"

def parallel_video_segmentation(video_path: str, overlap: float = 2):
    try:
        total_duration = get_video_duration(video_path)
        
        # Calculate optimal duration (based on your 500kbps logic)
        output_mb_per_second = (OUTPUT_BITRATE_KBPS + 128) / 8 / 1024 
        size_based_duration = (MAX_SIZE_MB * 0.9) / output_mb_per_second
        segment_duration = min(size_based_duration, MAX_DURATION_S)

        tasks = []
        start_time = 0.0
        i = 0
        while start_time < total_duration:
            end_time = min(start_time + segment_duration, total_duration)
            tasks.append((video_path, start_time, end_time, i))
            start_time += (segment_duration - overlap)
            i += 1
            if end_time >= total_duration: break

        print(f"Launching {len(tasks)} parallel workers...")
        # Optimal workers: use os.cpu_count() or len(tasks)
        with ProcessPoolExecutor(max_workers=min(len(tasks), os.cpu_count())) as executor:
            results = list(executor.map(process_single_segment, tasks))

        return results
    except Exception as e:
        print(f"Segmentation failed: {e}")
        return []