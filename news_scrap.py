"""한수원/새울본부 뉴스 스크랩 앱 - 로컬 실행용.
실행: python news_scrap.py  (브라우저가 자동으로 열립니다)
주간 AI 요약을 쓰려면 환경변수 ANTHROPIC_API_KEY 가 필요합니다.
Vercel 배포 시에는 public/index.html + api/*.py 가 사용됩니다.
"""
import json
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import newscore
from api._common import parse_query

PORT = 8765
INDEX = (Path(__file__).parent / "public" / "index.html").read_bytes()
ROUTES = {"/api/news": lambda d, k, f: newscore.collect(d, k, fast=f),
          "/api/summary": lambda d, k, f: newscore.weekly_summary(d, k)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ROUTES:
            days, kws, fast = parse_query(self.path)
            body = json.dumps(ROUTES[u.path](days, kws, fast), ensure_ascii=False).encode()
            ctype = "application/json; charset=utf-8"
        elif u.path == "/":
            body, ctype = INDEX, "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"뉴스 스크랩 실행 중: {url}  (종료: Ctrl+C)")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
