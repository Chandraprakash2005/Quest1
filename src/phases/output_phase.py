import json
import cv2
from pathlib import Path
from src.core.config import log
from src.core.models import VideoMeta, MatchResult

def phase4_output(meta: VideoMeta, best: MatchResult, session_id: str, work_dir: Path, elapsed: float = 0.0) -> None:
    log.info("=== Phase 4: Output Generation ===")

    metadata_dir = work_dir / "output_metadata"
    image_dir = work_dir / "outimage"
    
    metadata_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    
    frame_path = image_dir / f"output_frame_{session_id}.png"
    manifest_path = metadata_dir / f"manifest_{session_id}.json"

    if best.status == "NOT_FOUND":
        log.warning("No match found. Writing fallback frame and empty manifest.")
        cap = cv2.VideoCapture(meta.video_path)
        ret, frame = cap.read()
        cap.release()
        if ret:
            cv2.imwrite(str(frame_path), frame)
        manifest = {
            "timestamp": "00:00:00.000",
            "frame_number": 0,
            "extracted_text": "",
            "confidence_score": 0.0,
            "status": "NOT_FOUND",
            "processing_time": round(elapsed, 2),
            "image_path": str(frame_path.resolve()) if ret else ""
        }
        manifest_path.write_text(json.dumps(manifest, indent=2))
        log.info("Manifest written to %s", manifest_path)
        return

    cap = cv2.VideoCapture(meta.video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, best.timestamp * 1000)
    ret, frame = cap.read()
    cap.release()

    if ret:
        cv2.imwrite(str(frame_path), frame)
        log.info("Frame saved: %s", frame_path)
    else:
        log.error("Could not read frame at t=%.3fs", best.timestamp)

    total_secs = best.timestamp
    hrs = int(total_secs // 3600)
    mins = int((total_secs % 3600) // 60)
    secs = total_secs % 60
    ts_str = f"{hrs:02d}:{mins:02d}:{secs:06.3f}"

    manifest = {
        "timestamp": ts_str,
        "frame_number": best.frame_number,
        "extracted_text": best.extracted_text,
        "confidence_score": round(best.confidence, 2),
        "status": best.status,
        "asd_status": best.asd_status,
        "processing_time": round(elapsed, 2),
        "image_path": str(frame_path.resolve()) if ret else ""
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    log.info("Manifest written: %s", manifest_path)
    log.info("Result → %s", json.dumps(manifest, indent=2))
