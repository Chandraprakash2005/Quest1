#!/usr/bin/env python3
"""
find_dialogue.py — Multi-Modal Coarse-to-Fine Video Dialogue Detector

Identifies the exact video frame where a specific target dialogue appears
on-screen using an ASR + OCR pipeline. No VLMs or LLMs are used.

Architecture:
    Phase 0: Ingestion & Probing (yt-dlp + ffprobe)
    Phase 1: ASR Accelerator  (faster-whisper + rapidfuzz)
    Phase 2: Coarse Sampled OCR (1 fps sampling + PaddleOCR/EasyOCR)
    Phase 3: Temporal Refinement (multi-pass binary search)
    Phase 4: Output Generation (PNG frame + JSON manifest)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_URL = "https://ok.ru/video/248244667877"
DEFAULT_DIALOGUE = "My mind rebels at stagnation"
ASR_WINDOW_PAD = 2.0          # seconds before/after ASR hit
COARSE_FPS = 1.0              # 1 frame per second for coarse scan
CONFIDENCE_OK = 85
CONFIDENCE_LOW = 70
REFINE_PASS_A = 0.1           # seconds granularity
REFINE_PASS_B = 0.01
OUTPUT_FRAME = "output_frame.png"
OUTPUT_MANIFEST = "manifest.json"

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("DialogueDetector")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class VideoMeta:
    fps: float = 0.0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    video_path: str = ""
    audio_path: str = ""


@dataclass
class MatchResult:
    timestamp: float = 0.0
    frame_number: int = 0
    extracted_text: str = ""
    confidence: float = 0.0
    status: str = "NOT_FOUND"


@dataclass
class SearchWindow:
    start: float = 0.0
    end: float = 0.0


# ---------------------------------------------------------------------------
# OCR Backend abstraction
# ---------------------------------------------------------------------------
# Global caches for heavy models to drastically improve server speed
_EASYOCR_READER = None
_WHISPER_MODEL = None

_TRANSCRIPT_CACHE = {
    "url": "",
    "timestamp": 0,
    "words": []
}

class OCREngine:
    """Wraps PaddleOCR with EasyOCR fallback."""

    def __init__(self) -> None:
        self._engine = None
        self._backend: str = "none"
        self._init_engine()

    def _init_engine(self) -> None:
        global _EASYOCR_READER
        # PaddleOCR causes noisy logs and crashes on Windows CPU, skipping straight to EasyOCR
        try:
            import easyocr
            # Set env var to handle Unicode progress bar on Windows console
            os.environ["PYTHONIOENCODING"] = "utf-8"
            if _EASYOCR_READER is None:
                log.info("Loading EasyOCR into memory (this only happens once)...")
                _EASYOCR_READER = easyocr.Reader(["en"], gpu=True, verbose=False)
            self._engine = _EASYOCR_READER
            self._backend = "easyocr"
            log.info("OCR backend: EasyOCR")
            return
        except Exception as exc:
            log.error("Neither PaddleOCR nor EasyOCR could be loaded: %s", exc)
            raise RuntimeError("No OCR backend available. Install paddleocr or easyocr.")

    def extract_text(self, image: np.ndarray) -> str:
        """Return all detected text from an image as a single string."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        if self._backend == "paddleocr":
            try:
                results = self._engine.ocr(image)
                texts: List[str] = []
                if results and results[0]:
                    for line in results[0]:
                        texts.append(line[1][0])
                return " ".join(texts)
            except Exception as exc:
                log.warning("PaddleOCR crashed during inference (%s). Falling back to EasyOCR permanently.", type(exc).__name__)
                import easyocr
                os.environ["PYTHONIOENCODING"] = "utf-8"
                self._engine = easyocr.Reader(["en"], gpu=False, verbose=False)
                self._backend = "easyocr"
                log.info("OCR backend switched to EasyOCR")
                # Fall through to the easyocr block below

        if self._backend == "easyocr":
            results = self._engine.readtext(gray)
            return " ".join([r[1] for r in results])

        return ""


