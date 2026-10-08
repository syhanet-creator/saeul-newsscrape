import json
import urllib.parse


def parse_query(path):
    """?days=7&kw=한수원,새울본부&fast=1 -> (days, kws|None, fast)"""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    try:
        days = max(1, min(int(q.get("days", ["7"])[0]), 365))
    except ValueError:
        days = 7
    kws = [k.strip()[:30] for k in q.get("kw", [""])[0].split(",") if k.strip()][:8]
    return days, (kws or None), q.get("fast", ["0"])[0] == "1"


def respond(h, fn):
    """요청 핸들러 h 에 fn(days, kws, fast) 의 결과를 JSON 으로 응답한다."""
    days, kws, fast = parse_query(h.path)
    body = json.dumps(fn(days, kws, fast), ensure_ascii=False).encode()
    h.send_response(200)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)
