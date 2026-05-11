import hands.tools as hand_tools

if __name__ == "__main__":
    final_summary = hand_tools.video_analysis(
        "/Users/lawrence/Projects/VidA/vids/test2.mp4",
        "Categorize the content of this video into one word categories, and list the key events in this video?",
        max_workers=4,   # ← tune this
    )
    print("\nFinal Summary:\n", final_summary)