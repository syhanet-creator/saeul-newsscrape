import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import newscore  # noqa: E402
from _common import send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        tab = re.sub(r"[^a-z0-9_]", "", q.get("tab", [""])[0].lower())[:20]
        res = newscore.weather_for(tab)
        # 날씨는 10분마다 바뀌면 충분하므로 CDN 이 모든 방문자에게 10분 공유한다(오류는 캐시하지 않는다).
        send_json(self, res, "no-store" if res.get("error") else "public, s-maxage=600, stale-while-revalidate=1800")
