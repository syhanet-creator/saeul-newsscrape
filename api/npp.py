import os
import sys
from http.server import BaseHTTPRequestHandler

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import send_json  # noqa: E402
import _npp  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        res = _npp.fetch_all()
        # 5분 공유: 방문자가 많아도 한수원 사이트에는 5분에 한 번만 요청이 간다. 오류는 캐시하지 않는다.
        ok = not res.get("error")
        send_json(self, res, "public, s-maxage=300, stale-while-revalidate=900" if ok else "no-store")
