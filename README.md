# 🎯 Video Dialogue Frame Detector

> Automatically pinpoint the **exact video frame** where a specific line of dialogue appears on-screen, using a multi-modal ASR + OCR pipeline — no VLMs or LLMs required.

## Overview

This tool downloads a video, runs speech recognition to narrow the search window, then applies coarse-to-fine OCR sampling to locate the precise frame containing the target text. It outputs:

- `output_frame.png` — full-resolution screenshot of the matched frame
- `manifest.json` — structured result with timestamp, frame number, extracted text, and confidence

## Prerequisites

| Dependency       | Purpose                                         |
| ---------------- | ----------------------------------------------- |
| **Python 3.10+** | Runtime                                         |
| **FFmpeg**       | Video/audio processing (must be on system PATH) |
| **uv**           | Fast Python package manager                     |

### Install FFmpeg

**Windows (winget):**

```bash
winget install --id Gyan.FFmpeg -e --source winget
```

**Windows (choco):**

```bash
choco install ffmpeg
```

**macOS:**

```bash
brew install ffmpeg
```

**Ubuntu/Debian:**

```bash
sudo apt update && sudo apt install ffmpeg
```

Verify: `ffmpeg -version` and `ffprobe -version`

### Install uv

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Setup

```bash
# 1. Clone the repository
git clone https://github.com/your-username/Quest1.git
cd Quest1

# 2. Create a virtual environment with uv
uv venv

# 3. Activate the environment
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

# 4. Install all dependencies
uv pip install -r requirements.txt
```

## Usage

### Default (built-in target)

```bash
python src/find_dialogue.py
```

This will search for **"My mind rebels at stagnation"** in `https://ok.ru/video/248244667877`.

### Custom target

```bash
python src/find_dialogue.py \
  --url "https://ok.ru/video/248244667877" \
  --target "My mind rebels at stagnation" \
  --workdir ./output \
  --verbose
```

### CLI Arguments

| Flag        | Default                        | Description                           |
| ----------- | ------------------------------ | ------------------------------------- |
| `--url`     | ok.ru sample video             | Video URL (any yt-dlp supported site) |
| `--target`  | "My mind rebels at stagnation" | Dialogue text to find                 |
| `--workdir` | `.`                            | Directory for downloads and outputs   |
| `--verbose` | off                            | Enable DEBUG-level logging            |

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

See [APPROACH.md](APPROACH.md) for the full engineering design document.
