"""(임시 진단) Vercel 서버에서 울산뉴스넷·울주신문에 어떤 방식의 요청이 통하는지 시험한다. 확인 후 삭제한다."""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import newscore  # noqa: E402
from _common import send_json  # noqa: E402

SITES = {"ulsannews": "ulsannews.net", "uljusinmun": "www.uljusinmun.co.kr"}
SEARCH = "/search.html?" + urllib.parse.urlencode(
    {"submit": "submit", "search_and": 1, "search_exec": "all", "search_section": "all", "news_order": 1, "search": "새울"})
BROWSER = {"User-Agent": newscore._BROWSER_UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
           "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5"}


def attempt(label, url, headers, timeout=7):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(400000)
            return {"try": label, "status": r.status, "ms": round((time.time() - t0) * 1000), "bytes": len(body),
                    "results_marker": b"search_result_list_box" in body}
    except Exception as e:
        return {"try": label, "error": f"{type(e).__name__}: {str(e)[:60]}", "ms": round((time.time() - t0) * 1000)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        host = SITES.get(q.get("site", [""])[0])
        if not host:
            return send_json(self, {"error": "site"}, status=400)
        base_ua = {"User-Agent": newscore.UA}
        out = [
            attempt("현재방식: 봇 UA + http 검색", f"http://{host}{SEARCH}", base_ua),
            attempt("브라우저 UA + http 검색", f"http://{host}{SEARCH}", BROWSER),
            attempt("브라우저 UA + https 검색", f"https://{host}{SEARCH}", BROWSER),
            attempt("브라우저 UA + 첫 화면", f"http://{host}/", BROWSER),
            attempt("브라우저 UA + RSS", f"http://{host}/rss/rss_news.php", BROWSER),
        ]
        # 실제 수집 함수를 그대로 실행해 어떤 예외가 나는지 본다(순서대로 / 동시에)
        import threading
        fn = newscore.fetch_ulsannews if "ulsannews" in host else newscore.fetch_uljusinmun
        real = []
        for kw in ("새울원자력본부", "새울본부", "한국수력원자력", "한수원"):
            t0 = time.time()
            try:
                r = fn(kw, 7)
                real.append({"kw": kw, "ok": len(r), "ms": round((time.time() - t0) * 1000)})
            except Exception as e:
                real.append({"kw": kw, "exc": f"{type(e).__name__}: {str(e)[:80]}", "ms": round((time.time() - t0) * 1000)})
        conc = [None] * 4

        def run(i, kw):
            t0 = time.time()
            try:
                conc[i] = {"kw": kw, "ok": len(fn(kw, 7)), "ms": round((time.time() - t0) * 1000)}
            except Exception as e:
                conc[i] = {"kw": kw, "exc": f"{type(e).__name__}: {str(e)[:80]}", "ms": round((time.time() - t0) * 1000)}
        th = [threading.Thread(target=run, args=(i, kw)) for i, kw in enumerate(("새울원자력본부", "새울본부", "한국수력원자력", "한수원"))]
        [x.start() for x in th]
        [x.join() for x in th]
        send_json(self, {"site": host, "region": os.environ.get("VERCEL_REGION"), "results": out, "real_sequential": real, "real_concurrent": conc})
