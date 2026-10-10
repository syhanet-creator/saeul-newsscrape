"""한수원 뉴스 스크랩 2.0 (새울본부 메인 + 본부·사업소별 탭) - 로컬 실행용.
실행: python news_scrap.py  (브라우저가 자동으로 열립니다)
주간 AI 요약을 쓰려면 환경변수 GEMINI_API_KEY 또는 ANTHROPIC_API_KEY 가 필요합니다.
Vercel 배포 시에는 public/index.html + api/*.py 가 사용됩니다.
"""
import json
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import newscore
from api._common import author_response, parse_query

PORT = 8765
PUBLIC = Path(__file__).parent / "public"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".webmanifest": "application/manifest+json; charset=utf-8", ".png": "image/png",
         ".json": "application/json; charset=utf-8"}
ROUTES = {"/api/news": lambda d, k, f, t: newscore.collect_tab(t or newscore.MAIN_TAB, d, fast=f),
          "/api/summary": lambda d, k, f, t: newscore.weekly_summary(7, t or newscore.MAIN_TAB),
          "/api/tabs": lambda d, k, f, t: newscore.TABS_CFG}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/author":
            return author_response(self, newscore)
        if u.path in ROUTES:
            days, kws, fast, tab = parse_query(self.path)
            body = json.dumps(ROUTES[u.path](days, kws, fast, tab), ensure_ascii=False).encode()
            ctype = "application/json; charset=utf-8"
        else:
            # public/ 아래의 정적 파일(화면, 아이콘, 매니페스트, 서비스 워커)을 내보낸다.
            rel = "index.html" if u.path == "/" else urllib.parse.unquote(u.path).lstrip("/")
            f = (PUBLIC / rel).resolve()
            if PUBLIC.resolve() not in f.parents or not f.is_file():
                self.send_error(404)
                return
            body = f.read_bytes()
            ctype = TYPES.get(f.suffix, "application/octet-stream")
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
