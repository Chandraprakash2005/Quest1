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
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from rapidfuzz import fuzz

# ── Inject NVIDIA CUDA DLLs into PATH at module-load time (before ctranslate2 / faster_whisper) ──
_venv_dir = Path(sys.executable).parent.parent
_nvidia_base = _venv_dir / "Lib" / "site-packages" / "nvidia"
if _nvidia_base.exists():
    for _pkg_dir in _nvidia_base.iterdir():
        if _pkg_dir.is_dir():
            for _sub in ["bin", "lib"]:
                _dll_path = _pkg_dir / _sub
                if _dll_path.exists():
                    os.environ["PATH"] = str(_dll_path) + os.pathsep + os.environ["PATH"]
                    if hasattr(os, "add_dll_directory"):
                        os.add_dll_directory(str(_dll_path))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_URL = "https://ok.ru/video/248244667877"
DEFAULT_DIALOGUE = "My mind rebels at stagnation"
ASR_WINDOW_PAD = 2.0          # seconds before/after ASR hit
COARSE_FPS = 3.0              # 3 frames per second for coarse scan (catches short subtitles)
CONFIDENCE_OK = 85
CONFIDENCE_LOW = 70
REFINE_PASS_A = 0.1           # seconds granularity
REFINE_PASS_B = 0.01
OUTPUT_FRAME = "output_frame.png"
OUTPUT_MANIFEST = "manifest.json"

# ---------------------------------------------------------------------------
# Suppress noisy PyTorch warnings (pin_memory from EasyOCR internals)
# ---------------------------------------------------------------------------
import warnings
warnings.filterwarnings("ignore", message=".*pin_memory.*")

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
_GPU_LOCK = threading.Lock()  # Serialize GPU access across concurrent requests

