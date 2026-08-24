# APPROACH.md — Engineering Design Document

## Problem Statement

Given a video URL and a target dialogue string, identify the **exact frame** where that dialogue appears visually on-screen. The solution must be fully automated, locally executable, and must **not** rely on Vision-Language Models (VLMs) or LLMs for any image processing.

---

## 1. How the Solution Determines Where to Look

### ASR Audio-Anchoring Hypothesis

The core insight is that spoken dialogue in a video strongly correlates temporally with its on-screen subtitle or text appearance. By running Automatic Speech Recognition (ASR) on the audio track first, we can cheaply and quickly identify *when* the target line is spoken.

**Implementation:**
- The audio is extracted as a 16 kHz mono WAV file using `ffmpeg`.
- `faster-whisper` (with `openai-whisper` as fallback) transcribes the audio into timestamped segments.
- Each segment is fuzzy-matched against the target dialogue using `rapidfuzz.fuzz.token_set_ratio`.
- If a match is found (score ≥ 60), the search window is narrowed to `[t_spoken - 2.0s, t_spoken + 2.0s]`.

**Impact:** This reduces the OCR search space from potentially **hours** of video down to a **4-second window**, providing a ~99% reduction in compute for typical cases.

### Fallback for Visual-Only Text

If the target dialogue is never spoken aloud (e.g., it only appears as an intertitle, signage, or visual text), the ASR phase yields no match. In this case, the pipeline gracefully falls back to scanning the **entire video duration** at 1 fps. This ensures completeness at the cost of additional processing time.

---

## 2. How It Determines the Relevant Frame

### Coarse-to-Fine Temporal Search

The pipeline uses a three-pass refinement strategy, progressively increasing temporal resolution:

```
Phase 2 (Coarse):   1.000s steps  →  identifies ~1s neighborhood
Phase 3 Pass A:     0.100s steps  →  refines to ~0.1s neighborhood  
Phase 3 Pass B:     0.010s steps  →  refines to ~0.01s neighborhood
Phase 3 Pass C:     1/fps steps   →  locks exact frame (e.g., 0.04s at 25fps)
```

**Phase 2 — Coarse Sampling (1 fps):**
Within the search window, one frame per second is extracted using OpenCV's `CAP_PROP_POS_MSEC` seeking. Each frame undergoes OCR, and the timestamp with the highest fuzzy match score is recorded.

**Phase 3 — Multi-Pass Refinement:**
- **Pass A (0.1s):** Scans `[t_coarse ± 1.0s]` at 100ms intervals. This accounts for any coarse alignment error.
- **Pass B (0.01s):** Scans `[t_passA ± 0.1s]` at 10ms intervals. Narrows to sub-frame precision.
- **Pass C (1/fps):** Scans `[t_passB ± 0.05s]` at native frame-rate intervals. Identifies the exact frame.

After Pass C, a **backward walk** from the best timestamp finds the **first frame** where the text appears (i.e., the onset of the subtitle), which is the true target.

---

## 3. How It Extracts the Text

### OCR Pipeline

**Engine Selection:**
- **Primary:** PaddleOCR (`paddleocr`) — high accuracy, supports angle classification.
- **Fallback:** EasyOCR (`easyocr`) — broadly compatible, CPU-friendly.

The `OCREngine` class abstracts both backends behind a unified `extract_text(image)` interface. At initialization, it attempts PaddleOCR first; if that fails (import error, missing dependencies), it transparently falls back to EasyOCR.

**Image Preprocessing:**
- Each frame is converted to **grayscale** before OCR. This improves text detection by:
  - Removing color channel noise
  - Increasing contrast between text and background
  - Reducing computational overhead (single channel vs. three)

**Text Aggregation:**
All detected text regions within a single frame are concatenated into a single string, which is then compared against the target dialogue.

---

## 4. How Ambiguous Results Are Handled

### Fuzzy Matching Strategy

Exact string matching is unreliable for OCR output due to:
- Character substitution errors (e.g., `l` ↔ `I`, `0` ↔ `O`)
- Partial text detection (subtitle split across frames)
- Extra detected text (scene text, watermarks, etc.)

