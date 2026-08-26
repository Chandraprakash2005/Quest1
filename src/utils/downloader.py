import time
from pathlib import Path
from src.core.config import log

class VideoDownloader:
    @staticmethod
    def download(url: str, assets_dir: Path, status_callback=None) -> Path:
        video_dir = assets_dir / "video"
        video_dir.mkdir(parents=True, exist_ok=True)
        
        log.info("Downloading video using yt-dlp...")
        import yt_dlp

        outtmpl = str(video_dir / "%(title)s.%(ext)s")
        base_opts = {
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
            "restrictfilenames": True,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 60,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            },
            "cookiesfrombrowser": ("chrome",),
            "quiet": True,
            "no_warnings": True,
        }
        
        def yt_progress_hook(d):
            if d['status'] == 'downloading' and status_callback:
                p_str = d.get('_percent_str', '0.0%').strip()
                import re
                # Clean ANSI escape sequences and % sign
                p_clean = re.sub(r'\x1b\[[0-9;]*m', '', p_str).replace('%', '').strip()
                try:
                    pct = float(p_clean)
                    status_callback("node-media", f"Downloading video... {pct:.1f}%", pct)
                except ValueError:
                    pass

        base_opts["progress_hooks"] = [yt_progress_hook]

        formats = [
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "best"
        ]

        for fmt in formats:
            try:
                opts = {**base_opts, "format": fmt}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    final_filename = ydl.prepare_filename(info)
                    if not final_filename.endswith('.mp4'):
                        final_filename = str(Path(final_filename).with_suffix('.mp4'))
                    return Path(final_filename)
            except yt_dlp.utils.DownloadError as e:
                log.warning("Download failed for format '%s': %s", fmt, str(e))
                time.sleep(2)
            except Exception as e:
                log.warning("Unexpected error during download: %s", str(e))
                
        raise RuntimeError(
            f"Failed to download video from {url}.\\n"
            "The video might be private, blocked in your region, or unsupported.\\n"
            "If you have the file locally, run with: --video path/to/video.mp4"
        )
