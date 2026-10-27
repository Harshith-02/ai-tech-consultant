import os
import sys
import json
import argparse
import http.server
import socketserver
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"
if not PUBLIC_DIR.exists():
    PUBLIC_DIR = BASE_DIR / "dashboard" / "public"

DEFAULT_BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")

class DevServerProxyHandler(http.server.SimpleHTTPRequestHandler):
    """
    Local development HTTP server with reverse-proxy routing for API calls.
    Proxies all /api/* and /auth/* requests to the FastAPI backend on port 8000.
    Serves static assets (HTML, CSS, JS) from the public/ directory.
    Safely returns JSON error messages on proxy failures to avoid HTML parse errors.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def is_api_request(self) -> bool:
        return self.path.startswith("/api/") or self.path.startswith("/auth/") or self.path == "/api"

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()

    def do_GET(self):
        if self.is_api_request():
            self.proxy_request("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.is_api_request():
            self.proxy_request("POST")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_PUT(self):
        if self.is_api_request():
            self.proxy_request("PUT")
        else:
            self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        if self.is_api_request():
            self.proxy_request("DELETE")
        else:
            self.send_error(405, "Method Not Allowed")

    BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")

    def proxy_request(self, method: str):
        target_url = f"{self.BACKEND_URL}{self.path}"
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
            err_json = json.dumps({
                "detail": f"FastAPI backend unreachable at {self.BACKEND_URL}. Please verify it is running: {str(e)}"
            })
            self.wfile.write(err_json.encode("utf-8"))

def run():
    parser = argparse.ArgumentParser(description="AI Tech Consultant Local Dev Server with API Proxy")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 3000)), help="Port to listen on (default: 3000)")
    parser.add_argument("--backend", type=str, default="http://127.0.0.1:8000", help="Backend URL (default: http://127.0.0.1:8000)")
    args = parser.parse_args()

    DevServerProxyHandler.BACKEND_URL = args.backend

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", args.port), DevServerProxyHandler) as httpd:
        print(f"=====================================================")
        print(f"AI Tech Consultant Local Frontend Dev Server")
        print(f"Frontend URL : http://127.0.0.1:{args.port}")
        print(f"API Proxying : /api/* -> {args.backend}")
        print(f"Serving From : {PUBLIC_DIR}")
        print(f"=====================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDev server stopped.")

if __name__ == "__main__":
    run()
