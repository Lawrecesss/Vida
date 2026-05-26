import asyncio
from brain.brain import run_agent

async def main():
    test_cases = [
        {
            "label": "General summary",
            "message": "Can you analyze this video and tell me what it's about? The file is at /Users/lawrence/Projects/VidA/vids/vlog.mp4"
        },
        {
            "label": "Specific query",
            "message": "What are the key events in /Users/lawrence/Projects/VidA/vids/vlog.mp4?"
        },
        {
            "label": "Missing file",
            "message": "Analyze the video at /nonexistent/path/video.mp4"
        },
    ]

    for case in test_cases:
        print(f"\n{'='*60}")
        print(f"🧪 Test: {case['label']}")
        print(f"💬 Message: {case['message']}")
        print(f"{'='*60}")
        try:
            response = await run_agent(case["message"])
            print(f"✅ Response:\n{response}")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())