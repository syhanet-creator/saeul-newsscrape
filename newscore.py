"""뉴스 수집(구글 뉴스 RSS + 울산뉴스넷 + 선택적 네이버) + 스팸 제외 + 유사 기사 묶기 + 주간 AI 요약.
Vercel 함수와 로컬 서버가 함께 쓴다.
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KEYWORDS = ["한국수력원자력", "새울원자력본부", "한수원", "새울본부"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsScrap/1.0"
KST = timezone(timedelta(hours=9))
SIM_THRESHOLD = 0.4
CLAUDE_MODEL = os.environ.get("SUMMARY_MODEL", "claude-haiku-4-5-20251001")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
_cache = {}

# ---------- 스팸/광고 제외 ----------
# 한수원 키워드가 우연히 섞여 들어오는 도박·게임 사이트 등. 환경변수 BLOCKED_SOURCES(쉼표 구분)로 추가 가능.
BLOCKED_SOURCES = ["Calgary Roughnecks"] + [
    s.strip() for s in os.environ.get("BLOCKED_SOURCES", "").split(",") if s.strip()]
SPAM_RE = re.compile(r"토토|카지노|슬롯|바카라|먹튀|베팅|배팅|파워볼|도박|라이브\s?스코어|보증업체|사설")


def is_spam(a):
    return any(b.lower() in a["source"].lower() for b in BLOCKED_SOURCES) or bool(SPAM_RE.search(a["title"]))


# ---------- 수집 ----------
def fetch_google(kw, days):
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
        items.append({"title": html.unescape(title), "link": it.findtext("link") or "",
                      "source": source, "ts": dt.timestamp()})
    return items


ULSAN_BOX = re.compile(
    r"<dt><a href='(/\d+)'>(.*?)</a></dt>.*?class='etc'>.*?(\d{4}\.\d\d\.\d\d \d\d:\d\d)", re.S)


def local_paper(name, base):
    """같은 뉴스 CMS를 쓰는 지역 신문(울산뉴스넷·울주신문)의 사이트 검색 결과 1페이지를 읽는다."""
    def fetch(kw, days):
        q = urllib.parse.urlencode({"submit": "submit", "search_and": 1, "search_exec": "all",
                                    "search_section": "all", "news_order": 1, "search": kw})
        req = urllib.request.Request(base + "/search.html?" + q, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            page = r.read().decode("utf-8", "replace")
        limit = time.time() - days * 86400
        items = []
        for path, title, when in ULSAN_BOX.findall(page):
            ts = datetime.strptime(when, "%Y.%m.%d %H:%M").replace(tzinfo=KST).timestamp()
            if ts < limit:
                continue
            title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            items.append({"title": title, "link": base + path, "source": name,
                          "ts": ts, "local": True})
        return items
    return fetch


fetch_ulsannews = local_paper("울산뉴스넷", "http://ulsannews.net")
fetch_uljusinmun = local_paper("울주신문", "http://www.uljusinmun.co.kr")


def fetch_naver(kw, days):
    """네이버 검색 API (NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 있을 때만 사용)."""
    cid, sec = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if not (cid and sec):
        return []
    url = ("https://openapi.naver.com/v1/search/news.json?display=100&sort=date&query="
           + urllib.parse.quote(kw))
    req = urllib.request.Request(url, headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    limit = time.time() - days * 86400
    items = []
    for it in data.get("items", []):
        ts = parsedate_to_datetime(it["pubDate"]).timestamp()
        if ts < limit:
            continue
        link = it.get("originallink") or it["link"]
        host = urllib.parse.urlparse(link).netloc.replace("www.", "")
        title = html.unescape(re.sub(r"<[^>]+>", "", it["title"]))
        items.append({"title": title, "link": link, "source": host, "ts": ts})
    return items


SOURCES = (("google", fetch_google), ("울산뉴스넷", fetch_ulsannews),
           ("울주신문", fetch_uljusinmun), ("naver", fetch_naver))


# ---------- 유사 기사 묶기 ----------
def _grams(title):
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", title)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def cluster(arts):
    """제목 글자 2-gram 유사도(Jaccard)로 묶어 각 기사에 gid를 부여한다."""
    grams = [_grams(a["title"]) for a in arts]
    parent = list(range(len(arts)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(arts)):
        for j in range(i):
            u = len(grams[i] | grams[j])
            if u and len(grams[i] & grams[j]) / u >= SIM_THRESHOLD:
                parent[find(i)] = find(j)
    for i, a in enumerate(arts):
        a["gid"] = find(i)


def collect(days, kws=None):
    kws = [k for k in (kws or KEYWORDS)][:8]
    merged, errors = {}, []
    with ThreadPoolExecutor(max(1, len(kws) * len(SOURCES))) as ex:
        futs = [(kw, name, ex.submit(fn, kw, days)) for kw in kws for name, fn in SOURCES]
    for kw, name, f in futs:
        try:
            for a in f.result():
                key = a["link"] or a["title"]
                if key in merged:
                    if kw not in merged[key]["kws"]:
                        merged[key]["kws"].append(kw)
                else:
                    a["kws"] = [kw]
                    a["spam"] = is_spam(a)
                    a.setdefault("local", False)
                    merged[key] = a
        except Exception as e:
            errors.append(f"{kw} ({name}): {e}")
    arts = sorted(merged.values(), key=lambda a: a["ts"], reverse=True)
    cluster(arts)
    return {"articles": arts, "errors": errors, "keywords": kws,
            "fetched": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


# ---------- 주간 AI 요약 ----------
class ApiError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def _post_json(url, headers, payload, timeout=50):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except Exception:
            pass
        raise ApiError(e.code, _friendly(e.code, detail))


def _friendly(code, detail):
    d = detail.lower()
    if "credit balance" in d:
        return "API 크레딧이 부족합니다. 공급자 콘솔에서 충전해 주세요."
    if code in (401, 403) or "api key" in d and ("invalid" in d or "not valid" in d):
        return "API 키가 올바르지 않습니다. 환경변수를 확인해 주세요."
    if code == 429 or "quota" in d or "rate" in d:
        return "호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."
    return f"HTTP {code}: {detail[:200]}"


def _ask_llm(prompt):
    """GEMINI_API_KEY 가 있으면 Gemini, 없으면 ANTHROPIC_API_KEY 로 Claude 호출."""
    gkey = os.environ.get("GEMINI_API_KEY")
    if gkey:
        last = None
        # 과부하(503)·모델 없음(404)·한도(429)면 다음 모델로 넘어간다.
        for model in (GEMINI_MODEL, "gemini-flash-latest", "gemini-flash-lite-latest"):
            try:
                r = _post_json(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    {"x-goog-api-key": gkey},
                    {"contents": [{"parts": [{"text": prompt}]}]}, timeout=18)
                return r["candidates"][0]["content"]["parts"][0]["text"]
            except ApiError as e:
                last = e
                if e.code not in (404, 429, 500, 503):
                    raise
            except TimeoutError as e:
                last = e
        raise last
    akey = os.environ.get("ANTHROPIC_API_KEY")
    if akey:
        r = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": akey, "anthropic-version": "2023-06-01"},
            {"model": CLAUDE_MODEL, "max_tokens": 1200,
             "messages": [{"role": "user", "content": prompt}]})
        return r["content"][0]["text"]
    raise RuntimeError("GEMINI_API_KEY 또는 ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")


def weekly_summary(days=7, kws=None):
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return {"error": "GEMINI_API_KEY 또는 ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다."}
    ck = (days, tuple(kws or ()))
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    data = collect(days, kws)
    groups = {}
    for a in data["articles"]:
        if not a["spam"]:
            groups.setdefault(a["gid"], []).append(a)
    ordered = sorted(groups.values(), key=len, reverse=True)[:60]
    lines = [f"- ({len(g)}건) {g[0]['title']} / {', '.join(sorted({x['source'] for x in g})[:4])}"
             for g in ordered]
    prompt = (f"아래는 최근 {days}일간 '{'·'.join(data['keywords'])}' 관련 뉴스를 "
              "유사 기사끼리 묶은 목록입니다(괄호는 보도 건수).\n"
              "한국어로 이번 주 주요 이슈를 요약해 주세요. 형식: 먼저 2~3문장 총평, 이어서 "
              "건수가 많은 순으로 주요 이슈 3~6개를 '- **이슈명**: 한두 문장 설명' 형태의 목록으로. "
              "목록에 없는 내용은 추측하지 마세요.\n\n" + "\n".join(lines))
    try:
        text = _ask_llm(prompt)
    except Exception as e:
        return {"error": f"AI 요약 호출 실패: {e}"}
    out = {"summary": text, "count": sum(map(len, groups.values())), "groups": len(groups),
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    _cache[ck] = (time.time(), out)
    return out
