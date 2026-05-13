import hands.video_analyzer as tools
import asyncio

if __name__ == "__main__":
    result = asyncio.run(tools.video_analyzer(
        video_path="/Users/lawrence/Projects/VidA/vids/vlog.mp4",
        user_query="What is the main topic and key events in this video?"
    ))

    # for seg in result["segments"]:
    #     print(f"\n[Seg {seg['index'] + 1} | {seg['mode']}]\n{seg['analysis']}")

    print(f"\n── Final Summary ──\n{result['summary']}")
