import time
import os
import json
import hashlib
from pathlib import Path
import concurrent.futures
from typing import Optional, Tuple
import cv2
import numpy as np
from rapidfuzz import fuzz
from src.utils.matcher import calculate_ocr_match_score

from src.core.config import log, COARSE_FPS, CONFIDENCE_LOW, CONFIDENCE_OK
from src.core.models import VideoMeta, SearchWindow, MatchResult
from src.phases.asr_phase import exact_word_match
from src.utils.utils import clean_text, crop_subtitle_region
from src.engine.ocr_engine import OCREngine

def get_video_id(meta: VideoMeta) -> str:
    return hashlib.md5(meta.video_path.encode()).hexdigest()

def get_cache_dir(meta: VideoMeta) -> Path:
    from src.core.config import OUTPUT_DIR
    d = OUTPUT_DIR / "ocr_cache" / get_video_id(meta)
    d.mkdir(parents=True, exist_ok=True)
    return d

def is_window_cached(meta: VideoMeta, window: SearchWindow) -> bool:
    cache_dir = get_cache_dir(meta)
    meta_path = cache_dir / "metadata.json"
    if not meta_path.exists(): return False
    try:
        with open(meta_path, 'r') as f:
            data = json.load(f)
        for r in data.get("ranges", []):
            if window.start >= r[0] and window.end <= r[1]:
                return True
    except: pass
    return False

def load_cached_samples(meta: VideoMeta) -> list:
    cache_dir = get_cache_dir(meta)
    samples_path = cache_dir / "samples.json"
    if samples_path.exists():
        try:
            with open(samples_path, 'r') as f:
                return json.load(f)
        except: pass
    return []

def save_cache(meta: VideoMeta, new_samples: list, window: SearchWindow):
    cache_dir = get_cache_dir(meta)
    samples = load_cached_samples(meta)
    samples.extend(new_samples)
    samples.sort(key=lambda x: x["timestamp"])
    
    with open(cache_dir / "samples.json", 'w') as f:
        json.dump(samples, f, indent=4)
        
    meta_path = cache_dir / "metadata.json"
    ranges = []
    if meta_path.exists():
        try:
            with open(meta_path, 'r') as f:
                ranges = json.load(f).get("ranges", [])
        except: pass
    ranges.append([window.start, window.end])
    
    with open(meta_path, 'w') as f:
        json.dump({"video_path": meta.video_path, "ranges": ranges}, f, indent=4)

