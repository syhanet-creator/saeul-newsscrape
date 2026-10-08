"""한수원/새울본부 뉴스 스크랩 앱 - 로컬 실행용.
실행: python news_scrap.py  (브라우저가 자동으로 열립니다)
Vercel 배포 시에는 public/index.html + api/news.py 가 사용됩니다.
"""
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

from api.news import handler as NewsHandler

PORT = 8765
INDEX = (Path(__file__).parent / "public" / "index.html").read_bytes()


class Handler(NewsHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/news"):
            return super().do_GET()
        if self.path != "/":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(INDEX)))
        self.end_headers()
        self.wfile.write(INDEX)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"뉴스 스크랩 실행 중: {url}  (종료: Ctrl+C)")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
