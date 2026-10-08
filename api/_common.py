import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import newscore  # noqa: E402


def make_handler(fn):
    """fn(days) -> dict 를 JSON으로 응답하는 핸들러 클래스를 만든다."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                days = max(1, min(int(q.get("days", ["7"])[0]), 365))
            except ValueError:
                days = 7
            body = json.dumps(fn(days), ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return H
