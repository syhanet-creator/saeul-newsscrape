import os
import sys
from http.server import BaseHTTPRequestHandler

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import send_json  # noqa: E402
import _admin  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _run(self, method):
        n = min(int(self.headers.get("Content-Length") or 0), 4_000_000)
        body = self.rfile.read(n) if n else b""
        status, extra, obj = _admin.handle(method, self.path, self.headers, body)
        # 관리 응답은 절대 캐시하지 않는다. Set-Cookie 를 붙이려고 send_json 대신 직접 보낸다.
        import json
        raw = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex")
        for k, v in extra.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._run("GET")

    def do_POST(self):
        self._run("POST")
