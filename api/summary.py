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
        # 공개 사이트에서 AI 비용이 새지 않도록 기본 키워드·7일 기준 요약 하나만 만들고 CDN 에서 1시간 공유한다.
        respond(self, lambda d, k, f: newscore.weekly_summary(7, None), ttl=3600)
