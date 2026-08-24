# Video Dialogue Detection Pipeline Architecture

This document outlines the engineering decisions and architecture for the Multi-Modal Coarse-to-Fine Video Dialogue Detector.

## 1. How the Solution Determines Where to Look
To prevent the catastrophic compute costs of running OCR on every single frame of a multi-minute video, the pipeline utilizes an **ASR Audio-Anchoring Hypothesis**. 
- First, the system extracts the audio track and passes it through `faster-whisper`, a highly optimized Speech-to-Text model.
- Because `faster-whisper` is configured with `word_timestamps=True`, it generates exact sub-second timings for every spoken word.
- A sliding-window algorithm scans these word timestamps and uses `rapidfuzz` to find the exact moment the target dialogue is spoken.
- **The Shortcut:** If the dialogue is spoken loudly and clearly (Confidence >= 60), the pipeline instantly outputs this frame and short-circuits, completing the search in seconds!
- **The Fallback:** If the dialogue is a *silent on-screen text* (ASR finds nothing), it falls back to scanning the entire video visually. 

## 2. How it Determines the Relevant Frame
When ASR fails to find the dialogue (meaning the text is silent), the system must search the video visually. It does this via a **Coarse-to-Fine Temporal Binary Search** to remain incredibly fast:
1. **Coarse Scan:** It samples the video at just **1 frame per second (1 fps)**. This allows it to blaze through a 3-minute video in just 180 frames rather than 5,400 frames. 
2. **Refinement Pass A (0.1s):** Once the 1 fps scan finds a rough match, the pipeline zooms into a 2-second window around that match and scans every 0.1 seconds.
3. **Refinement Pass B (0.01s):** It zooms in further, scanning every 0.01 seconds around the new best match.
4. **Refinement Pass C (Frame-Level):** It steps exactly `1/fps` to lock onto the precise, exact first frame the text appeared.

## 3. How it Extracts the Text
Visual text extraction is handled entirely locally using **EasyOCR** (with PaddleOCR compatibility built-in for non-Windows environments). 
- Before being passed to the Neural Network, `opencv-python` pre-processes the frame by converting it to Grayscale (`cv2.COLOR_BGR2GRAY`). This significantly speeds up OCR inference and reduces memory overhead by stripping unnecessary RGB channels.
- To prevent massive server startup delays, the PyTorch EasyOCR reader is **cached globally in RAM**, allowing instantaneous inference across multiple requests.

## 4. How Ambiguous Results are Handled
Because OCR frequently hallucinates characters or misses punctuation (e.g., reading "I'll" as "Ill"), strict string matching fails. Instead, the pipeline uses **Fuzzy Logic** (`rapidfuzz.token_set_ratio`).
Results are categorized into three transition states:
- **OK (Score >= 85):** A highly confident match. The search immediately halts and accepts this timestamp.
- **LOW_CONFIDENCE (Score 70-84):** An ambiguous match. The search logs this timestamp but continues scanning the remaining window just in case a better (OK) match exists later. If no better match is found, it accepts the low confidence match.
- **NOT_FOUND (Score < 70):** The text is considered non-existent in this frame.

## 5. Architectural Constraints (No VLMs)
**Vision-Language Models (VLMs) and Large Language Models (LLMs) were deliberately avoided in this architecture.** 
While VLMs (like GPT-4V or LLaVA) are powerful, they are extremely slow, incredibly expensive at scale, and difficult to run locally on standard consumer hardware. By using a specialized, deterministic ASR + OCR pipeline, this solution processes entire videos locally on a CPU/GPU in seconds at zero cost.
