import os
from moviepy import VideoFileClip
from concurrent.futures import ProcessPoolExecutor

def process_single_segment(args) -> str:
    """
    Helper function to process one segment. 
    Using a single argument 'args' makes it easier to use with executor.map.
    """
    video_path, start_time, end_time, segment_index = args
    try:
        # We must load the clip inside the process for thread-safety/stability
        with VideoFileClip(video_path) as video:
            output_path = f"{video_path}_segment_{segment_index + 1}.mp4"
            print(f"Starting Segment {segment_index + 1}: {start_time}s to {end_time}s")
            
            # Create and write segment
            video_segment = video.subclipped(start_time, end_time)
            video_segment.write_videofile(
                output_path, 
                codec='libx264', 
                audio=True, 
                logger=None # Suppress massive logs
            )
        return output_path
    except Exception as e:
        return f"Error in segment {segment_index}: {e}"

def parallel_video_segmentation(video_path) -> list:
    try:
        video = VideoFileClip(video_path)
        duration = video.duration
        video.close() # Close initial load to free file for workers

        segment_duration = 30
        overlap = 2
        tasks = []
        
        # 1. Calculate all start/end times first
        start_time = 0
        i = 0
        while start_time < duration:
            end_time = min(start_time + segment_duration, duration)
            tasks.append((video_path, start_time, end_time, i))
            
            start_time += (segment_duration - overlap)
            i += 1
            if end_time >= duration: break

        # 2. Run in Parallel
        print(f"Launching {len(tasks)} parallel workers for {duration}s video...")
        with ProcessPoolExecutor() as executor:
            results = list(executor.map(process_single_segment, tasks))
        return results

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    parallel_video_segmentation("/Users/lawrence/Projects/VidA/vids/test1.MP4")