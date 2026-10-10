import os
import sys
from http.server import BaseHTTPRequestHandler

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import newscore  # noqa: E402
from _common import send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 탭 구성(이름·키워드)은 거의 바뀌지 않으므로 CDN 에서 1시간 공유한다.
        send_json(self, newscore.TABS_CFG, "public, s-maxage=3600, stale-while-revalidate=86400")
