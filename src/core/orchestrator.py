import time
import re
import uuid
from pathlib import Path
from typing import Optional

from src.core.config import log
from src.core.models import MatchResult, SearchWindow
from src.engine.ocr_engine import OCREngine
from src.phases.ingest import phase0_ingest
from src.phases.asr_phase import phase1_asr
from src.phases.ocr_phase import phase2_coarse_ocr
from src.phases.refine_phase import phase3_refine
from src.phases.output_phase import phase4_output

class DialogueDetector:
    def __init__(self, url: str, target_dialogue: str, work_dir: str = "output", local_video: str = "", mode: str = "asr_only", assets_dir: str = "assets", status_callback=None) -> None:
        self.status_callback = status_callback
        self.session_id = uuid.uuid4().hex
        self.url = url
        self.target = re.sub(r'[^\w\s]', ' ', target_dialogue).lower()
        self.mode = mode
        self.work_dir = Path(work_dir).resolve()
        
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.local_video = local_video
        self.assets_dir = Path(assets_dir).resolve()
        
        self.meta = None
        self.ocr = OCREngine()
        self.best: MatchResult = MatchResult()
        self.asr_best: Optional[MatchResult] = None

    def run(self) -> MatchResult:
        t0 = time.time()
        log.info("Target dialogue: '%s'", self.target)
        log.info("Video URL: %s", self.url)

        if self.status_callback: self.status_callback("node-media", "Loading media assets...")
        self.meta = phase0_ingest(self.url, self.local_video, self.assets_dir, self.status_callback)

        if self.mode == "ocr_only":
            log.info("Mode 'ocr_only' selected. Skipping ASR.")
            window = SearchWindow(0.0, self.meta.duration)
        else:
            if self.status_callback: self.status_callback("node-asr", "Running ASR audio transcription...")
            window, self.asr_best = phase1_asr(self.meta, self.target, self.status_callback)

        if self.mode == "asr_only":
            if self.asr_best is not None and self.asr_best.confidence >= 60:
                log.info("Mode 'asr_only': ASR matched target dialogue. Short-circuiting OCR.")
                
                # --- NEW TalkNet ASD Stage ---
                if self.status_callback: self.status_callback("node-asd", "Detecting active speakers (ASD)...")
                from src.phases.asd_phase import phase_asd
                asd_result = phase_asd(self.meta, self.asr_best, window)
                self.asr_best.asd_status = asd_result["status"]
                # ---------------------------
                
                self.best = self.asr_best
            else:
                log.info("Mode 'asr_only': ASR failed. Stopping pipeline as OCR is disabled.")
                self.best.status = "NOT_FOUND"
        elif self.mode == "asr_ocr":
            if self.asr_best is not None and self.asr_best.confidence >= 60:
                log.info("Mode 'asr_ocr': ASR anchored to %.2fs. Zooming into OCR refinement window.", self.asr_best.timestamp)
                t_coarse = self.asr_best.timestamp
                
                if self.status_callback: self.status_callback("node-ocr", "Refining anchor with OCR scan...")
                self.best = phase3_refine(self.meta, self.ocr, t_coarse, self.target, self.mode, self.best)
                
                # If OCR refinement didn't find subtitles (confidence is 0 or below ASR confidence), fall back to ASR
                if self.best.status == "NOT_FOUND" or self.best.confidence == 0 or self.best.confidence < self.asr_best.confidence:
                    log.warning("OCR refinement found no subtitles. Falling back to ASR transcription: '%s' (%.1f%%)", self.asr_best.extracted_text, self.asr_best.confidence)
                    
                    # Preserve the OCR timestamp if it found any frames, even with lower confidence
                    ocr_timestamp = self.best.timestamp
                    ocr_frame = self.best.frame_number
                    ocr_confidence = self.best.confidence
                    
                    self.best = self.asr_best
                    
                    if ocr_timestamp > 0 and ocr_confidence > 0:
                        self.best.timestamp = ocr_timestamp
                        self.best.frame_number = ocr_frame
                    elif ocr_frame > 0 and self.asr_best.frame_number == 0:
                        self.best.frame_number = ocr_frame
                
                # Run ASD Phase for dual mode if we have a valid ASR anchor
                if self.status_callback: self.status_callback("node-asd", "Detecting active speakers (ASD)...")
                from src.phases.asd_phase import phase_asd
                asd_result = phase_asd(self.meta, self.asr_best, window)
                self.best.asd_status = asd_result["status"]
            else:
                log.warning("Mode 'asr_ocr': ASR failed. Falling back to full video OCR.")
                if self.status_callback: self.status_callback("node-ocr", "Running full video OCR scan...")
                t_coarse, self.best = phase2_coarse_ocr(self.meta, self.ocr, window, self.target, self.status_callback)
                if t_coarse is not None:
                    if self.status_callback: self.status_callback("node-ocr", "Refining anchor with OCR scan...")
                    self.best = phase3_refine(self.meta, self.ocr, t_coarse, self.target, self.mode, self.best)
        else:
            if self.status_callback: self.status_callback("node-ocr", "Running full video OCR scan...")
            t_coarse, self.best = phase2_coarse_ocr(self.meta, self.ocr, window, self.target, self.status_callback)
            if t_coarse is not None:
                if self.status_callback: self.status_callback("node-ocr", "Refining anchor with OCR scan...")
                self.best = phase3_refine(self.meta, self.ocr, t_coarse, self.target, self.mode, self.best)

        if self.status_callback: self.status_callback("node-fuzzy", "Compiling alignment and merging results...")

        elapsed = time.time() - t0
        phase4_output(self.meta, self.best, self.session_id, self.work_dir, elapsed)
        log.info("Pipeline completed in %.1fs", elapsed)
        return self.best
