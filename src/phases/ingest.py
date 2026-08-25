import json
import subprocess
from pathlib import Path
from src.core.config import log
from src.core.models import VideoMeta
from src.utils.downloader import VideoDownloader

def phase0_ingest(url: str, local_video: str, assets_dir: Path) -> VideoMeta:
    log.info("=== Phase 0: Ingestion & Probing ===")
    video_dir = assets_dir / "video"
    audio_dir = assets_dir / "audio"
    video_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    video_path = None
    if local_video:
        local = Path(local_video)
        if not local.exists():
            raise FileNotFoundError(f"Local video not found: {local_video}")
        video_path = local
        log.info("Using local video: %s", local_video)
    else:
        log.info("Downloading video from %s ...", url)
        try:
            video_path = VideoDownloader.download(url, assets_dir)
            log.info("Download complete/verified: %s", video_path)
        except Exception as exc:
            log.error("Download failed: %s", exc)
            raise
            
    audio_path = audio_dir / f"{video_path.stem}.wav"

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

    meta = VideoMeta()
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            fps_str = stream.get("r_frame_rate", "25/1")
            num, den = fps_str.split("/")
            meta.fps = float(num) / float(den) if float(den) != 0 else 25.0
            meta.width = int(stream.get("width", 0))
            meta.height = int(stream.get("height", 0))
            break

    meta.duration = float(info.get("format", {}).get("duration", 0))
    meta.video_path = str(video_path)
    log.info(
        "Metadata — fps=%.2f  duration=%.2fs  resolution=%dx%d",
        meta.fps, meta.duration, meta.width, meta.height,
    )

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
    meta.audio_path = str(audio_path)
    log.info("Audio ready: %s", audio_path)
    return meta