def _get_whisper_model(model_size: str = "tiny.en"):
    """Returns a cached Whisper model, preferring GPU."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    
    from faster_whisper import WhisperModel
    try:
        _WHISPER_MODEL = WhisperModel(model_size, device="cuda", compute_type="float16")
        log.info("faster-whisper '%s' loaded on CUDA GPU!", model_size)
    except Exception as e:
        log.warning("GPU load failed (%s). Falling back to CPU.", str(e)[:60])
        _WHISPER_MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _WHISPER_MODEL

_TRANSCRIPT_CACHE = {
    "video_path": "",
    "timestamp": 0,
    "words": [],
    "segments": []
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
        """Return all detected text from an image as a single string.
        Thread-safe: acquires GPU lock to prevent concurrent GPU contention.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        with _GPU_LOCK:
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

    def __init__(self, url: str, target_dialogue: str, work_dir: str = "output", local_video: str = "", mode: str = "asr_only") -> None:
        import re
        import uuid
        self.session_id = uuid.uuid4().hex
        self.url = url
        self.target = re.sub(r'[^\w\s]', ' ', target_dialogue).lower()
        self.mode = mode
        self.work_dir = Path(work_dir).resolve()
        
        # As requested, cap OCR refinement at 0.01s granularity for all OCR modes (avoid 1/fps)
        self.fps_refinement = False
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.local_video = local_video
        
        self.meta = VideoMeta()
        self.ocr = OCREngine()
        self.best: MatchResult = MatchResult()
        self.asr_best: Optional[MatchResult] = None
        self._prev_sub_hash: Optional[int] = None  # for frame deduplication

    @staticmethod
    def _crop_subtitle_region(frame: np.ndarray) -> np.ndarray:
        """Crop the bottom 30% of the frame where subtitles typically appear.
        This reduces OCR input size by ~70% and dramatically speeds up inference.
        """
        h = frame.shape[0]
        top = int(h * 0.70)
        return frame[top:h, :]

    def _is_duplicate_frame(self, sub_region: np.ndarray) -> bool:
        """Check if the subtitle region is visually identical to the previous one.
        Uses a fast perceptual hash to skip redundant OCR calls.
        """
        # Resize to tiny thumbnail and hash
        small = cv2.resize(sub_region, (64, 16), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if len(small.shape) == 3 else small
        h = hash(gray.tobytes())
        if h == self._prev_sub_hash:
            return True
        self._prev_sub_hash = h
        return False
        
    def _clean(self, text: str) -> str:
        """Strips punctuation to extract raw words for comparison."""
        import re
        return re.sub(r'[^\w\s]', ' ', text).lower()


    def _download_with_ytdlp(self) -> Path:
        """Download video — tries direct HTTP extraction first, then yt-dlp.
        Returns the path to the downloaded video file.
        """
        import re
        import requests as req
        video_dir = Path("assets/video")
        video_dir.mkdir(parents=True, exist_ok=True)

        # ── Strategy 1: Direct extraction from ok.ru desktop page ──
        if "ok.ru" in self.url:
            try:
                log.info("Strategy 1: Direct ok.ru page extraction...")
                video_url, title = self._extract_okru_direct_url_and_title()
                if video_url:
                    out_path = video_dir / f"{title}.mp4"
                    if not out_path.exists():
                        self._http_download(video_url, str(out_path))
                    return out_path
            except Exception as exc:
                log.warning("Direct extraction failed: %s", exc)

        # ── Strategy 2: yt-dlp with retries ──
        log.info("Strategy 2: yt-dlp download...")
        import yt_dlp

        # Download with title as filename
        outtmpl = str(video_dir / "%(title)s.%(ext)s")
        
        base_opts = {
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
            "restrictfilenames": True, # avoid weird chars
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
                        info = ydl.extract_info(self.url, download=True)
                        final_filename = ydl.prepare_filename(info)
                        # prepare_filename sometimes gives the pre-merged extension (e.g. .webm)
                        # We force merge to mp4, so let's ensure the path returned has .mp4
                        if not final_filename.endswith('.mp4'):
                            final_filename = str(Path(final_filename).with_suffix('.mp4'))
                        return Path(final_filename)
                except Exception as exc:
                    log.warning("yt-dlp (%s) retry %d failed: %s", fmt, retry + 1, str(exc)[:80])
                    time.sleep(2 ** retry)

        raise RuntimeError(
            "All download strategies failed.\n"
            "  Re-run with: --video path/to/downloaded_video.mp4"
        )

    def _extract_okru_direct_url_and_title(self) -> Tuple[Optional[str], str]:
        """Extract the best direct video URL and title from ok.ru desktop page."""
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

        title_match = re.search(r'<title>(.*?)</title>', html)
        title = title_match.group(1).replace(" | OK.RU", "").strip() if title_match else "video"
        title = re.sub(r'[^\w\s-]', '', title).replace(' ', '_')

        # ok.ru stores metadata in data-options attribute
        match = re.search(r'data-options="([^"]+)"', html)
        if not match:
            return None, title

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
                log.info("Found %s quality stream for '%s'", q, title)
                return url, title

        # Return first available
        first_url = videos[0].get("url", "")
        return (first_url.replace("\\u0026", "&") if first_url else None), title

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

        video_path = None
        
        # Use local video if provided, otherwise download
        if self.local_video:
            import shutil
            local = Path(self.local_video)
            if not local.exists():
                raise FileNotFoundError(f"Local video not found: {self.local_video}")
            video_path = local
            log.info("Using local video: %s", self.local_video)
        else:
            log.info("Downloading video from %s ...", self.url)
            try:
                video_path = self._download_with_ytdlp()
                log.info("Download complete/verified: %s", video_path)
            except Exception as exc:
                log.error(
                    "Download failed: %s\n"
                    "If ok.ru is blocked in your region, download the video manually\n"
                    "and re-run with: --video path/to/video.mp4",
                    exc,
                )
                raise
                
        # Derive matching audio path based on video filename
        audio_path = audio_dir / f"{video_path.stem}.wav"

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
    def _get_sentence_context(self, words: list, match_start_idx: int, match_end_idx: int, max_context: int = 12) -> str:
        """Get the full surrounding sentence context for a matched word span.
        
        Looks outward from the match indices to find sentence boundaries
        (pauses > 0.5s between words) or up to max_context words on each side.
        """
        # Expand left
        left = match_start_idx
        for k in range(match_start_idx - 1, max(match_start_idx - max_context, -1), -1):
            if k < 0:
                break
            gap = words[k + 1]["start"] - words[k]["end"]
            if gap > 0.5:
                break  # sentence boundary
            left = k
        
        # Expand right
        right = match_end_idx
        for k in range(match_end_idx + 1, min(match_end_idx + max_context, len(words))):
            gap = words[k]["start"] - words[k - 1]["end"]
            if gap > 0.5:
                break  # sentence boundary
            right = k
        
        context_words = words[left:right + 1]
        return " ".join([w["word"] for w in context_words]).strip()

    def _exact_word_match(self, target_words: list, transcript_words: list) -> tuple:
        """Find the target words as exact whole words in the transcript.
        
        Returns (score, time, matched_text, match_start_idx, match_end_idx)
        or (0, 0, "", -1, -1) if not found.
        """
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
            
            # Count exact word matches (allowing for trailing 's')
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

    def phase1_asr(self) -> SearchWindow:
        """Run ASR on audio and fuzzy-match the target dialogue."""
        log.info("=== Phase 1: ASR Accelerator ===")

        global _TRANSCRIPT_CACHE
        cache_video = _TRANSCRIPT_CACHE.get("video_path", "")
        cache_fresh = (time.time() - _TRANSCRIPT_CACHE.get("timestamp", 0)) < 600
        
        if cache_video != self.meta.audio_path or not cache_fresh:
            log.info("Transcript cache miss. Running Whisper over entire audio...")
            try:
                model = _get_whisper_model("tiny.en")
                segments_iter, _ = model.transcribe(self.meta.audio_path, language="en", word_timestamps=True)
            except Exception as exc:
                log.warning("GPU inference failed (%s). Falling back to CPU.", str(exc)[:50])
                global _WHISPER_MODEL
                _WHISPER_MODEL = None
                from faster_whisper import WhisperModel
                model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
                _WHISPER_MODEL = model
                try:
                    segments_iter, _ = model.transcribe(self.meta.audio_path, language="en", word_timestamps=True)
                except Exception as exc2:
                    log.warning("Whisper CPU fallback also failed (%s). Falling back to full scan.", str(exc2)[:50])
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
                "video_path": self.meta.audio_path,
                "timestamp": time.time(),
                "words": all_words
            }
        else:
            log.info("Using cached ASR transcript. Skipping Whisper inference!")

        words = _TRANSCRIPT_CACHE["words"]
        target_words = self.target.split()
        n_target_words = len(target_words)
        
        best_score = 0.0
        best_time = 0.0
        best_text = ""

        # ── Strategy 1: Exact whole-word matching (prevents false positives on short inputs) ──
        log.info("ASR Strategy 1: Exact whole-word matching for '%s' (%d words)", self.target, n_target_words)
        exact_score, exact_time, exact_text, m_start, m_end = self._exact_word_match(target_words, words)
        
        if exact_score >= 100:
            # Perfect exact match — get full sentence context
            context_text = self._get_sentence_context(words, m_start, m_end)
            log.info("Exact match found: score=%.0f at t=%.2fs text='%s'", exact_score, exact_time, context_text[:80])
            best_score = exact_score
            best_time = exact_time
            best_text = context_text
        elif n_target_words >= 3:
            # ── Strategy 2: Fuzzy matching only for longer phrases (≥3 words) ──
            log.info("ASR Strategy 2: Fuzzy sliding window (target has %d words)", n_target_words)
            for i in range(len(words)):
                for j in range(i + 1, min(i + n_target_words + 3, len(words) + 1)):
                    window = words[i:j]
                    w_text = " ".join([w["word"] for w in window]).strip()
                    w_score = fuzz.ratio(self.target.lower(), self._clean(w_text).lower())
                    
                    if w_score > best_score:
                        best_score = w_score
                        best_text = self._get_sentence_context(words, i, j - 1)
                        best_time = (window[0]["start"] + window[-1]["end"]) / 2.0
                        
                if best_score >= 85:
                    log.info("Fuzzy match found! Halting search.")
                    break
        else:
            # Short target (1-2 words) — only accept exact matches
            if exact_score >= 50:  # At least half the words matched exactly
                context_text = self._get_sentence_context(words, m_start, m_end) if m_start >= 0 else exact_text
                best_score = exact_score
                best_time = exact_time
                best_text = context_text
                log.info("Partial exact match for short target: score=%.0f at t=%.2fs", exact_score, exact_time)
            else:
                log.info("No exact match for short target '%s' (best_exact=%.0f). Rejecting fuzzy matches to avoid false positives.", self.target, exact_score)

        if best_score > 0:
            self.asr_best = MatchResult(
                timestamp=best_time,
                frame_number=int(best_time * self.meta.fps),
                extracted_text=best_text,
                confidence=best_score,
                status="ASR_ONLY_MATCH"
            )
            log.info("ASR best: score=%.0f  time=%.2fs  text='%s'", best_score, best_time, best_text[:100])

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
        """Sample at 1 fps within the window and OCR each frame.
        Uses subtitle-region cropping and frame deduplication for speed.
        """
        log.info("=== Phase 2: Coarse Sampled OCR (1 fps) ===")
        log.info("Scanning window [%.2f, %.2f] ...", window.start, window.end)

        cap = cv2.VideoCapture(self.meta.video_path)
        if not cap.isOpened():
            log.error("Cannot open video file.")
            return None

        best_score = 0.0
        best_ts = 0.0
        best_text = ""
        self._prev_sub_hash = None  # reset dedup for this scan
        skipped = 0

        ts = window.start
        while ts <= window.end:
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
            ret, frame = cap.read()
            if not ret:
                ts += 1.0 / COARSE_FPS
                continue

            # Crop to subtitle region (bottom 30%) for faster OCR
            sub_region = self._crop_subtitle_region(frame)
            
            # Skip if subtitle region hasn't changed
            if self._is_duplicate_frame(sub_region):
                skipped += 1
                ts += 1.0 / COARSE_FPS
                continue

            text = self.ocr.extract_text(sub_region)
            score = fuzz.token_set_ratio(self._clean(self.target), self._clean(text))

            if score >= CONFIDENCE_LOW:
                # Halt immediately to preserve the EARLIEST acceptable occurrence!
                # If we keep scanning for a higher score, we might skip the first occurrence
                # and lock onto a later occurrence of the same word (e.g., at 4.0s instead of 1.3s).
                best_score = score
                best_ts = ts
                best_text = text
                log.info("  t=%.2fs  score=%.0f  text='%s'", ts, score, text[:80])
                log.info("Target text found! Halting coarse scan early to preserve earliest timestamp.")
                break
                
            elif score > best_score:
                best_score = score
                best_ts = ts
                best_text = text
                log.info("  t=%.2fs  score=%.0f  text='%s'", ts, score, text[:80])

            ts += 1.0 / COARSE_FPS

        cap.release()
        if skipped > 0:
            log.info("Skipped %d duplicate frames (no subtitle change)", skipped)

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
                sub_region = self._crop_subtitle_region(frame)
                text = self.ocr.extract_text(sub_region)
                score = fuzz.token_set_ratio(self._clean(self.target), self._clean(text))
                
                # If we hit an acceptable score, return IMMEDIATELY.
                # This guarantees we get the earliest possible start frame,
                # rather than moving the timestamp forward to a later frame with a higher score.
                if score >= CONFIDENCE_LOW:
                    log.info("    Earliest acceptable frame found: score=%.0f at t=%.3fs", score, t)
                    return score, t, text
                    
                if score > best_s:
                    best_s, best_t, best_txt = score, t, text
                t += step
            return best_s, best_t, best_txt

        if self.mode == "ocr_only":
            # For OCR only, we know the match appeared between t_coarse-1.0 and t_coarse
            window_a_start = max(0, t_coarse - 1.0)
            window_a_end = t_coarse
            
            # We want to do f-f for ocr_only
            self.fps_refinement = True
        else:
            # For ASR+OCR, we look at +/- 2.0 around the audio anchor
            window_a_start = max(0, t_coarse - 2.0)
            window_a_end = min(self.meta.duration, t_coarse + 2.0)
            
        # Pass A: 0.1s granularity
        log.info("Pass A: 0.1s steps in [%.2f, %.2f]", window_a_start, window_a_end)
        s_a, t_a, txt_a = scan_range(window_a_start, window_a_end, REFINE_PASS_A)
        log.info("  → best t=%.3fs  score=%.0f", t_a, s_a)

        if self.mode == "ocr_only":
            window_b_start = max(0, t_a - 0.1)
            window_b_end = t_a
        else:
            window_b_start = max(0, t_a - 0.1)
            window_b_end = min(self.meta.duration, t_a + 0.1)

        # Pass B: 0.01s granularity
        log.info("Pass B: 0.01s steps in [%.2f, %.2f]", window_b_start, window_b_end)
        s_b, t_b, txt_b = scan_range(window_b_start, window_b_end, REFINE_PASS_B)
        log.info("  → best t=%.4fs  score=%.0f", t_b, s_b)

        # Pass C: frame-by-frame
        if self.fps_refinement:
            frame_step = 1.0 / self.meta.fps if self.meta.fps > 0 else 0.04
            
            if self.mode == "ocr_only":
                window_c_start = max(0, t_b - 0.01)
                window_c_end = t_b
            else:
                window_c_start = max(0, t_b - 0.05)
                window_c_end = min(self.meta.duration, t_b + 0.05)
                
            log.info("Pass C: frame-level (%.5fs) in [%.4f, %.4f]", frame_step, window_c_start, window_c_end)
            s_c, t_c, txt_c = scan_range(window_c_start, window_c_end, frame_step)
            log.info("  → FINAL t=%.5fs  score=%.0f", t_c, s_c)
        else:
            log.info("Pass C: Skipped (Not required for mode='%s')", self.mode)
            frame_step = 0.01
            s_c, t_c, txt_c = s_b, t_b, txt_b

        cap.release()

        # Save the best refinement result BEFORE the backward walk
        # so _find_first_appearance has valid fallback values
        best_refine_score = s_c if self.fps_refinement or s_c > 0 else s_b
        best_refine_t = t_c
        best_refine_txt = txt_c if txt_c else txt_b
        if best_refine_score > 0:
            status = "OK" if best_refine_score >= CONFIDENCE_OK else "LOW_CONFIDENCE"
            self.best = MatchResult(best_refine_t, int(best_refine_t * self.meta.fps), best_refine_txt, best_refine_score, status)

        # Find the *first* frame in the Pass C neighbourhood that meets threshold
        self._find_first_appearance(t_c, frame_step)

        return self.best.timestamp

    def _find_first_appearance(self, t_center: float, frame_step: float) -> None:
        """Walk backwards from t_center to find the earliest frame with a match.
        Uses 0.1s steps (max 5 steps) to avoid excessive OCR calls.
        """
        log.info("=== Finding first appearance (walking backwards from t=%.3fs) ===", t_center)
        cap = cv2.VideoCapture(self.meta.video_path)
        if not cap.isOpened():
            return

        earliest_t = t_center
        earliest_txt = self.best.extracted_text
        earliest_score = self.best.confidence

        # Use coarser step for backward walk — 0.1s minimum, max 5 steps back (0.5s)
        back_step = max(frame_step, 0.1)
        max_back = 0.5
        steps = 0

        t = t_center - back_step
        while t >= max(0, t_center - max_back) and steps < 5:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret:
                break
            sub_region = self._crop_subtitle_region(frame)
            text = self.ocr.extract_text(sub_region)
            score = fuzz.token_set_ratio(self._clean(self.target), self._clean(text))
            log.info("  backward t=%.3fs  score=%.0f", t, score)
            if score >= CONFIDENCE_LOW:
                earliest_t = t
                earliest_txt = text
                earliest_score = score
                t -= back_step
                steps += 1
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
        output_dir.mkdir(parents=True, exist_ok=True)
        self.frame_path = output_dir / f"output_frame_{self.session_id}.png"
        self.manifest_path = output_dir / f"manifest_{self.session_id}.json"
        
        frame_path = self.frame_path
        manifest_path = self.manifest_path

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
                
                # Restore the full context text from ASR instead of using the raw OCR subtitle fragment
                if self.best.status != "NOT_FOUND":
                    self.best.extracted_text = self.asr_best.extracted_text
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
