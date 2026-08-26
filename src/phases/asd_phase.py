import cv2
import subprocess
from pathlib import Path
from src.core.config import log
from src.core.models import MatchResult, SearchWindow, VideoMeta
from src.engine.asd_engine import TalkNetASDEngine

def extract_asd_media(meta: VideoMeta, asr_best: MatchResult, fps: int = 25):
    """
    Extracts frames strictly around the exact ASR timestamp to prevent adjacent shots (B-roll) from bleeding into the analysis.
    """
    # Create a tight 2-second window around the center of the dialogue
    tight_start = max(0.0, asr_best.timestamp - 1.0)
    tight_end = min(meta.duration, asr_best.timestamp + 1.0)
    
    log.info("Extracting frames for TalkNet (Tight Window) from %.2fs to %.2fs", tight_start, tight_end)
    
    # Extract video frames
    cap = cv2.VideoCapture(meta.video_path)
    frames = []
    
    if cap.isOpened():
        start_frame = int(tight_start * meta.fps)
        end_frame = int(tight_end * meta.fps)
        
        # MASSIVE BOTTLENECK FIX: Seek only once, then read sequentially!
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        
        frame_step = max(1, round(meta.fps / fps))
        current_frame = start_frame
        
        while current_frame <= end_frame:
            ret, frame = cap.read()
            if not ret:
                break
                
            if (current_frame - start_frame) % frame_step == 0:
                frames.append(frame)
                
            current_frame += 1
            
        cap.release()
        
    log.info("Extracted %d frames for ASD processing.", len(frames))
    return frames

import json

def phase_asd(meta: VideoMeta, asr_best: MatchResult, window: SearchWindow) -> dict:
    """
    Executes the Active Speaker Detection (TalkNet) phase with persistent caching.
    """
    log.info("=== Phase ASD: TalkNet Speaker Classification ===")
    
    video_id = Path(meta.video_path).stem if meta.video_path else "unknown_video"
    asd_dir = Path("output/asd_cache") / video_id
    asd_dir.mkdir(parents=True, exist_ok=True)
    cache_file = asd_dir / "asd_results.json"
    
    cache_key = f"{asr_best.timestamp:.3f}"
    
    # 1. Check Cache
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
            if cache_key in cache_data:
                log.info("Found ASD result in cache for timestamp %s (Bypassing Inference)", cache_key)
                return cache_data[cache_key]
        except Exception:
            cache_data = {}
    else:
        cache_data = {}

    # 2. Run Pipeline on Cache Miss
    frames = extract_asd_media(meta, asr_best)
    
    tight_start = max(0.0, asr_best.timestamp - 1.0)
    tight_end = min(meta.duration, asr_best.timestamp + 1.0)
    
    engine = TalkNetASDEngine()
    result = engine.detect_speaker(frames, meta.audio_path, tight_start, tight_end)
    
    # 3. Save to Cache
    cache_data[cache_key] = result
    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=4)
        log.info("Saved ASD result to persistent disk cache.")
    except Exception as e:
        log.warning("Failed to save ASD cache: %s", str(e))
    
    log.info("TalkNet Result: %s (Confidence: %.2f)", result['status'], result['confidence'])
    return result
