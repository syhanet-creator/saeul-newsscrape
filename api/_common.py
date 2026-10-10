import json
import re
import urllib.parse


def parse_query(path):
    """?days=7&tab=saeul&fast=1 -> (days, kws|None, fast, tab)"""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    try:
        days = max(1, min(int(q.get("days", ["7"])[0]), 365))
    except ValueError:
        days = 7
    kws = [k.strip()[:30] for k in q.get("kw", [""])[0].split(",") if k.strip()][:8]
    tab = re.sub(r"[^a-z0-9_]", "", q.get("tab", [""])[0].lower())[:20]
    return days, (kws or None), q.get("fast", ["0"])[0] == "1", tab


def send_json(h, obj, cache_control="no-store", status=200):
    body = json.dumps(obj, ensure_ascii=False).encode()
    h.send_response(status)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Cache-Control", cache_control)
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def respond(h, fn, ttl=0):
    """요청 핸들러 h 에 fn(days, kws, fast, tab) 의 결과를 JSON 으로 응답한다.

    ttl > 0 이면 Vercel CDN 이 같은 주소의 응답을 ttl 초 동안 모든 방문자에게 재사용한다.
    (공개 사이트에서 방문자가 많아도 외부 호출·AI 비용이 늘지 않게 하는 장치.) 오류 응답은 캐시하지 않는다.
    """
    days, kws, fast, tab = parse_query(h.path)
    result = fn(days, kws, fast, tab)
    if isinstance(result, dict) and result.get("errors"):
        ttl = min(ttl, 10)  # 일부 출처가 실패한 응답은 오래 공유하지 않는다
    cacheable = ttl > 0 and not (isinstance(result, dict) and result.get("error"))
    send_json(h, result, f"public, s-maxage={ttl}, stale-while-revalidate={ttl * 4}" if cacheable else "no-store")


def author_response(h, newscore):
    """/api/author?u=<구글 뉴스 링크> -> {author, status}. 찾은 결과는 CDN 에 오래 공유한다."""
    link = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query).get("u", [""])[0]
    if not link.startswith(newscore.GN_LINK) or len(link) > 600:
        return send_json(h, {"error": "bad link"}, status=400)
    title = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query).get("t", [""])[0][:200]
    domain = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query).get("d", [""])[0][:100]
    name, status, via = newscore.author_for_article(link, title, domain)
    if status == "ok":
        cc = "public, s-maxage=604800, stale-while-revalidate=86400" if name else "public, s-maxage=86400"
    else:
        cc = "no-store"  # 차단·실패는 캐시하지 않는다
    send_json(h, {"author": name, "status": status, "via": via}, cc)
