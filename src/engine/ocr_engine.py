import os
import threading
import cv2
import numpy as np
from src.core.config import log

_EASYOCR_READER = None
_GPU_LOCK = threading.Lock()

class OCREngine:
    def __init__(self) -> None:
        self._engine = None
        self._backend: str = "none"
        self._init_engine()

    def _init_engine(self) -> None:
        global _EASYOCR_READER
        try:
            import easyocr
            os.environ["PYTHONIOENCODING"] = "utf-8"
            if _EASYOCR_READER is None:
                log.info("Loading EasyOCR into memory (this only happens once)...")
                _EASYOCR_READER = easyocr.Reader(["en"], gpu=True, verbose=False)
            self._engine = _EASYOCR_READER
            self._backend = "easyocr"
            log.info("OCR backend: EasyOCR")
            return
        except Exception as exc:
            log.error("EasyOCR could not be loaded: %s", exc)
            raise RuntimeError("No OCR backend available. Install easyocr.")

    def extract_text(self, image: np.ndarray) -> str:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        with _GPU_LOCK:
            if self._backend == "easyocr":
                results = self._engine.readtext(gray)
                return " ".join([r[1] for r in results])
        return ""
