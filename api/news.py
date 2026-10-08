"""구글 뉴스 RSS 실시간 수집 (Vercel 서버리스 함수 + 로컬 서버 공용)."""
import html
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler

KEYWORDS = ["한국수력원자력", "새울원자력본부", "한수원", "새울본부"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsScrap/1.0"


def fetch_keyword(kw, days):
    q = f'"{kw}" when:{days}d'
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
           + "&hl=ko&gl=KR&ceid=KR:ko")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    items = []
    for it in root.iter("item"):
        title = it.findtext("title") or ""
        source = it.findtext("source") or ""
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:
            dt = datetime.fromtimestamp(0, timezone.utc)
        items.append({
            "title": html.unescape(title),
            "link": it.findtext("link") or "",
            "source": source,
            "ts": dt.timestamp(),
            "kw": kw,
        })
    return items


def collect(days):
    merged, errors = {}, []
    with ThreadPoolExecutor(len(KEYWORDS)) as ex:
        futs = {kw: ex.submit(fetch_keyword, kw, days) for kw in KEYWORDS}
    for kw, f in futs.items():
        try:
            for a in f.result():
                key = a["link"] or a["title"]
                if key in merged:
                    if kw not in merged[key]["kws"]:
                        merged[key]["kws"].append(kw)
                else:
                    a["kws"] = [kw]
                    del a["kw"]
                    merged[key] = a
        except Exception as e:
            errors.append(f"{kw}: {e}")
    arts = sorted(merged.values(), key=lambda a: a["ts"], reverse=True)
    return {"articles": arts, "errors": errors, "keywords": KEYWORDS,
            "fetched": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            days = int(q.get("days", ["7"])[0])
        except ValueError:
            days = 7
        body = json.dumps(collect(max(1, min(days, 365))), ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
