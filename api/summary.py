import os
import sys
from http.server import BaseHTTPRequestHandler

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import newscore  # noqa: E402
from _common import respond  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 공개 사이트에서 AI 비용이 새지 않도록 탭별 7일 요약만 만들고(탭은 정해진 목록만 허용) CDN 에서 1시간 공유한다.
        respond(self, lambda d, k, f, t: newscore.weekly_summary(7, t or newscore.MAIN_TAB), ttl=3600)