# ---------------------------------------------------------------------------
# Main detector class
# ---------------------------------------------------------------------------
class DialogueDetector:
    """Orchestrates the full coarse-to-fine detection pipeline."""

    def __init__(
        self,
        url: str,
        target_dialogue: str,
        work_dir: str = ".",
        local_video: Optional[str] = None,
        mode: str = "asr_only",
    ) -> None:
        self.url = url
        self.target = target_dialogue
        self.mode = mode
        self.work_dir = Path(work_dir).resolve()
        
        # We cap at 0.01s granularity by default. We do NOT drop to 1/fps for ASR+OCR refinement.
        self.fps_refinement = False if self.mode == "asr_ocr" else True
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.local_video = local_video

        self.meta = VideoMeta()
        self.ocr = OCREngine()
        self.best: MatchResult = MatchResult()
        self.asr_best: Optional[MatchResult] = None


    def _download_with_ytdlp(self, output_path: str) -> None:
        """Download video — tries direct HTTP extraction first, then yt-dlp."""
        import re
        import requests as req

        # ── Strategy 1: Direct extraction from ok.ru desktop page ──
        if "ok.ru" in self.url:
            try:
                log.info("Strategy 1: Direct ok.ru page extraction...")
                video_url = self._extract_okru_direct_url()
                if video_url:
                    self._http_download(video_url, output_path)
                    return
            except Exception as exc:
                log.warning("Direct extraction failed: %s", exc)

        # ── Strategy 2: yt-dlp with retries ──
        log.info("Strategy 2: yt-dlp download...")
        import yt_dlp

        base_opts = {
            "merge_output_format": "mp4",
            "outtmpl": output_path,
            "retries": 5,
            "fragment_retries": 5,
            "socket_timeout": 60,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            },
        }

        for fmt in [
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "best", 
            "worst"
        ]:
            for retry in range(2):
                try:
                    opts = {**base_opts, "format": fmt, "quiet": True}
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([self.url])
                    return
                except Exception as exc:
                    log.warning("yt-dlp (%s) retry %d failed: %s", fmt, retry + 1, str(exc)[:80])
                    time.sleep(2 ** retry)

        raise RuntimeError(
            "All download strategies failed.\n"
            "  Re-run with: --video path/to/downloaded_video.mp4"
        )

    def _extract_okru_direct_url(self) -> Optional[str]:
        """Extract the best direct video URL from ok.ru desktop page."""
        import re
        import requests as req

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        }
        resp = req.get(self.url, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text

        # ok.ru stores metadata in data-options attribute
        match = re.search(r'data-options="([^"]+)"', html)
        if not match:
            return None

        raw = match.group(1).replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        # Navigate: metadata -> videos array
        metadata_str = data.get("flashvars", {}).get("metadata", "")
        if not metadata_str:
            # Try nested path
            for key in data:
                if isinstance(data[key], dict) and "metadata" in data[key]:
                    metadata_str = data[key]["metadata"]
                    break

        if not metadata_str:
            return None

        try:
            metadata = json.loads(metadata_str)
        except json.JSONDecodeError:
            return None

        videos = metadata.get("videos", [])
        if not videos:
            return None

        # Prefer highest quality: sd > low > lowest > mobile
        quality_order = ["hd", "sd", "low", "lowest", "mobile"]
        url_map = {v.get("name", ""): v.get("url", "") for v in videos}

        for q in quality_order:
            if q in url_map and url_map[q]:
                url = url_map[q].replace("\\u0026", "&")
                log.info("Found %s quality stream", q)
                return url

        # Return first available
        first_url = videos[0].get("url", "")
        return first_url.replace("\\u0026", "&") if first_url else None

    def _http_download(self, url: str, output_path: str) -> None:
        """Download a file via HTTP with progress logging."""
        import requests as req

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        }
        log.info("Downloading video via direct HTTP...")
        resp = req.get(url, headers=headers, stream=True, timeout=120)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024  # 1 MB chunks

        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = (downloaded / total) * 100
                        log.info("  %.1f%% (%d / %d MB)", pct, downloaded // (1024*1024), total // (1024*1024))

        log.info("Download complete: %s (%.1f MB)", output_path, downloaded / (1024*1024))

    # ---- Phase 0 ----
    def phase0_ingest(self) -> None:
        """Download video and extract metadata + audio."""
        log.info("=== Phase 0: Ingestion & Probing ===")

        video_dir = Path("assets/video")
        audio_dir = Path("assets/audio")
        video_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)

        video_path = video_dir / "video.mp4"
        audio_path = audio_dir / "audio.wav"

        # Use local video if provided, otherwise download
        if self.local_video:
            import shutil
            local = Path(self.local_video)
            if not local.exists():
                raise FileNotFoundError(f"Local video not found: {self.local_video}")
            if local.resolve() != video_path.resolve():
                shutil.copy2(str(local), str(video_path))
            log.info("Using local video: %s", self.local_video)
        elif not video_path.exists():
            log.info("Downloading video from %s ...", self.url)
            # Try yt-dlp Python API first, then CLI fallback
            try:
                self._download_with_ytdlp(str(video_path))
                log.info("Download complete: %s", video_path)
            except Exception as exc:
                log.error(
                    "yt-dlp download failed: %s\n"
                    "If ok.ru is blocked in your region, download the video manually\n"
                    "and re-run with: --video path/to/video.mp4",
                    exc,
                )
                raise
        else:
            log.info("Video already exists, skipping download.")

        # Probe metadata with ffprobe
        log.info("Probing video metadata...")
        probe_cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", str(video_path),
        ]
        try:
            result = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
            info = json.loads(result.stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            log.error("ffprobe failed: %s", exc)
            raise

        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                fps_str = stream.get("r_frame_rate", "25/1")
                num, den = fps_str.split("/")
                self.meta.fps = float(num) / float(den) if float(den) != 0 else 25.0
                self.meta.width = int(stream.get("width", 0))
                self.meta.height = int(stream.get("height", 0))
                break

        self.meta.duration = float(info.get("format", {}).get("duration", 0))
        self.meta.video_path = str(video_path)
        log.info(
            "Metadata — fps=%.2f  duration=%.2fs  resolution=%dx%d",
            self.meta.fps, self.meta.duration, self.meta.width, self.meta.height,
        )

        # Extract audio as 16 kHz mono WAV
        if not audio_path.exists():
            log.info("Extracting audio track...")
            audio_cmd = [
                "ffmpeg", "-y", "-i", str(video_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(audio_path),
            ]
            try:
                subprocess.run(audio_cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as exc:
                log.error("Audio extraction failed: %s", exc.stderr)
                raise
        self.meta.audio_path = str(audio_path)
        log.info("Audio ready: %s", audio_path)

    # ---- Phase 1 ----
    def phase1_asr(self) -> SearchWindow:
        """Run ASR on audio and fuzzy-match the target dialogue."""
        log.info("=== Phase 1: ASR Accelerator ===")

        global _TRANSCRIPT_CACHE
        if _TRANSCRIPT_CACHE.get("url") != self.url or (time.time() - _TRANSCRIPT_CACHE.get("timestamp", 0)) > 600:
            log.info("Transcript cache empty or expired. Running Whisper over entire audio...")
            try:
                global _WHISPER_MODEL
                from faster_whisper import WhisperModel
                if _WHISPER_MODEL is None:
                    log.info("Loading faster-whisper into memory (this only happens once)...")
                    try:
                        # Dynamically inject pip-installed NVIDIA CUDA DLLs into PATH
                        import os, sys
                        from pathlib import Path
                        venv_dir = Path(sys.executable).parent.parent
                        for pkg in ["cublas", "cudnn", "cuda_nvrtc", "cuda_runtime"]:
                            bin_path = venv_dir / "Lib" / "site-packages" / "nvidia" / pkg / "bin"
                            if bin_path.exists():
                                os.environ["PATH"] = str(bin_path) + os.pathsep + os.environ["PATH"]
                                if hasattr(os, "add_dll_directory"):
                                    os.add_dll_directory(str(bin_path))

                        from faster_whisper import WhisperModel
                        _WHISPER_MODEL = WhisperModel("tiny.en", device="cuda", compute_type="float16")
                        log.info("faster-whisper (tiny.en) successfully loaded on CUDA GPU.")
                    except Exception as e:
                        log.warning("GPU load failed. Falling back to CPU: %s", str(e)[:40])
                        from faster_whisper import WhisperModel
                        _WHISPER_MODEL = WhisperModel("tiny.en", device="cpu", compute_type="int8")
                model = _WHISPER_MODEL
                segments_iter, _ = model.transcribe(self.meta.audio_path, language="en", word_timestamps=True)
            except Exception as exc:
                log.warning("faster-whisper failed (%s), trying openai-whisper...", exc)
                try:
                    import whisper
                    model = whisper.load_model("tiny.en")
                    result = model.transcribe(self.meta.audio_path, language="en", word_timestamps=True)
                    segments_iter = result.get("segments", [])
                except Exception as exc2:
                    log.warning("Whisper also failed (%s). Falling back to full scan.", exc2)
                    return SearchWindow(0.0, self.meta.duration)

            all_words = []
            for seg in segments_iter:
                words = seg.words if hasattr(seg, "words") else seg.get("words", [])
                for w in words:
                    w_text = w.word if hasattr(w, "word") else w.get("word", "")
                    w_start = w.start if hasattr(w, "start") else w.get("start", 0)
                    w_end = w.end if hasattr(w, "end") else w.get("end", 0)
                    all_words.append({"word": w_text, "start": w_start, "end": w_end})
            
            _TRANSCRIPT_CACHE = {
                "url": self.url,
                "timestamp": time.time(),
                "words": all_words
            }
        else:
            log.info("Using cached ASR transcript. Skipping Whisper inference!")

        best_score = 0.0
        best_time = 0.0
        best_text = ""

        # Sliding window over the entire flat transcript to avoid segment boundary cutoffs
        words = _TRANSCRIPT_CACHE["words"]
        for i in range(len(words)):
            for j in range(i + 1, min(i + 8, len(words) + 1)):
                window = words[i:j]
                w_text = " ".join([w["word"] for w in window]).strip()
                w_score = fuzz.ratio(self.target.lower(), w_text.lower())
                
                if w_score > best_score:
                    best_score = w_score
                    best_text = w_text
                    best_time = (window[0]["start"] + window[-1]["end"]) / 2.0
                    
            if best_score >= 85:
                log.info("Target spoken text found in cache! Halting search.")
                break

        if best_score > 0:
            self.asr_best = MatchResult(
                timestamp=best_time,
                frame_number=int(best_time * self.meta.fps),
                extracted_text=best_text,
                confidence=best_score,
                status="ASR_ONLY_MATCH"
            )

        if best_score >= 60:
            win_start = max(0.0, best_time - ASR_WINDOW_PAD)
            win_end = min(self.meta.duration, best_time + ASR_WINDOW_PAD)
            log.info(
                "ASR match (score=%.0f) at ~%.2fs → window [%.2f, %.2f]",
                best_score, best_time, win_start, win_end,
            )
            return SearchWindow(win_start, win_end)

        log.warning("No ASR match found (best=%.0f). Full-scan fallback.", best_score)
        return SearchWindow(0.0, self.meta.duration)

    # ---- Phase 2 ----
    def phase2_coarse_ocr(self, window: SearchWindow) -> Optional[float]:
        """Sample at 1 fps within the window and OCR each frame."""
        log.info("=== Phase 2: Coarse Sampled OCR (1 fps) ===")
        log.info("Scanning window [%.2f, %.2f] ...", window.start, window.end)

        cap = cv2.VideoCapture(self.meta.video_path)
        if not cap.isOpened():
            log.error("Cannot open video file.")
            return None

        best_score = 0.0
        best_ts = 0.0
        best_text = ""

        ts = window.start
        while ts <= window.end:
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
            ret, frame = cap.read()
            if not ret:
                ts += 1.0 / COARSE_FPS
                continue

            text = self.ocr.extract_text(frame)
            score = fuzz.token_set_ratio(self.target.lower(), text.lower())

            if score > best_score:
                best_score = score
                best_ts = ts
                best_text = text
                log.info("  t=%.2fs  score=%.0f  text='%s'", ts, score, text[:80])

            ts += 1.0 / COARSE_FPS

        cap.release()

        if best_score >= CONFIDENCE_LOW:
            status = "OK" if best_score >= CONFIDENCE_OK else "LOW_CONFIDENCE"
            log.info("Coarse match: score=%.0f (%s) at t=%.2fs", best_score, status, best_ts)
            self.best = MatchResult(best_ts, 0, best_text, best_score, status)
            return best_ts

        log.warning("No coarse OCR match found (best=%.0f).", best_score)
        self.best = MatchResult(0, 0, best_text, best_score, "NOT_FOUND")
        return None

    # ---- Phase 3 ----
    def phase3_refine(self, t_coarse: float) -> float:
        """Multi-pass temporal refinement to find exact first frame."""
        log.info("=== Phase 3: Temporal Refinement ===")

        cap = cv2.VideoCapture(self.meta.video_path)
        if not cap.isOpened():
            log.error("Cannot open video for refinement.")
            return t_coarse

        def scan_range(start: float, end: float, step: float) -> Tuple[float, float, str]:
            best_s, best_t, best_txt = 0.0, t_coarse, ""
            t = start
            while t <= end:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ret, frame = cap.read()
                if not ret:
                    t += step
                    continue
                text = self.ocr.extract_text(frame)
                score = fuzz.token_set_ratio(self.target.lower(), text.lower())
                if score > best_s:
                    best_s, best_t, best_txt = score, t, text
                t += step
            return best_s, best_t, best_txt

        # Pass A: 0.1s granularity in ±1s
        log.info("Pass A: 0.1s steps in [%.2f, %.2f]", t_coarse - 1.0, t_coarse + 1.0)
        s_a, t_a, txt_a = scan_range(
            max(0, t_coarse - 1.0), min(self.meta.duration, t_coarse + 1.0), REFINE_PASS_A
        )
        log.info("  → best t=%.3fs  score=%.0f", t_a, s_a)

        # Pass B: 0.01s granularity in ±0.1s
        log.info("Pass B: 0.01s steps around %.3fs", t_a)
        s_b, t_b, txt_b = scan_range(
            max(0, t_a - 0.1), min(self.meta.duration, t_a + 0.1), REFINE_PASS_B
        )
        log.info("  → best t=%.4fs  score=%.0f", t_b, s_b)

        # Pass C: frame-by-frame in ±0.01s
        if self.fps_refinement:
            frame_step = 1.0 / self.meta.fps if self.meta.fps > 0 else 0.04
            log.info("Pass C: frame-level (%.5fs) around %.4fs", frame_step, t_b)
            s_c, t_c, txt_c = scan_range(
                max(0, t_b - 0.05), min(self.meta.duration, t_b + 0.05), frame_step
            )
            log.info("  → FINAL t=%.5fs  score=%.0f", t_c, s_c)
        else:
            log.info("Pass C: Skipped (Not required for mode='%s')", self.mode)
            frame_step = 0.01
            t_c = t_b

        cap.release()

        # Find the *first* frame in the Pass C neighbourhood that meets threshold
        self._find_first_appearance(t_c, frame_step)

        return self.best.timestamp

    def _find_first_appearance(self, t_center: float, frame_step: float) -> None:
        """Walk backwards from t_center to find the earliest frame with a match."""
        cap = cv2.VideoCapture(self.meta.video_path)
        if not cap.isOpened():
            return

        earliest_t = t_center
        earliest_txt = self.best.extracted_text
        earliest_score = self.best.confidence

        t = t_center
        while t >= max(0, t_center - 1.0):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret:
                break
            text = self.ocr.extract_text(frame)
            score = fuzz.token_set_ratio(self.target.lower(), text.lower())
            if score >= CONFIDENCE_LOW:
                earliest_t = t
                earliest_txt = text
                earliest_score = score
                t -= frame_step
            else:
                break

        cap.release()

        status = "OK" if earliest_score >= CONFIDENCE_OK else "LOW_CONFIDENCE"
        frame_num = int(earliest_t * self.meta.fps)
        self.best = MatchResult(earliest_t, frame_num, earliest_txt, earliest_score, status)
        log.info("First appearance at t=%.5fs  frame=%d  score=%.0f", earliest_t, frame_num, earliest_score)

    # ---- Phase 4 ----
    def phase4_output(self) -> None:
        """Save the matched frame as PNG and write the JSON manifest."""
        log.info("=== Phase 4: Output Generation ===")

        output_dir = self.work_dir
        frame_path = output_dir / OUTPUT_FRAME
        manifest_path = output_dir / OUTPUT_MANIFEST

        if self.best.status == "NOT_FOUND":
            log.warning("No match found. Writing empty manifest.")
            manifest = {
                "timestamp": "00:00:00.000",
                "frame_number": 0,
                "extracted_text": "",
                "confidence_score": 0.0,
                "status": "NOT_FOUND",
            }
            manifest_path.write_text(json.dumps(manifest, indent=2))
            log.info("Manifest written to %s", manifest_path)
            return

        # Extract and save frame
        cap = cv2.VideoCapture(self.meta.video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, self.best.timestamp * 1000)
        ret, frame = cap.read()
        cap.release()

        if ret:
            cv2.imwrite(str(frame_path), frame)
            log.info("Frame saved: %s", frame_path)
        else:
            log.error("Could not read frame at t=%.3fs", self.best.timestamp)

        # Build timestamp string HH:MM:SS.sss
        total_secs = self.best.timestamp
        hrs = int(total_secs // 3600)
        mins = int((total_secs % 3600) // 60)
        secs = total_secs % 60
        ts_str = f"{hrs:02d}:{mins:02d}:{secs:06.3f}"

        manifest = {
            "timestamp": ts_str,
            "frame_number": self.best.frame_number,
            "extracted_text": self.best.extracted_text,
            "confidence_score": round(self.best.confidence, 2),
            "status": self.best.status,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2))
        log.info("Manifest written: %s", manifest_path)
        log.info("Result → %s", json.dumps(manifest, indent=2))

    # ---- Run all phases ----
    def run(self) -> MatchResult:
        """Execute the full pipeline."""
        t0 = time.time()
        log.info("Target dialogue: '%s'", self.target)
        log.info("Video URL: %s", self.url)

        self.phase0_ingest()

        if self.mode == "ocr_only":
            log.info("Mode 'ocr_only' selected. Skipping ASR.")
            window = SearchWindow(0.0, self.meta.duration)
        else:
            window = self.phase1_asr()

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
                # Zoom into a -2.0 to +2.0 second window around the ASR timestamp
                t_coarse = self.asr_best.timestamp
                self.phase3_refine(t_coarse)
            else:
                log.warning("Mode 'asr_ocr': ASR failed. Falling back to full video OCR.")
                t_coarse = self.phase2_coarse_ocr(window)
                if t_coarse is not None:
                    self.phase3_refine(t_coarse)
        else:
            # Fallback legacy logic
            t_coarse = self.phase2_coarse_ocr(window)
            if t_coarse is not None:
                self.phase3_refine(t_coarse)

        self.phase4_output()

        elapsed = time.time() - t0
        log.info("Pipeline completed in %.1fs", elapsed)
        return self.best


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find the exact video frame where a target dialogue appears on-screen.",
    )
    parser.add_argument(
        "--url", type=str, default=DEFAULT_URL,
        help="Video URL to process (default: ok.ru sample).",
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
        "--workdir", type=str, default=".",
        help="Working directory for downloads and outputs.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    detector = DialogueDetector(
        url=args.url,
        target_dialogue=args.target,
        work_dir=args.workdir,
        local_video=args.video,
    )
    detector.run()


if __name__ == "__main__":
    main()
