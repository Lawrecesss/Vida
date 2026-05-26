from core.helpers.encode_file import encode_file

def build_video_prompt(index: int, segment_path: str, user_query: str = None) -> list:
    return [
        {
            "type": "video_url",
            "video_url": {"url": f"data:video/mp4;base64,{encode_file(segment_path)}"}
        },
        {
            "type": "text",
            "text": (
                (f"User goal: {user_query}\n\n" if user_query else "") +
                "Watch this video and write a clear, concise summary (maximum 5 sentences)."
            )
        }
    ]

def build_frames_prompt(index: int, frame_paths: list[str], user_query: str = None) -> list:
    content = []
    for i, fp in enumerate(frame_paths):
        content.append({"type": "text", "text": f"Frame {i+1}:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_file(fp)}", "detail": "low"}})
    content.append({"type": "text", "text": f"Segment {index + 1}\n" + (f"User goal: {user_query}\n\n" if user_query else "") + "Analyze these frames..."})
    return content