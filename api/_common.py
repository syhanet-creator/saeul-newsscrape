import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import newscore  # noqa: E402


def respond(h, fn):
    """요청 핸들러 h 에 fn(days) 의 결과를 JSON 으로 응답한다."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    try:
        days = max(1, min(int(q.get("days", ["7"])[0]), 365))
    except ValueError:
        days = 7
    body = json.dumps(fn(days), ensure_ascii=False).encode()
    h.send_response(200)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)
