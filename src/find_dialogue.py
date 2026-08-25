#!/usr/bin/env python3
import argparse
import logging
from src.core.config import DEFAULT_URL, DEFAULT_DIALOGUE
from src.core.orchestrator import DialogueDetector

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find the exact video frame where a target dialogue appears on-screen.",
    )
    parser.add_argument(
        "--url", type=str, default=DEFAULT_URL,
        help="Video URL to process.",
    )
    parser.add_argument(
        "--target", type=str, default=DEFAULT_DIALOGUE,
        help="Target dialogue text to search for.",
    )
    parser.add_argument(
        "--video", type=str, default=None,
        help="Path to a local video file (skips download).",
    )
    parser.add_argument(
        "--mode", type=str, default="asr_ocr", choices=["asr_only", "ocr_only", "asr_ocr"],
        help="Detection mode to run.",
    )
    args = parser.parse_args()

    detector = DialogueDetector(
        url=args.url,
        target_dialogue=args.target,
        local_video=args.video,
        mode=args.mode
    )
    detector.run()

if __name__ == "__main__":
    main()
