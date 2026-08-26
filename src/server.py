import os
import sys
import json
import time
import uuid
import logging
import shutil
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import urllib.parse

log = logging.getLogger("DialogueServer")
GLOBAL_STATUS = {"node": "none", "msg": "Idle"}

# Ensure the project root is in the python path so 'src' can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.core.orchestrator import DialogueDetector
from src.phases.ingest import phase0_ingest

PORT = 8000
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
ASSETS_DIR = Path(__file__).parent.parent / "assets"
OUTPUT_DIR = Path(__file__).parent.parent / "output"

class DialogueAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def log_message(self, format, *args):
        # Prevent the constant /api/status polling from spamming the console
        if len(args) > 0 and isinstance(args[0], str) and "/api/status" in args[0]:
            return
        super().log_message(format, *args)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/api/frame"):
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            session_id = params.get("id", [""])[0]
            
            if session_id:
                frame_path = OUTPUT_DIR / "outimage" / f"output_frame_{session_id}.png"
            else:
                frame_path = OUTPUT_DIR / "outimage" / "output_frame.png"
                
            if frame_path.exists():
                self.send_response(200)
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                with open(frame_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "Frame not found")
            return
            
        if self.path.startswith("/assets/video/"):
            original_path = self.path
            original_dir = getattr(self, 'directory', str(FRONTEND_DIR))
            
            self.path = "/" + urllib.parse.unquote(original_path.split("/")[-1])
            self.directory = str(ASSETS_DIR / "video")
            try:
                super().do_GET()
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            finally:
                self.path = original_path
                self.directory = original_dir
            return
            
        if self.path == "/api/history":
            history = []
            metadata_dir = OUTPUT_DIR / "output_metadata"
            if metadata_dir.exists():
                for manifest_file in sorted(metadata_dir.glob("manifest_*.json"), key=os.path.getmtime, reverse=True):
                    try:
                        with open(manifest_file, 'r') as f:
                            data = json.load(f)
                            session_id = manifest_file.stem.split('_')[1] if '_' in manifest_file.stem else ""
                            data['session_id'] = session_id
                            history.append(data)
                    except:
                        pass
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"history": history}).encode('utf-8'))
            return

        if self.path == "/api/videos":
            videos = []
            video_dir = ASSETS_DIR / "video"
            if video_dir.exists():
                for file in video_dir.glob("*.mp4"):
                    videos.append(file.name)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"videos": videos}).encode('utf-8'))
            return
            
        if self.path == "/api/status":
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(GLOBAL_STATUS).encode('utf-8'))
            return

        # Serve frontend static files
        try:
            super().do_GET()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            log.warning("Client disconnected before GET response could be sent.")

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            req_body = json.loads(post_data)
        except:
            req_body = {}

        if self.path == '/api/load':
            url = req_body.get('url', '')
            local_video = req_body.get('local_video', '')
            if not url and not local_video:
                self._send_json(400, {"error": "Missing URL or local_video parameter"})
                return
            
            try:
                # We do not delete ASSETS_DIR anymore so it can be used concurrently.
                # Just ensure it exists.
                ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                
                # 2. Run phase 0 to download & probe
                phase0_ingest(url, local_video, ASSETS_DIR)
                
                self._send_json(200, {"status": "success"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == '/api/search':
            url = req_body.get('url', '')
            target = req_body.get('target', '')
            mode = req_body.get('mode', 'asr_only')
            local_video = req_body.get('local_video', '')
            
            if (not url and not local_video) or not target:
                self._send_json(400, {"error": "Missing url, local_video, or target parameter"})
                return
            
            if local_video:
                video_path = ASSETS_DIR / "video" / local_video
                local_video_path_str = str(video_path)
            else:
                # No local video provided, we will let DialogueDetector handle the download
                local_video_path_str = ""

            try:
                t_start = time.time()
                
                def status_cb(node, msg, progress=None):
                    GLOBAL_STATUS["node"] = node
                    GLOBAL_STATUS["msg"] = msg
                    if progress is not None:
                        GLOBAL_STATUS["progress"] = progress
                    else:
                        GLOBAL_STATUS.pop("progress", None)

                detector = DialogueDetector(url=url, target_dialogue=target, mode=mode, local_video=local_video_path_str, work_dir=str(OUTPUT_DIR), assets_dir=str(ASSETS_DIR), status_callback=status_cb)
                
                result = detector.run()
                elapsed = time.time() - t_start
                
                # Safe check if video metadata was ingested
                video_filename = ""
                clip_start_time = 0.0
                if hasattr(detector, "meta") and detector.meta and detector.meta.video_path:
                    video_path_obj = Path(detector.meta.video_path)
                    if video_path_obj.exists():
                        video_filename = video_path_obj.name
                        
                        # Physically cut the video clip from -6 to +6 seconds
                        if result and result.status != "NOT_FOUND" and result.timestamp > 0:
                            import subprocess
                            clip_name = f"clip_{detector.session_id}_{video_filename}"
                            clips_dir = ASSETS_DIR / "video" / "clips"
                            clips_dir.mkdir(parents=True, exist_ok=True)
                            clip_path = clips_dir / clip_name
                            clip_start_time = max(0.0, result.timestamp - 6.0)
                            
                            try:
                                subprocess.run([
                                    "ffmpeg", "-y", "-i", str(video_path_obj), 
                                    "-ss", str(clip_start_time), "-t", "12.0", 
                                    "-c", "copy", str(clip_path)
                                ], capture_output=True, check=True)
                                
                                if clip_path.exists():
                                    video_filename = f"clips/{clip_name}"
                            except Exception as e:
                                print("Error clipping video:", e)
                
                # Return the result and manifest contents
                metadata_dir = OUTPUT_DIR / "output_metadata"
                metadata_dir.mkdir(parents=True, exist_ok=True)
                manifest_path = getattr(detector, 'manifest_path', metadata_dir / f"manifest_{detector.session_id}.json")
                manifest_data = {}
                if manifest_path.exists():
                    with open(manifest_path, 'r') as f:
                        manifest_data = json.load(f)
                    
                    # Inject target_text so history knows what we searched for
                    manifest_data["target_text"] = target
                    manifest_data["mode"] = mode
                    manifest_data["video_file"] = video_filename or local_video_path_str or "video"
                    manifest_data["clip_start_time"] = clip_start_time
                    with open(manifest_path, 'w') as f:
                        json.dump(manifest_data, f, indent=2)
                else:
                    manifest_data = {
                        "timestamp": "00:00:00.000",
                        "frame_number": 0,
                        "extracted_text": "",
                        "confidence_score": 0.0,
                        "status": "NOT_FOUND",
                        "processing_time": round(elapsed, 2),
                        "target_text": target,
                        "mode": mode,
                        "video_file": video_filename or local_video_path_str or "video",
                        "clip_start_time": 0.0
                    }
                
                self._send_json(200, {
                    "status": "success", 
                    "elapsed": elapsed,
                    "session_id": detector.session_id,
                    "result": manifest_data
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json(200, {
                    "status": "success",
                    "elapsed": 0.0,
                    "session_id": "err_" + uuid.uuid4().hex[:8],
                    "result": {
                        "status": "NOT_FOUND",
                        "confidence_score": 0.0,
                        "timestamp": "00:00:00.000",
                        "extracted_text": "",
                        "target_text": target if 'target' in locals() else "",
                        "mode": mode if 'mode' in locals() else "asr_ocr",
                        "video_file": local_video_path_str if 'local_video_path_str' in locals() else "video",
                        "error_detail": str(e)
                    }
                })
    def do_DELETE(self):
        if self.path == '/api/cache':
            try:
                # Clear output directory (processed files)
                if OUTPUT_DIR.exists():
                    for item in OUTPUT_DIR.iterdir():
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                
                # Clear RAM cache
                try:
                    from src.phases.asr_phase import _TRANSCRIPT_CACHE
                    _TRANSCRIPT_CACHE.clear()
                except Exception as e:
                    log.warning(f"Could not clear RAM cache: {e}")
                            
                self._send_json(200, {"status": "success", "msg": "Cache cleared"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "Not found"})

    def _send_json(self, status_code, data):
        try:
            self.send_response(status_code)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            log.warning("Client disconnected before response could be sent.")

if __name__ == '__main__':
    print(f"Starting server on http://localhost:{PORT}")
    httpd = ThreadingHTTPServer(('localhost', PORT), DialogueAPIHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    print("Server stopped.")
