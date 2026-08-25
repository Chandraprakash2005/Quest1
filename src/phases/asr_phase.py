import time
from typing import Optional, Tuple
from rapidfuzz import fuzz

from src.core.config import log, ASR_WINDOW_PAD
from src.core.models import VideoMeta, SearchWindow, MatchResult
from src.engine.asr_engine import get_whisper_model
from src.utils.utils import clean_text

_TRANSCRIPT_CACHE = {}

def get_sentence_context(words: list, match_start_idx: int, match_end_idx: int, max_context: int = 12) -> str:
    """Get the full surrounding sentence context for a matched word span."""
    left = match_start_idx
    for k in range(match_start_idx - 1, max(match_start_idx - max_context, -1), -1):
        if k < 0:
            break
        gap = words[k + 1]["start"] - words[k]["end"]
        if gap > 0.5:
            break
        left = k
    
    right = match_end_idx
    for k in range(match_end_idx + 1, min(match_end_idx + max_context, len(words))):
        gap = words[k]["start"] - words[k - 1]["end"]
        if gap > 0.5:
            break
        right = k
    
    context_words = words[left:right + 1]
    return " ".join([w["word"] for w in context_words]).strip()

def exact_word_match(target_words: list, transcript_words: list) -> tuple:
    import re
    target_clean = [re.sub(r'[^\w]', '', w).lower() for w in target_words if w.strip()]
    n_target = len(target_clean)
    
    if n_target == 0:
        return (0, 0.0, "", -1, -1)
    
    best_score = 0
    best_time = 0.0
    best_text = ""
    best_start = -1
    best_end = -1
    
    for i in range(len(transcript_words) - n_target + 1):
        window = transcript_words[i:i + n_target]
        window_clean = [re.sub(r'[^\w]', '', w["word"]).lower() for w in window]
        
        matches = 0
        for t, w in zip(target_clean, window_clean):
            if t == w or w == t + 's' or t == w + 's':
                matches += 1
        score = (matches / n_target) * 100
        
        if score > best_score:
            best_score = score
            best_text = " ".join([w["word"] for w in window]).strip()
            best_time = (window[0]["start"] + window[-1]["end"]) / 2.0
            best_start = i
            best_end = i + n_target - 1
            
            if best_score >= 100:
                break
    
    return (best_score, best_time, best_text, best_start, best_end)

def phase1_asr(meta: VideoMeta, target: str) -> tuple:
    log.info("=== Phase 1: ASR Accelerator ===")

    import json
    from pathlib import Path
    
    video_id = Path(meta.video_path).stem if meta.video_path else "unknown_video"
    cache_dir = Path("output/asr_cache") / video_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    cache_file = cache_dir / "samples.json"
    
    if cache_file.exists():
        log.info("Found persistent ASR cache on disk. Loading...")
        try:
            with open(cache_file, "r") as f:
                all_words = json.load(f)
        except Exception as e:
            log.warning("Failed to load ASR cache (%s). Will re-run.", str(e))
            all_words = None
    else:
        all_words = None

    if not all_words:
        log.info("ASR cache miss. Running Whisper over entire audio...")
        try:
            model = get_whisper_model("tiny.en")
            segments_iter, _ = model.transcribe(meta.audio_path, language="en", word_timestamps=True)
            
            all_words = []
            for seg in segments_iter:
                words = seg.words if hasattr(seg, "words") else seg.get("words", [])
                for w in words:
                    w_text = w.word if hasattr(w, "word") else w.get("word", "")
                    w_start = w.start if hasattr(w, "start") else w.get("start", 0)
                    w_end = w.end if hasattr(w, "end") else w.get("end", 0)
                    all_words.append({"word": w_text, "start": w_start, "end": w_end})
                    
            with open(cache_file, "w") as f:
                json.dump(all_words, f, indent=2)
            log.info("Saved ASR cache to disk: %s", cache_file)
                
        except Exception as exc:
            log.warning("ASR inference failed (%s). Falling back to full scan.", str(exc)[:50])
            return SearchWindow(0.0, meta.duration), None

    words = all_words
    target_words = target.split()
    n_target_words = len(target_words)
    
    best_score = 0.0
    best_time = 0.0
    best_text = ""

    log.info("ASR Strategy 1: Exact whole-word matching for '%s' (%d words)", target, n_target_words)
    exact_score, exact_time, exact_text, m_start, m_end = exact_word_match(target_words, words)
    
    best_score = exact_score
    best_time = exact_time
    if exact_score > 0:
        best_text = get_sentence_context(words, m_start, m_end) if m_start >= 0 else exact_text
    else:
        best_text = ""

    if exact_score >= 100:
        log.info("Exact match found: score=%.0f at t=%.2fs text='%s'", exact_score, exact_time, best_text[:80])
    elif n_target_words >= 3:
        log.info("ASR Strategy 2: Fuzzy sliding window (target has %d words)", n_target_words)
        for i in range(len(words)):
            for j in range(i + 1, min(i + n_target_words + 3, len(words) + 1)):
                window = words[i:j]
                w_text = " ".join([w["word"] for w in window]).strip()
                w_score = fuzz.ratio(target.lower(), clean_text(w_text).lower())
                
                if len(window) < (n_target_words * 0.7):
                    w_score -= 20
                
                if w_score > best_score:
                    best_score = w_score
                    best_text = get_sentence_context(words, i, j - 1)
                    best_time = (window[0]["start"] + window[-1]["end"]) / 2.0
                    
            if best_score >= 85:
                log.info("Fuzzy match found! Halting search.")
                break
    else:
        if exact_score >= 50:
            context_text = get_sentence_context(words, m_start, m_end) if m_start >= 0 else exact_text
            best_score = exact_score
            best_time = exact_time
            best_text = context_text
            log.info("Partial exact match for short target: score=%.0f at t=%.2fs", exact_score, exact_time)
        else:
            log.info("No exact match for short target '%s'. Rejecting fuzzy matches.", target)

    asr_best = None
    if best_score > 0:
        asr_best = MatchResult(
            timestamp=best_time,
            frame_number=int(best_time * meta.fps),
            extracted_text=best_text,
            confidence=best_score,
            status="ASR_ONLY_MATCH"
        )
        log.info("ASR best: score=%.0f  time=%.2fs  text='%s'", best_score, best_time, best_text[:100])

    if best_score >= 60:
        win_start = max(0.0, best_time - ASR_WINDOW_PAD)
        win_end = min(meta.duration, best_time + ASR_WINDOW_PAD)
        log.info("ASR match (score=%.0f) at ~%.2fs → window [%.2f, %.2f]", best_score, best_time, win_start, win_end)
        return SearchWindow(win_start, win_end), asr_best

    log.warning("No ASR match found (best=%.0f). Full-scan fallback.", best_score)
    return SearchWindow(0.0, meta.duration), asr_best
