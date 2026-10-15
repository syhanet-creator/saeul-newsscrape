import os
import sys
from http.server import BaseHTTPRequestHandler

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import send_json  # noqa: E402
import _admin  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 화면 상단 광고 배너. 저장소가 안 되거나 오류가 나도 화면은 멀쩡해야 하므로 빈 목록을 준다.
        try:
            send_json(self, {"banners": _admin.public_banners()}, "public, s-maxage=60, stale-while-revalidate=300")
        except Exception:
            send_json(self, {"banners": []}, "public, s-maxage=10")
