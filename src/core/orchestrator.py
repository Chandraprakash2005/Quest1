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
    def __init__(self, url: str, target_dialogue: str, work_dir: str = "output", local_video: str = "", mode: str = "asr_only", assets_dir: str = r"C:\Users\dayan\Documents\Quest1\assets") -> None:
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

        self.meta = phase0_ingest(self.url, self.local_video, self.assets_dir)

        if self.mode == "ocr_only":
            log.info("Mode 'ocr_only' selected. Skipping ASR.")
            window = SearchWindow(0.0, self.meta.duration)
        else:
            window, self.asr_best = phase1_asr(self.meta, self.target)

        if self.mode == "asr_only":
            if self.asr_best is not None and self.asr_best.confidence >= 60:
                log.info("Mode 'asr_only': ASR matched target dialogue. Short-circuiting OCR.")
                self.best = self.asr_best
            else:
                log.info("Mode 'asr_only': ASR failed. Stopping pipeline as OCR is disabled.")
                self.best.status = "NOT_FOUND"
        elif self.mode == "asr_ocr":
            if self.asr_best is not None and self.asr_best.confidence >= 60:
                log.info("Mode 'asr_ocr': ASR anchored to %.2fs. Zooming into OCR refinement window.", self.asr_best.timestamp)
                t_coarse = self.asr_best.timestamp
                self.best = phase3_refine(self.meta, self.ocr, t_coarse, self.target, self.mode, self.best)
                
                if self.best.status == "NOT_FOUND":
                    log.warning("OCR refinement failed to find subtitles. Falling back to ASR anchor.")
                    self.best = self.asr_best
            else:
                log.warning("Mode 'asr_ocr': ASR failed. Falling back to full video OCR.")
                t_coarse, self.best = phase2_coarse_ocr(self.meta, self.ocr, window, self.target)
                if t_coarse is not None:
                    self.best = phase3_refine(self.meta, self.ocr, t_coarse, self.target, self.mode, self.best)
        else:
            t_coarse, self.best = phase2_coarse_ocr(self.meta, self.ocr, window, self.target)
            if t_coarse is not None:
                self.best = phase3_refine(self.meta, self.ocr, t_coarse, self.target, self.mode, self.best)

        phase4_output(self.meta, self.best, self.session_id, self.work_dir)

        elapsed = time.time() - t0
        log.info("Pipeline completed in %.1fs", elapsed)
        return self.best
