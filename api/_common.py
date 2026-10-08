import json
import urllib.parse


def parse_query(path):
    """?days=7&kw=한수원,새울본부&fast=1 -> (days, kws|None, fast)"""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    try:
        days = max(1, min(int(q.get("days", ["7"])[0]), 365))
    except ValueError:
        days = 7
    kws = [k.strip()[:30] for k in q.get("kw", [""])[0].split(",") if k.strip()][:8]
    return days, (kws or None), q.get("fast", ["0"])[0] == "1"


def respond(h, fn, ttl=0):
    """요청 핸들러 h 에 fn(days, kws, fast) 의 결과를 JSON 으로 응답한다.

    ttl > 0 이면 Vercel CDN 이 같은 주소의 응답을 ttl 초 동안 모든 방문자에게 재사용한다.
    (공개 사이트에서 방문자가 많아도 외부 호출·AI 비용이 늘지 않게 하는 장치.) 오류 응답은 캐시하지 않는다.
    """
    days, kws, fast = parse_query(h.path)
    result = fn(days, kws, fast)
    body = json.dumps(result, ensure_ascii=False).encode()
    cacheable = ttl > 0 and not (isinstance(result, dict) and result.get("error"))
    h.send_response(200)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Cache-Control",
                  f"public, s-maxage={ttl}, stale-while-revalidate={ttl * 4}" if cacheable else "no-store")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)
