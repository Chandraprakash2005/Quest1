"""Test direct download after rate-limit cooldown."""
import time
import json
import re
import requests
import sys

print("Waiting 20s for rate-limit cooldown...")
time.sleep(20)

URL = "https://youtu.be/nth5SnVvcPg"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}

try:
    r = requests.get(URL, headers=headers, timeout=30)
    print(f"Page status: {r.status_code}, size: {len(r.text)} bytes")

    m = re.search(r'data-options="([^"]+)"', r.text)
    if not m:
        print("No data-options found")
        sys.exit(1)

    raw = m.group(1).replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    data = json.loads(raw)
    meta_str = data.get("flashvars", {}).get("metadata", "")

    if not meta_str:
        print("No metadata found in flashvars")
        sys.exit(1)

    meta = json.loads(meta_str)
    videos = meta.get("videos", [])
    print(f"\nFound {len(videos)} video streams:")

    best_url = None
    for v in videos:
        name = v.get("name", "?")
        url = v.get("url", "").replace("\\u0026", "&")
        print(f"  {name}: {url[:100]}...")
        if name == "sd":
            best_url = url
        elif best_url is None:
            best_url = url

    if best_url:
        print(f"\nDownloading best stream...")
        resp = requests.get(best_url, headers=headers, stream=True, timeout=120)
        print(f"Download status: {resp.status_code}")
        total = int(resp.headers.get("content-length", 0))
        print(f"Content-Length: {total} bytes ({total / (1024*1024):.1f} MB)")

        downloaded = 0
        with open("video.mp4", "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    print(f"  {downloaded / (1024*1024):.1f} / {total / (1024*1024):.1f} MB")

        print(f"\nDONE! Saved video.mp4 ({downloaded / (1024*1024):.1f} MB)")
    else:
        print("No video URL found")

except Exception as e:
    print(f"Failed: {e}")