def build_ocr_cache(meta: VideoMeta, ocr_engine: OCREngine, window: SearchWindow, status_callback=None) -> None:
    num_workers = min(2, (os.cpu_count() or 2))
    duration = window.end - window.start
    chunk_duration = duration / num_workers
    chunks = [(window.start + i * chunk_duration, window.start + (i + 1) * chunk_duration if i < num_workers - 1 else window.end) for i in range(num_workers)]
    
    all_blocks = []
    progress_dict = {i: 0.0 for i in range(num_workers)}
    
    def process_chunk(chunk_id: int, start_ts: float, end_ts: float) -> list:
        cap = cv2.VideoCapture(meta.video_path)
        chunk_results = []
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0: fps = 30
        
        ts = start_ts
        last_log_ts = start_ts
        last_thresh = None
        last_text = ""
        
        while ts <= end_ts:
            if ts - last_log_ts >= 30:
                pct = ((ts - start_ts) / (end_ts - start_ts + 0.1)) * 100
                progress_dict[chunk_id] = pct
                avg_pct = sum(progress_dict.values()) / num_workers
                log.info("OCR Thread %d: %.1f%% complete (Overall: %.1f%%)", chunk_id, pct, avg_pct)
                if status_callback:
                    status_callback("node-ocr", f"Running full video OCR scan... {avg_pct:.1f}%", avg_pct)
                last_log_ts = ts

            target_frame = int(ts * fps)
            current_frame = cap.get(cv2.CAP_PROP_POS_FRAMES)
            
            # Fast-forward optimization: if jumping < 60 frames, just grab() instead of heavy seeking
            if target_frame > current_frame and (target_frame - current_frame) < 60:
                for _ in range(int(target_frame - current_frame)):
                    cap.grab()
                ret, frame = cap.read()
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()
            if not ret:
                ts += 1.0 / COARSE_FPS
                continue
                
            sub_region = crop_subtitle_region(frame)
            
            # Blank Frame Binarization Skipping Optimization
            gray = cv2.cvtColor(sub_region, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
            white_pixels = cv2.countNonZero(thresh)
            
            if white_pixels < 50:
                last_thresh = None
                last_text = ""
                ts += 1.0 / COARSE_FPS
                continue
                
            # Visual Hashing (Bypass OCR if subtitle hasn't changed)
            if last_thresh is not None:
                diff = cv2.absdiff(thresh, last_thresh)
                if cv2.countNonZero(diff) < 100:  # Image is virtually identical
                    if last_text:
                        chunk_results.append({
                            "timestamp": float(ts),
                            "frame_number": int(ts * fps),
                            "text": last_text
                        })
                    ts += 1.0 / COARSE_FPS
                    continue
                    
            text = ocr_engine.extract_text(sub_region).strip()
            last_thresh = thresh.copy()
            last_text = text
            
            if last_text:
                chunk_results.append({
                    "timestamp": float(ts),
                    "frame_number": int(ts * fps),
                    "text": last_text
                })
                
            ts += 1.0 / COARSE_FPS
            
        cap.release()
        log.info("OCR Thread %d Finished.", chunk_id)
        return chunk_results

    log.info("Building OCR cache for window [%.2f, %.2f] across %d threads...", window.start, window.end, num_workers)
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(process_chunk, i, c[0], c[1]) for i, c in enumerate(chunks)]
        for future in concurrent.futures.as_completed(futures):
            try:
                all_blocks.extend(future.result())
            except Exception as exc:
                log.error("OCR chunk processing failed: %s", exc)
                
    save_cache(meta, all_blocks, window)

def phase2_coarse_ocr(meta: VideoMeta, ocr_engine: OCREngine, window: SearchWindow, target: str, status_callback=None) -> tuple:
    log.info("=== Phase 2: Coarse Sampled OCR ===")
    
    if not is_window_cached(meta, window):
        log.info("OCR cache miss for window [%.2f, %.2f]. Building cache...", window.start, window.end)
        build_ocr_cache(meta, ocr_engine, window, status_callback)
    else:
        log.info("Using persistent cached OCR transcript for window [%.2f, %.2f]", window.start, window.end)
        
    blocks = load_cached_samples(meta)
    
    best_score = 0.0
    best_ts = 0.0
    best_text = ""

    log.info("OCR Strategy: Block-based Token Set Ratio")
    
    for item in blocks:
        ts = item["timestamp"]
        if ts < window.start or ts > window.end:
            continue
            
        text = item["text"]
        score = calculate_ocr_match_score(target, text)

        if score >= CONFIDENCE_LOW:
            best_score = score
            best_ts = ts
            best_text = text
            log.info("  t=%.2fs  score=%.0f  text='%s'", ts, score, best_text[:80])
            log.info("Target text found! Halting coarse scan early.")
            break
            
        elif score > best_score:
            best_score = score
            best_ts = ts
            best_text = text

    if best_score >= CONFIDENCE_LOW:
        status = "OK" if best_score >= CONFIDENCE_OK else "LOW_CONFIDENCE"
        log.info("Coarse match: score=%.0f (%s) at t=%.2fs", best_score, status, best_ts)
        result = MatchResult(best_ts, int(best_ts * meta.fps), best_text, best_score, status)
        return best_ts, result

    log.warning("No coarse OCR match found (best=%.0f). Returning closest guess.", best_score)
    frame_num = int(best_ts * meta.fps) if best_ts > 0 else 0
    result = MatchResult(best_ts, frame_num, best_text, best_score, "NOT_FOUND")
    return None, result

