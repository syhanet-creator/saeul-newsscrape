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
        respond(self, lambda d, k, f: newscore.collect(d, k, fast=f))
