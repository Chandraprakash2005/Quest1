# Video Dialogue Frame Detector

> Automatically pinpoint the **exact video frame** where a specific line of dialogue appears on-screen, using a multi-modal ASR + OCR pipeline — no VLMs or LLMs required.

## Overview

This tool downloads a video, runs speech recognition to narrow the search window, then applies coarse-to-fine OCR sampling to locate the precise frame containing the target text. It outputs:

- `output_frame.png` — full-resolution screenshot of the matched frame
- `manifest.json` — structured result with timestamp, frame number, extracted text, and confidence

## 1. What to Install (Setup)

You need to install system dependencies (FFmpeg) and python dependencies to run this app.

**System Requirements:**

- **Python 3.10+**
  **System Dependencies (FFmpeg & uv):**

**Windows (PowerShell):**

```powershell
winget install --id Gyan.FFmpeg -e --source winget
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS (Homebrew):**

```bash
brew install ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Linux (Debian/Ubuntu):**

```bash
sudo apt update && sudo apt install ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Application Setup:**
Choose your operating system below and copy-paste the entire block into your terminal to set up the project in one go:

**Windows (PowerShell):**

```powershell
git clone https://github.com/your-username/Quest1.git
cd Quest1
uv venv
.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
```

**macOS / Linux:**

```bash
git clone https://github.com/your-username/Quest1.git
cd Quest1
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

---

## 2. What to Run (Usage)

To run the whole application, you just need to start the backend server. The Web UI is the primary way to interact with the detector.

**Step 1: Start the server**

```bash
python src/server.py
```

_(Leave this terminal window running)_

**Step 2: Open the Dashboard**
Open your web browser and go to: **http://localhost:8000**

**Step 3: Using the App**

1. **Source:** Choose a local video from the `assets/video` folder or paste a remote URL.
2. **Target Phrase:** Enter the dialogue to search for.
3. **Method:** Select **Voice + On-Screen Text (Best Accuracy)** for the best results.
4. **Run:** Click "Run Pipeline" and watch the live progress until the frame is found!

## Output

```
output_frame.png    ← Full-resolution frame image
manifest.json       ← Structured detection result
```

### Example `manifest.json`

```json
{
  "timestamp": "00:01:23.456",
  "frame_number": 2086,
  "extracted_text": "My mind rebels at stagnation",
  "confidence_score": 94.5,
  "status": "OK"
}
```

### Confidence Status Codes

| Status           | Score Range | Meaning                  |
| ---------------- | ----------- | ------------------------ |
| `OK`             | ≥ 85        | High-confidence match    |
| `LOW_CONFIDENCE` | 70–84       | Partial or fuzzy match   |
| `NOT_FOUND`      | < 70        | Target text not detected |

## Pipeline Phases

1. **Phase 0 — Ingestion:** Downloads video via `yt-dlp`, probes metadata with `ffprobe`, extracts 16 kHz mono audio.
2. **Phase 1 — ASR:** Runs `faster-whisper` on audio and fuzzy-matches the transcript to narrow the search to a ~4s window.
3. **Phase 2 — Coarse OCR:** Samples 1 frame/second within the window and runs PaddleOCR (or EasyOCR) on each frame.
4. **Phase 3 — Refinement:** Multi-pass binary search (0.1s → 0.01s → frame-level) to lock in the first appearance.
5. **Phase 4 — Output:** Saves the frame as PNG and writes the JSON manifest.
   See the accompanying [Approach.pdf](Approach.pdf) for the full engineering design document.
