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
        def run(d, k, f, t):
            res = newscore.collect_tab(t or newscore.MAIN_TAB, d, fast=f)
            if "debug=1" in self.path and isinstance(res, dict):
                res["last_fail"] = dict(newscore.LAST_FAIL)
            return res
        respond(self, run, ttl=0 if "debug=1" in self.path else 60)
