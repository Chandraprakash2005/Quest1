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
    from collections import defaultdict
    
    target_clean = [re.sub(r'[^\w]', '', w).lower() for w in target_words if w.strip()]
    n_target = len(target_clean)
    
    if n_target == 0 or not transcript_words:
        return (0, 0.0, "", -1, -1)
    
    # Pre-clean transcript and build inverted index (using cached clean words if available)
    cleaned_transcript = []
    word_index = defaultdict(list)
    for i, w in enumerate(transcript_words):
        if "clean" in w:
            cw = w["clean"]
        else:
            cw = re.sub(r'[^\w]', '', w["word"]).lower()
            w["clean"] = cw  # Backfill RAM cache
            
        cleaned_transcript.append(cw)
        word_index[cw].append(i)
        
    # Find all potential window start indices using the inverted index
    candidate_starts = set()
    for offset, t_word in enumerate(target_clean):
        t_variations = [t_word]
        if not t_word.endswith('s'):
            t_variations.append(t_word + 's')
        elif t_word.endswith('s') and len(t_word) > 1:
            t_variations.append(t_word[:-1])
            
        for tv in t_variations:
            for idx in word_index.get(tv, []):
                start_idx = idx - offset
                if 0 <= start_idx <= len(transcript_words) - n_target:
                    candidate_starts.add(start_idx)
                    
    best_score = 0
    best_time = 0.0
    best_text = ""
    best_start = -1
    best_end = -1
    
    # Only iterate over windows that contain at least one matching word
    for i in sorted(list(candidate_starts)):
        window_clean = cleaned_transcript[i:i + n_target]
        
        matches = 0
        for t, w in zip(target_clean, window_clean):
            if t == w or w == t + 's' or t == w + 's':
                matches += 1
        score = (matches / n_target) * 100
        
        if score > best_score:
            best_score = score
            window_orig = transcript_words[i:i + n_target]
            best_text = " ".join([w["word"] for w in window_orig]).strip()
            best_time = (window_orig[0]["start"] + window_orig[-1]["end"]) / 2.0
            best_start = i
            best_end = i + n_target - 1
            
            if best_score >= 100:
                break
    
    return (best_score, best_time, best_text, best_start, best_end)

