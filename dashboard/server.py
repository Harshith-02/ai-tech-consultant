import os
import http.server
import socketserver
from pathlib import Path

PORT = 5000
PUBLIC_DIR = Path(__file__).resolve().parent / "public"

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

def run():
    os.chdir(str(PUBLIC_DIR))
    with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
        print(f"[Unified Dashboard] Running at http://127.0.0.1:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run()
