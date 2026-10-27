import os
import sys
import json
import http.server
import socketserver
import urllib.request
import urllib.error
from pathlib import Path

PORT = int(os.environ.get("PORT", 5000))
PUBLIC_DIR = Path(__file__).resolve().parent / "public"
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def is_api(self) -> bool:
        return self.path.startswith("/api/") or self.path.startswith("/auth/") or self.path == "/api"

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        if self.is_api():
            self.proxy_request("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.is_api():
            self.proxy_request("POST")
        else:
            self.send_error(405, "Method Not Allowed")

    def proxy_request(self, method: str):
        target_url = f"{BACKEND_URL}{self.path}"
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        headers = {}
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length"):
                headers[k] = v

        req = urllib.request.Request(target_url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "content-encoding"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ("transfer-encoding", "content-encoding"):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "detail": f"FastAPI backend unreachable at {BACKEND_URL}: {str(e)}"
            }).encode("utf-8"))

def run():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
        print(f"[Unified Dashboard] Running at http://127.0.0.1:{PORT} (Proxying /api -> {BACKEND_URL})")
        httpd.serve_forever()

if __name__ == "__main__":
    run()

