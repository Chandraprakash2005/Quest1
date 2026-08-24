import os
import sys
import json
import time
import shutil
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

# Ensure src is in the python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_dialogue import DialogueDetector

PORT = 8000
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
ASSETS_DIR = Path(__file__).parent.parent / "assets"

class DialogueAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/frame"):
            frame_path = Path("output_frame.png")
            if frame_path.exists():
                self.send_response(200)
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                with open(frame_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "Frame not found")
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
            if not url:
                self._send_json(400, {"error": "No URL provided"})
                return
            
            try:
                # 1. Delete old assets
                if ASSETS_DIR.exists():
                    shutil.rmtree(ASSETS_DIR)
                ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                
                # 2. Run phase 0 to download & probe
                detector = DialogueDetector(url=url, target_dialogue="")
                detector.phase0_ingest()
                
                self._send_json(200, {"status": "success"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif self.path == '/api/search':
            target = req_body.get('target', '')
            url = req_body.get('url', '')
            mode = req_body.get('mode', 'asr_only')
            
            if not target:
                self._send_json(400, {"error": "No target provided"})
                return
            
            # If a new URL is provided, download it first!
            if url:
                if ASSETS_DIR.exists():
                    shutil.rmtree(ASSETS_DIR)
                ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                
                detector = DialogueDetector(url=url, target_dialogue="", mode=mode)
                detector.phase0_ingest()

            video_path = ASSETS_DIR / "video" / "video.mp4"
            if not video_path.exists():
                self._send_json(400, {"error": "No video cached. Please provide a URL."})
                return
                
            try:
                t0 = time.time()
                detector = DialogueDetector(
                    url="", 
                    target_dialogue=target, 
                    local_video=str(video_path),
                    mode=mode
                )
                result = detector.run()
                elapsed = time.time() - t0
                
                # Return the result and manifest contents
                manifest_path = Path("manifest.json")
                manifest_data = {}
                if manifest_path.exists():
                    with open(manifest_path, 'r') as f:
                        manifest_data = json.load(f)
                
                self._send_json(200, {
                    "status": "success", 
                    "elapsed": elapsed,
                    "result": manifest_data
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "Not found"})

    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

if __name__ == '__main__':
    print(f"Starting server on http://localhost:{PORT}")
    httpd = HTTPServer(('localhost', PORT), DialogueAPIHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    print("Server stopped.")
