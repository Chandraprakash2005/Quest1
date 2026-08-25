import os
import sys
import json
import time
import logging
import shutil
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import urllib.parse

log = logging.getLogger("DialogueServer")

# Ensure the project root is in the python path so 'src' can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.core.orchestrator import DialogueDetector
from src.phases.ingest import phase0_ingest

PORT = 8000
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
ASSETS_DIR = Path(r"C:\Users\dayan\Documents\Quest1\assets")
OUTPUT_DIR = Path(__file__).parent.parent / "output"

class DialogueAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

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

        # Serve frontend static files
        super().do_GET()

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
                detector = DialogueDetector(url=url, target_dialogue=target, mode=mode, local_video=local_video_path_str, work_dir=str(OUTPUT_DIR))
                
                result = detector.run()
                elapsed = time.time() - t_start
                
                # Check if video was successfully ingested
                if not Path(detector.meta.video_path).exists():
                    self._send_json(400, {"error": "Video download failed or file missing. Try again."})
                    return
                
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
                    with open(manifest_path, 'w') as f:
                        json.dump(manifest_data, f, indent=2)
                
                self._send_json(200, {
                    "status": "success", 
                    "elapsed": elapsed,
                    "session_id": detector.session_id,
                    "result": manifest_data
                })
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