def phase1_asr(meta: VideoMeta, target: str) -> tuple:
    log.info("=== Phase 1: ASR Accelerator ===")

    import json
    from pathlib import Path
    
    global _TRANSCRIPT_CACHE
    video_id = Path(meta.video_path).stem if meta.video_path else "unknown_video"
    
    if video_id in _TRANSCRIPT_CACHE:
        log.info("Found ASR cache in RAM (instant load).")
        all_words = _TRANSCRIPT_CACHE[video_id]
    else:
        cache_dir = Path("output/asr_cache") / video_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        cache_file = cache_dir / "samples.json"
        
        if cache_file.exists():
            log.info("Found persistent ASR cache on disk. Loading into RAM...")
            try:
                with open(cache_file, "r") as f:
                    all_words = json.load(f)
                _TRANSCRIPT_CACHE[video_id] = all_words
            except Exception as e:
                log.warning("Failed to load ASR cache (%s). Will re-run.", str(e))
                all_words = None
        else:
            all_words = None

        if not all_words:
            log.info("ASR cache miss. Running Hybrid Whisper sweep...")
            import re
            try:
                # Pass 1: Small (high accuracy) sweep FIRST (Lazy Evaluation)
                log.info("Running high-accuracy sweep (small.en)...")
                small_model = get_whisper_model("small.en")
                small_iter, _ = small_model.transcribe(
                    meta.audio_path, language="en", word_timestamps=True, vad_filter=True, beam_size=2, condition_on_previous_text=False
                )
                small_words = []
                for seg in small_iter:
                    words_list = seg.get("words", []) if isinstance(seg, dict) else getattr(seg, "words", [])
                    if not words_list: continue
                    for w in words_list:
                        w_text = w.get("word", "") if isinstance(w, dict) else getattr(w, "word", "")
                        w_start = w.get("start", 0) if isinstance(w, dict) else getattr(w, "start", 0)
                        w_end = w.get("end", 0) if isinstance(w, dict) else getattr(w, "end", 0)
                        small_words.append({"word": w_text, "start": w_start, "end": w_end})
                        
                # Hybrid merge logic: check for all gaps > 5.0 seconds
                gaps = []
                if small_words and small_words[0]["start"] > 5.0:
                    gaps.append((0.0, small_words[0]["start"]))
                    
                for i in range(len(small_words) - 1):
                    g_start = small_words[i]["end"]
                    g_end = small_words[i+1]["start"]
                    if (g_end - g_start) > 5.0:
                        gaps.append((g_start, g_end))
                        
                if small_words and hasattr(meta, "duration") and (meta.duration - small_words[-1]["end"]) > 5.0:
                    gaps.append((small_words[-1]["end"], meta.duration))
                    
                if gaps:
                    log.info("Detected %d gaps > 5.0s. Fast-cropping for tiny.en sweep...", len(gaps))
                    import subprocess, tempfile, os
                    fallback_model = get_whisper_model("tiny.en")
                    fallback_words = []
                    
                    for (g_start, g_end) in gaps:
                        gap_audio = os.path.join(tempfile.gettempdir(), f"gap_{video_id}_{g_start}.wav")
                        duration = g_end - g_start
                        subprocess.run(["ffmpeg", "-y", "-i", meta.audio_path, "-ss", str(g_start), "-t", str(duration), "-c", "copy", gap_audio], capture_output=True)
                        
                        fallback_iter, _ = fallback_model.transcribe(
                            gap_audio, language="en", word_timestamps=True, vad_filter=True, beam_size=1, condition_on_previous_text=False
                        )
                        
                        for seg in fallback_iter:
                            words_list = seg.get("words", []) if isinstance(seg, dict) else getattr(seg, "words", [])
                            if not words_list: continue
                            for w in words_list:
                                w_text = w.get("word", "") if isinstance(w, dict) else getattr(w, "word", "")
                                w_start = w.get("start", 0) if isinstance(w, dict) else getattr(w, "start", 0)
                                w_end = w.get("end", 0) if isinstance(w, dict) else getattr(w, "end", 0)
                                # Offset timestamps relative to the crop
                                fallback_words.append({"word": w_text, "start": w_start + g_start, "end": w_end + g_start})
                        
                        if os.path.exists(gap_audio):
                            try: os.remove(gap_audio)
                            except: pass
                            
                    # Merge and sort
                    merged_words = small_words + fallback_words
                    merged_words.sort(key=lambda x: x["start"])
                    
                    all_words = []
                    for w in merged_words:
                        w_clean = re.sub(r'[^\w]', '', w["word"]).lower()
                        all_words.append({"word": w["word"], "start": w["start"], "end": w["end"], "clean": w_clean})
                else:
                    all_words = []
                    for w in small_words:
                        w_clean = re.sub(r'[^\w]', '', w["word"]).lower()
                        all_words.append({"word": w["word"], "start": w["start"], "end": w["end"], "clean": w_clean})
                        
                with open(cache_file, "w") as f:
                    json.dump(all_words, f, indent=2)
                _TRANSCRIPT_CACHE[video_id] = all_words
                log.info("Saved ASR cache to disk and RAM.")
                    
            except Exception as exc:
                log.warning("ASR inference failed (%s). Falling back to full scan.", str(exc)[:50])
                return SearchWindow(0.0, meta.duration), None

    words = all_words
    import re
    
    # Globally normalize the target string: replace punctuation with spaces to properly separate hyphenated words
    target_normalized = re.sub(r'[^\w\s]', ' ', target).lower()
    target_words = target_normalized.split()
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
        target_clean = " ".join(target_words)
        cleaned_words = [w.get("clean", re.sub(r'[^\w]', '', w["word"]).lower()) for w in words]
        
        for i in range(len(words)):
            for j in range(i + 1, min(i + n_target_words + 3, len(words) + 1)):
                window = words[i:j]
                w_clean_text = " ".join(cleaned_words[i:j]).strip()
                w_score = fuzz.ratio(target_clean, w_clean_text)
                
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
