# Quest1
## Multimodal Dialogue Localization
**Dialogue Localization System - Final System Architecture**

---

## 1. Current Approach

The current system uses a multimodal dialogue localization architecture consisting of three complementary pipelines:

1. **ASR Pipeline** – identifies spoken dialogue from the audio.
2. **OCR Pipeline** – identifies visually displayed dialogue or text from video frames.
3. **ASR–OCR Pipeline** – combines audio-based temporal localization with visual verification and temporal refinement.

The final system is designed around the principle of using the least expensive reliable method first and applying additional processing only when required.

The overall architecture is:

```text
Video → [ ASR | OCR | ASR + OCR ] → Target Localization → Temporal Refinement → Exact Frame
```

### 1.1 ASR Pipeline

The ASR pipeline is responsible for locating dialogue that is spoken in the video.

The final ASR implementation uses a hybrid combination of two Faster-Whisper models:
`small.en + tiny.en`

**Processing flow:**
1. **Audio** (Input video/audio track)
2. **`small.en`** (Primary ASR)
3. **Gap Detection** (Gap > 5s?)
   - *No Gap:* Proceed to Combined Output
   - *Gap > 5s:* **`tiny.en`** (Gap Recovery ASR)
4. **Combined Output** (Merged word-level timestamps)
5. **RAM Cache & Persistent Cache** (For fast access and reuse)
6. **ASD Detection** (On-Screen / Off-Screen Classification)
7. **Final Output** (Dialogue + Timestamps + Classification)

The `small.en` model acts as the primary transcription engine and generates a word-level transcript containing temporal information. The primary model was selected to provide a balance between transcription quality and processing speed.

#### 1.1.1 Gap-Based Secondary ASR

After the primary transcription is generated, the word-level timeline is examined for large temporal gaps.

The current trigger is: **Δt > 5 seconds**

A gap greater than five seconds is treated as a candidate region where the primary ASR may have failed to recognize dialogue. Only these regions are reprocessed using `tiny.en`. Therefore, `tiny.en` is not applied to the complete audio.

#### 1.1.2 ASR Target Matching

The target dialogue is searched within the resulting transcript using a hierarchical matching strategy:
`Exact → Sequential Partial → Fuzzy`

Exact matching is attempted first. If the complete target is not found, sequential partial matching is considered. Fuzzy matching is then used to handle transcription variations.

### 1.2 OCR Pipeline

The OCR pipeline is responsible for locating dialogue or text that is visually displayed in the video.

**Processing flow:**
`Video → Frame Sampling → Frame Preprocessing → OCR Recognition → Target Text Matching → Temporal Refinement → Exact Frame`

The OCR pipeline does not rely on the audio transcript. It can therefore be used when the target text is visually present but cannot be reliably located through ASR.

The OCR search follows a coarse-to-fine strategy:
`Coarse Search (Wide Time Range) → Candidate Region (Reduced Interval) → Fine Search (Smaller Interval) → Exact Frame (Final Location)`

#### 1.2.1 OCR Processing Model
The OCR implementation provides the visual text recognition stage of the pipeline. The main optimization is to reduce the number of frames and image regions that require OCR inference.

### 1.3 ASR–OCR Integrated Pipeline

The ASR–OCR pipeline combines the two modalities. ASR is used to obtain an efficient temporal estimate, while OCR is used to verify or refine the visual location.

**Processing flow:**
`Video → Hybrid ASR (Small + Tiny) → Target Timestamp → Localized OCR (Temporal Window) → Temporal Refinement (Coarse → Fine) → Exact Frame`

When the target dialogue is successfully identified by ASR, the resulting timestamp is used to restrict the OCR search:
`t_ASR → [t_ASR - Δ, t_ASR + Δ] → OCR`

If ASR cannot reliably identify the target, the system can fall back to the OCR-only pipeline.

### 1.4 Temporal Refinement

All three processing paths ultimately use temporal refinement when a precise frame location is required. The temporal search progresses from a coarse interval to a fine interval:
`1.0s → 0.1s → 0.01s → Frame Level`

The timestamp is converted to an explicit frame index using: `F = ⌊t × FPS⌋`

### 1.5 Optimizations Applied to the Final Approach

#### 1.5.1 ASR Optimizations
- **Hybrid ASR:** `small.en` is used for the primary transcription and `tiny.en` is used only for large gaps.
- **Selective Reprocessing:** The secondary model is not run over the complete audio.
- **Word-Level Timestamps:** Retained for accurate dialogue localization.
- **Hierarchical Matching:** Exact, sequential partial, and fuzzy matching are attempted in order.

#### 1.5.2 OCR Optimizations
- Subtitle-region cropping.
- Blank-frame filtering.
- Resolution scaling.
- Visual frame deduplication.
- Controlled OCR worker concurrency.
- GPU synchronization.

#### 1.5.3 ASR–OCR Optimizations
- ASR-guided temporal localization.
- Localized OCR windows.
- OCR fallback only when required.
- Coarse-to-fine temporal refinement.
- Reuse of previously processed ASR/OCR information.

### 1.6 Models Used in the Final System

| Pipeline | Model | Role |
| :--- | :--- | :--- |
| ASR | `small.en` | Primary full-audio transcription. |
| ASR | `tiny.en` | Selective reprocessing of regions with gaps greater than five seconds. |
| OCR | OCR engine | Recognition of visually displayed text in selected video frames. |
| ASR–OCR | Hybrid ASR + OCR | Combines spoken-dialogue localization with visual verification and temporal refinement. |

