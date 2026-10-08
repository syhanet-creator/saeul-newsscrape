from http.server import BaseHTTPRequestHandler

from _common import newscore, respond


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        respond(self, newscore.weekly_summary)
