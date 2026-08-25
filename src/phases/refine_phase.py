import cv2
from typing import Tuple
from rapidfuzz import fuzz
from src.utils.matcher import calculate_ocr_match_score

from src.core.config import log, CONFIDENCE_LOW, CONFIDENCE_OK, REFINE_PASS_A, REFINE_PASS_B
from src.core.models import VideoMeta, MatchResult
from src.utils.utils import clean_text, crop_subtitle_region
from src.engine.ocr_engine import OCREngine

def scan_range(meta: VideoMeta, ocr_engine: OCREngine, start: float, end: float, step: float, target: str, t_coarse: float) -> Tuple[float, float, str]:
    cap = cv2.VideoCapture(meta.video_path)
    if not cap.isOpened():
        return 0.0, t_coarse, ""

    best_s, best_t, best_txt = 0.0, t_coarse, ""
    t = start
    while t <= end:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * meta.fps))
        ret, frame = cap.read()
        if not ret:
            t += step
            continue
        sub_region = crop_subtitle_region(frame)
        text = ocr_engine.extract_text(sub_region)
        score = calculate_ocr_match_score(target, text)
        
        if score > best_s:
            log.info("    New best frame: score=%.0f at t=%.3fs text='%s'", score, t, text[:50])
            best_s, best_t, best_txt = score, t, text
            
        t += step
        
    cap.release()
    return best_s, best_t, best_txt

def find_first_appearance(meta: VideoMeta, ocr_engine: OCREngine, t_center: float, frame_step: float, target: str, current_best: MatchResult) -> MatchResult:
    log.info("=== Finding first appearance (walking backwards from t=%.3fs) ===", t_center)
    cap = cv2.VideoCapture(meta.video_path)
    if not cap.isOpened():
        return current_best

    earliest_t = t_center
    earliest_txt = current_best.extracted_text
    earliest_score = current_best.confidence

    back_step = max(frame_step, 0.1)
    max_back = 0.5
    steps = 0

    t = t_center - back_step
    while t >= max(0, t_center - max_back) and steps < 5:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * meta.fps))
        ret, frame = cap.read()
        if not ret:
            break
        sub_region = crop_subtitle_region(frame)
        text = ocr_engine.extract_text(sub_region)
        score = calculate_ocr_match_score(target, text)
        log.info("  backward t=%.3fs  score=%.0f", t, score)
        # Only walk backwards if the previous frame retains the exact same maximum score
        # This prevents it from accidentally latching onto a different, lower-scoring sentence
        if score >= (current_best.confidence - 2):
            earliest_t = t
            earliest_txt = text
            earliest_score = score
            t -= back_step
            steps += 1
        else:
            break

    cap.release()

    status = "OK" if earliest_score >= CONFIDENCE_OK else "LOW_CONFIDENCE"
    frame_num = int(earliest_t * meta.fps)
    result = MatchResult(earliest_t, frame_num, earliest_txt, earliest_score, status)
    log.info("First appearance at t=%.5fs  frame=%d  score=%.0f", earliest_t, frame_num, earliest_score)
    return result

def phase3_refine(meta: VideoMeta, ocr_engine: OCREngine, t_coarse: float, target: str, mode: str, current_best: MatchResult) -> MatchResult:
    log.info("=== Phase 3: Temporal Refinement ===")

    fps_refinement = False

    if mode == "ocr_only":
        window_a_start = max(0, t_coarse - 1.0)
        window_a_end = t_coarse
        fps_refinement = True
    else:
        window_a_start = max(0, t_coarse - 2.0)
        window_a_end = min(meta.duration, t_coarse + 2.0)
        
    log.info("Pass A: 0.1s steps in [%.2f, %.2f]", window_a_start, window_a_end)
    s_a, t_a, txt_a = scan_range(meta, ocr_engine, window_a_start, window_a_end, REFINE_PASS_A, target, t_coarse)
    log.info("  → best t=%.3fs  score=%.0f", t_a, s_a)

    if mode == "ocr_only":
        window_b_start = max(0, t_a - 0.1)
        window_b_end = t_a
    else:
        window_b_start = max(0, t_a - 0.1)
        window_b_end = min(meta.duration, t_a + 0.1)

    log.info("Pass B: 0.01s steps in [%.2f, %.2f]", window_b_start, window_b_end)
    s_b, t_b, txt_b = scan_range(meta, ocr_engine, window_b_start, window_b_end, REFINE_PASS_B, target, t_a)
    log.info("  → best t=%.4fs  score=%.0f", t_b, s_b)

    if fps_refinement:
        frame_step = 1.0 / meta.fps if meta.fps > 0 else 0.04
        
        if mode == "ocr_only":
            window_c_start = max(0, t_b - 0.01)
            window_c_end = t_b
        else:
            window_c_start = max(0, t_b - 0.05)
            window_c_end = min(meta.duration, t_b + 0.05)
            
        log.info("Pass C: frame-level (%.5fs) in [%.4f, %.4f]", frame_step, window_c_start, window_c_end)
        s_c, t_c, txt_c = scan_range(meta, ocr_engine, window_c_start, window_c_end, frame_step, target, t_b)
        log.info("  → FINAL t=%.5fs  score=%.0f", t_c, s_c)
    else:
        log.info("Pass C: Skipped (Not required for mode='%s')", mode)
        frame_step = 0.01
        s_c, t_c, txt_c = s_b, t_b, txt_b

    best_refine_score = s_c if fps_refinement or s_c > 0 else s_b
    best_refine_t = t_c
    best_refine_txt = txt_c if txt_c else txt_b
    
    new_best = current_best
    if best_refine_score > 0:
        status = "OK" if best_refine_score >= CONFIDENCE_OK else "LOW_CONFIDENCE"
        new_best = MatchResult(best_refine_t, int(best_refine_t * meta.fps), best_refine_txt, best_refine_score, status)

    final_best = find_first_appearance(meta, ocr_engine, t_c, frame_step, target, new_best)
    return final_best