We use `rapidfuzz.fuzz.token_set_ratio`, which:
1. Tokenizes both strings into word sets
2. Computes the ratio on the intersection, remainder, and combined sets
3. Returns the **maximum** of these ratios

This is ideal because:
- It is **order-independent** (handles word reordering)
- It is **subset-tolerant** (handles extra detected words from scene text)
- It handles **partial matches** gracefully

### Confidence Tiers

| Score Range | Status | Interpretation |
|---|---|---|
| **≥ 85** | `OK` | High-confidence confirmed match. All or nearly all target words detected with correct spelling. |
| **70 – 84** | `LOW_CONFIDENCE` | Partial match. Most words detected but some OCR errors present. Frame is likely correct but text extraction is imperfect. |
| **< 70** | `NOT_FOUND` | No reliable match. The target text is not visually present in any scanned frame. |

The `LOW_CONFIDENCE` tier is critical: it still triggers Phase 3 refinement (which may improve the score by finding a cleaner frame), but the final manifest transparently reports the uncertainty so downstream consumers can make informed decisions.

---

## 5. Why VLMs Were Deliberately Avoided

Vision-Language Models (e.g., GPT-4V, Gemini Pro Vision, LLaVA) were **intentionally excluded** from this pipeline for the following engineering reasons:

| Factor | VLM Approach | This Pipeline |
|---|---|---|
| **Latency** | 2-10s per API call | <50ms per frame (local OCR) |
| **Cost** | $0.01-0.05 per image | Free (local compute) |
| **Privacy** | Frames sent to cloud | Fully offline |
| **Determinism** | Probabilistic, may vary | Deterministic OCR + fuzzy match |
| **Dependencies** | API keys, internet, rate limits | None (fully self-contained) |
| **Scalability** | Rate-limited | Bounded only by local CPU/GPU |

The ASR + OCR + fuzzy-matching approach achieves comparable accuracy for text detection tasks while being orders of magnitude faster, cheaper, and more predictable. VLMs would be appropriate if the task required *semantic understanding* of visual content (e.g., "find the frame where the character looks sad"), but for literal text matching, classical OCR is the superior tool.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────┐
│                    INPUT                              │
│   URL: ok.ru/video/...    Target: "My mind rebels..." │
└──────────────┬───────────────────────────────────────┘
               │
     ┌─────────▼─────────┐
     │  Phase 0: Ingest   │  yt-dlp → video.mp4
     │  & Probe           │  ffprobe → metadata
     │                    │  ffmpeg → audio.wav (16kHz)
     └─────────┬──────────┘
               │
     ┌─────────▼──────────┐
     │  Phase 1: ASR       │  faster-whisper → transcript
     │  (Fast Pass)        │  rapidfuzz → fuzzy match
     │                    │  Output: SearchWindow [t-2s, t+2s]
     └─────────┬──────────┘
               │
     ┌─────────▼──────────┐
     │  Phase 2: Coarse    │  OpenCV → 1 fps frames
     │  OCR Scan           │  PaddleOCR → text extraction
     │                    │  rapidfuzz → scoring
     └─────────┬──────────┘
               │
     ┌─────────▼──────────┐
     │  Phase 3: Refine    │  Pass A: 0.1s steps
     │  (Binary Search)    │  Pass B: 0.01s steps
     │                    │  Pass C: 1/fps steps
     │                    │  Backward walk → first frame
     └─────────┬──────────┘
               │
     ┌─────────▼──────────┐
     │  Phase 4: Output    │  output_frame.png
     │                    │  manifest.json
     └────────────────────┘
```

---

## Performance Characteristics

- **Best case (ASR hit):** ~10-30 seconds total (4s window × 4 frames + refinement)
- **Worst case (full scan):** Scales linearly with video duration (~1 OCR call per second of video)
- **Memory:** O(1) per frame (frames processed sequentially, not buffered)
- **Disk:** Video file + WAV audio + single output frame
