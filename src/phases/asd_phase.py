import cv2
import subprocess
from pathlib import Path
from src.core.config import log
from src.core.models import MatchResult, SearchWindow, VideoMeta
from src.engine.asd_engine import TalkNetASDEngine

def extract_asd_media(meta: VideoMeta, window: SearchWindow, fps: int = 25):
    """
    Extracts frames corresponding to the ASR temporal window.
    (Audio is read directly from assets during inference, without disk extraction)
    """
    log.info("Extracting frames for TalkNet from %.2fs to %.2fs", window.start, window.end)
    
    # Extract video frames
    cap = cv2.VideoCapture(meta.video_path)
    frames = []
    
    if cap.isOpened():
        start_frame = int(window.start * meta.fps)
        end_frame = int(window.end * meta.fps)
        
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
    frames = extract_asd_media(meta, window)
    
    engine = TalkNetASDEngine()
    result = engine.detect_speaker(frames, meta.audio_path, window.start, window.end)
    
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