### 1.7 Final Pipeline Architecture
The system receives a video and target dialogue and selects an ASR, OCR, or integrated ASR–OCR processing pipeline. The pipelines use caching systems to avoid redundant processing, integrate Active Speaker Detection (ASD) for on-screen/off-screen classification, and converge into a single final output.

---

## 2. Approaches Attempted

The ASR component was developed through a series of model experiments:
`tiny.en → base.en → small.en → medium.en → small.en + tiny.en`

### 2.1 Approach 1: Faster-Whisper Tiny
- **Advantage:** Very Fast ASR.
- **Limitation:** Lower Word-Level Accuracy. Produced phonetically similar or incorrect words.

### 2.2 Approach 2: Faster-Whisper Base
- **Advantage:** Fast + More Accurate.
- **Limitation:** Still missed words when dialogue was mixed with strong background music.

### 2.3 Approach 3: Faster-Whisper Small
- **Advantage:** Fast + High Accuracy.
- **Limitation:** Still missed portions of dialogue when speech was heavily masked by background music (failures were concentrated in particular regions).

### 2.4 Approach 4: Faster-Whisper Medium
- **Advantage:** Higher Accuracy and robustness.
- **Limitation:** Too Slow. The larger model introduced significantly higher inference cost.

### 2.5 Approach 5: Hybrid Small + Tiny ASR (Final)
Instead of running a large model over the complete video, the system uses `small.en` as the primary model and selectively uses `tiny.en` to recover potentially missed regions.

### 2.6 Final Selection Rationale
The final architecture avoids the two extreme choices (Tiny: Too Little Accuracy, Medium: Too Much Processing Time) by using **Small for Speed + Accuracy** and **Tiny for Selective Recovery**.

---

## 3. System Limitations

### 3.1 ASR Limitations
- **Tiny Model:** Severe Background Noise Drop-off and Low Vocabulary. (Partially Solved)
- **Small Model:** Moderate noise interference and punctuation inconsistencies. Struggles with heavy cinematic scores. (Unsolved)
- **Medium Model:** Compute Heavy and Over-Sensitivity. Requires ~5 GB VRAM and heavy GPU compute. (Unsolved)

### 3.2 OCR Limitations
- **Character Hallucinations and Missed Punctuation:** OCR frequently hallucinates or merges characters. (Solved via RapidFuzz string matching thresholds)

### 3.3 Video Processing and Frame Extraction
- **OpenCV Frame Seeking Inconsistencies:** Timestamp-based seeking in compressed video formats is occasionally inaccurate. (Solved by transitioning to frame-based seeking)

### 3.4 Temporal Refinement Limitations
- **Hard Capped Granularity:** Temporal refinement is capped at 0.01s granularity to prevent infinite loops. (Solved via hardcoded limits)

### 3.5 Fuzzy Matching False Positives
- **Sliding window ambiguity:** Small target phrases matched against a sliding window can trigger false positives on similar-sounding text. (Partially Solved using strict confidence scores)

---

## 4. Optimizations

### 4.1 Implemented Optimizations
- **ASR Audio-Anchoring Hypothesis (Early Halting):** Extracts audio and uses ASR with word timestamps. If dialogue is found, it short-circuits and bypasses OCR entirely.
- **Coarse-to-Fine Temporal Binary Search:** Scans a 3-minute video in ~180 frames instead of 5400 frames by progressively zooming in (1 FPS → 0.1s → 0.01s → frame-level).
- **Grayscale and Blank Frame Binarization:** Converts frames to grayscale and skips blank frames before inference to speed up OCR.
- **Persistent Transcript Caching & RAM Caching:** Caches the flat word-level ASR transcript locally and in-memory. Subsequent query times drop to <1 second.

---

## 5. Performance Optimization and Bottleneck Analysis

### 5.1 Component-Level Performance Analysis
- **ASR:** Processed via persistent JSON caching after a 2-4 second cold start.
- **Video and OCR:** Capped heavily by Coarse-to-Fine search algorithm (<200 invocations on average).
- **Matching & Refinement:** RapidFuzz is highly optimized in C++, and temporal refinement increases logarithmically.
- **I/O and Disk Operations:** Heavy disk I/O during hybrid gap-cropping is currently a primary pipeline bottleneck.

### 5.2 Performance Bottleneck Analysis
**Primary Bottleneck: Hybrid ASR FFmpeg Cropping**
Invoking `ffmpeg` via subprocess for every >5.0s gap incurs OS-level process spawning overhead and disk write penalties.

### 5.3 Limitations of the Hybrid Approach
- Additional Model-Loading Overhead (VRAM).
- Segment Boundary Problems (hard cropping might cut off spoken words).
- Worst-Case Runtime (sparse interviews with many gaps cause dozens of FFmpeg processes).

### 5.4 Future Optimization Roadmap
- **High Priority:** Replace FFmpeg subprocess calls with direct PyTorch/NumPy tensor slicing to eliminate I/O overhead in Hybrid ASR.
- **Medium Priority:** Integrate `PyAV` (FFmpeg bindings) for exact keyframe-aware seeking.
- **Dynamic Model Loading & VRAM Sharing:** Implement a VRAM manager that unloads Whisper before loading EasyOCR if the VRAM ceiling is reached.
- **Low Priority:** Dynamic temporal refinement cap based on source video framerate (e.g., 1/fps).
