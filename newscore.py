"""뉴스 수집(구글 뉴스 RSS + 울산 지역 신문 8곳) + 스팸 제외 + 유사 기사 묶기 + 주간 AI 요약.
Vercel 함수와 로컬 서버가 함께 쓴다.
"""
import html
import json
import os
import re
import threading
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
FETCH_TIMEOUT = 10  # 지역 신문 한 번 요청의 제한 시간(초). 시간 초과 시 한 번 더 시도한다.
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
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
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


# ---------- 기자 이름 ----------
NOT_NAMES = {"울주신문", "울산뉴스넷", "울산매일", "울산신문", "경상일보", "울산제일일보", "울산종합일보", "울산시민신문",
             "관리자", "편집부", "편집국", "보도자료", "취재", "담당", "본지", "현장", "사진", "영상", "수습", "인턴", "선임",
             "사회", "정치", "경제", "문화", "지역", "온라인"}
OUTLET_SUFFIX = ("일보", "신문", "뉴스", "방송", "미디어", "저널", "투데이", "타임스", "데일리", "경제", "통신", "닷컴", "넷")
BYLINE_RE = re.compile(r"([가-힣]{2,4})\s*(?:기자|PD|논설위원|대기자|편집위원)")


def clean_author(s):
    """'이두영 기자 |' 같은 문자열에서 이름만 남긴다. 신문사 이름·부서명이면 빈 문자열."""
    s = html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    m = BYLINE_RE.search(s)
    name = m.group(1) if m else re.sub(r"[^가-힣]", "", s)
    if (not (2 <= len(name) <= 4) or name in NOT_NAMES or name.endswith(("부", "팀", "국", "실"))
            or name.endswith(OUTLET_SUFFIX)):
        return ""
    return name


ULSAN_BOX = re.compile(
    r"<dt><a href='(/\d+)'>(.*?)</a></dt>(.*?)class='etc'>(.*?)(\d{4}\.\d\d\.\d\d \d\d:\d\d)", re.S)


def local_paper(name, base):
    """같은 뉴스 CMS를 쓰는 지역 신문(울산뉴스넷·울주신문)의 사이트 검색 결과 1페이지를 읽는다."""
    def fetch(kw, days):
        q = urllib.parse.urlencode({"submit": "submit", "search_and": 1, "search_exec": "all",
                                    "search_section": "all", "news_order": 1, "search": kw})
        req = urllib.request.Request(base + "/search.html?" + q, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
            page = r.read().decode("utf-8", "replace")
        limit = time.time() - days * 86400
        items = []
        for path, title, lead, pre, when in ULSAN_BOX.findall(page):
            ts = datetime.strptime(when, "%Y.%m.%d %H:%M").replace(tzinfo=KST).timestamp()
            if ts < limit:
                continue
            title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            # 이름 칸이 신문사 이름이면 본문 앞머리의 '[울주신문=김정대기자]' 에서 읽는다.
            author = clean_author(pre) or clean_author(lead[:200])
            items.append({"title": title, "link": base + path, "source": name,
                          "ts": ts, "local": True, "author": author})
        return items
    return fetch


UCI_ROW = re.compile(
    r'<a href="(/news/articleView\.html\?idxno=\d+)" class="links"><strong>(.*?)</strong></a>.*?'
    r'class="list-dated[^"]*">([^<]*?)(\d{4}-\d\d-\d\d \d\d:\d\d)', re.S)


def fetch_ucinews(kw, days):
    """울산시민신문: 사이트 검색 결과 1페이지."""
    base = "http://www.ucinews.kr"
    # 검색 폼이 POST 방식이다(GET 은 검색어를 무시한다).
    data = urllib.parse.urlencode({"sc_area": "A", "sc_word": kw}).encode()
    req = urllib.request.Request(base + "/news/articleList.html", data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
        page = r.read().decode("utf-8", "replace")
    limit = time.time() - days * 86400
    items = []
    for path, title, pre, when in UCI_ROW.findall(page):
        ts = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=KST).timestamp()
        if ts >= limit:
            items.append({"title": html.unescape(re.sub(r"<[^>]+>", "", title)).strip(),
                          "link": base + path, "source": "울산시민신문", "ts": ts, "local": True,
                          "author": clean_author(pre)})
    return items


_iusm = {"t": 0, "items": []}


def _iusm_feed():
    """울산매일 전체기사 RSS 는 2분간 한 번만 받아 키워드별 호출이 같이 쓴다."""
    if time.time() - _iusm["t"] > 120:
        req = urllib.request.Request("https://www.iusm.co.kr/rss/allArticle.xml", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
            root = ET.fromstring(r.read())
        items = []
        for it in root.iter("item"):
            try:
                ts = datetime.strptime(it.findtext("pubDate").strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST).timestamp()
            except Exception:
                continue
            items.append({"title": (it.findtext("title") or "").strip(), "desc": it.findtext("description") or "",
                          "link": (it.findtext("link") or "").strip(), "ts": ts,
                          "author": clean_author(it.findtext("author"))})
        _iusm.update(t=time.time(), items=items)
    return _iusm["items"]


def fetch_iusm(kw, days):
    """울산매일: 사이트 검색이 동작하지 않아 전체기사 RSS(최근 50건)에서 키워드가 든 기사만 고른다."""
    limit = time.time() - days * 86400
    return [{"title": html.unescape(a["title"]), "link": a["link"], "source": "울산매일", "ts": a["ts"], "local": True,
             "author": a["author"]}
            for a in _iusm_feed() if a["ts"] >= limit and (kw in a["title"] or kw in a["desc"])]


ART_A = re.compile(r'<a\s[^>]*href=["\']([^"\']*(?:idxno=\d+|ncode=\d+|/news/view\.php\?[^"\']*|/\d{5,})[^"\']*)["\'][^>]*>(.*?)</a>', re.S)
DATE_RE = re.compile(r"(\d{4})[.\-](\d\d)[.\-](\d\d)(?:\s+(\d\d):(\d\d))?")


def _art_id(href):
    m = re.search(r"idxno=(\d+)|ncode=(\d+)|[?&](?:no|uid|id)=(\d+)|/(\d{5,})", href)
    return next((g for g in m.groups() if g), href) if m else href


def parse_cms_list(page, base):
    """사이트마다 다른 검색 결과 HTML에서 (제목, 링크, 시각)을 뽑는다.
    기사 링크 바로 뒤(다음 기사 링크 전)에 날짜가 있는 것만 채택해 사이드바 기사를 걸러낸다."""
    anchors = [(m.start(), m.end(), m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()) for m in ART_A.finditer(page)]
    found = {}
    for i, (s, e, href, text) in enumerate(anchors):
        aid = _art_id(href)
        nxt = next((a[0] for a in anchors[i + 1:] if _art_id(a[2]) != aid), min(len(page), e + 900))
        d = DATE_RE.search(page[e:min(nxt, e + 900)])
        rec = found.setdefault(aid, {"href": href, "title": "", "date": None, "author": ""})
        if len(text) >= 8 and not rec["title"]:
            rec["title"] = html.unescape(text)
        if d and not rec["date"]:
            rec["date"] = d
        if not rec["author"]:  # 링크 뒤쪽(다음 기사 전)에서 '홍길동 기자' 형태를 찾는다.
            by = BYLINE_RE.search(re.sub(r"<[^>]+>", " ", page[e:min(nxt, e + 900)]))
            rec["author"] = clean_author(by.group(0)) if by else ""
    items = []
    for rec in found.values():
        d = rec["date"]
        if not (rec["title"] and d):
            continue
        y, mo, da, hh, mi = d.groups()
        ts = datetime(int(y), int(mo), int(da), int(hh or 0), int(mi or 0), tzinfo=KST).timestamp()
        items.append({"title": rec["title"], "link": urllib.parse.urljoin(base + "/", rec["href"].replace("&amp;", "&")),
                      "ts": ts, "author": rec["author"]})
    return items


def cms_site(name, base, url, method="GET", extra=None, kwname="sc_word"):
    """검색 결과 1페이지를 읽는 범용 수집 함수를 만든다."""
    def fetch(kw, days):
        params = {**(extra or {}), kwname: kw}
        enc = urllib.parse.urlencode(params)
        if method == "POST":
            req = urllib.request.Request(url, data=enc.encode(), headers={"User-Agent": UA})
        else:
            req = urllib.request.Request(url + "?" + enc, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
            raw = r.read(1_500_000)
        try:
            page = raw.decode("utf-8")
        except UnicodeDecodeError:
            page = raw.decode("euc-kr", "replace")
        limit = time.time() - days * 86400
        return [{**a, "source": name, "local": True} for a in parse_cms_list(page, base) if a["ts"] >= limit]
    return fetch


fetch_ulsanpress = cms_site("울산신문", "https://www.ulsanpress.net", "https://www.ulsanpress.net/news/articleList.html",
                            "POST", {"sc_area": "A"})
fetch_ksilbo = cms_site("경상일보", "https://www.ksilbo.co.kr", "https://prt.ksilbo.co.kr/engine_yonhap/search.php",
                        "POST", {"sc_area": "A", "view_type": "sm"})
fetch_ujeil = cms_site("울산제일일보", "http://www.ujeil.com", "http://www.ujeil.com/news/articleList.html",
                       "GET", {"sc_area": "A"})
fetch_ujnews = cms_site("울산종합일보", "https://www.ujnews.co.kr", "https://www.ujnews.co.kr/news/search.php",
                        "GET", kwname="q")

fetch_ulsannews = local_paper("울산뉴스넷", "http://ulsannews.net")
fetch_uljusinmun = local_paper("울주신문", "http://www.uljusinmun.co.kr")


SOURCES = (("google", fetch_google), ("울산뉴스넷", fetch_ulsannews),
           ("울주신문", fetch_uljusinmun), ("울산시민신문", fetch_ucinews), ("울산매일", fetch_iusm),
           ("울산신문", fetch_ulsanpress), ("경상일보", fetch_ksilbo), ("울산제일일보", fetch_ujeil),
           ("울산종합일보", fetch_ujnews))

_fcache = {}
_locks = {name: threading.Semaphore(2) for name, _ in SOURCES}


def _cached(name, fn, kw, days, ttl=120):
    """같은 (출처, 키워드, 기간) 요청은 2분간 재사용해 지역 신문 사이트에 부담을 줄인다."""
    key = (name, kw, days)
    hit = _fcache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return [dict(a) for a in hit[1]]
    try:
        if name == "google":
            res = fn(kw, days)
        else:
            # 지역 신문은 같은 사이트에 요청을 동시에 많이 보내지 않고, 429·시간 초과면 한 번 더 시도한다.
            with _locks[name]:
                for attempt in (0, 1):
                    try:
                        res = fn(kw, days)
                        break
                    except urllib.error.HTTPError as e:
                        if e.code != 429 or attempt:
                            raise
                        time.sleep(1.5)
                    except (TimeoutError, urllib.error.URLError):
                        if attempt:
                            raise
                time.sleep(0.1)
    except Exception:
        if hit:  # 실패하면 직전에 받아 둔 결과(오래됐어도)를 대신 쓴다.
            return [dict(a) for a in hit[1]]
        raise
    _fcache[key] = (time.time(), res)
    return [dict(a) for a in res]


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


GN_LINK = "https://news.google.com/rss/articles/"
_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def resolve_google(link, timeout=10):
    """구글 뉴스 기사 링크 -> 원문 주소. 구글의 기사 변환 요청(batchexecute)을 쓴다. 실패하면 ''."""
    if not link.startswith(GN_LINK):
        return ""
    gid = link[len(GN_LINK):].split("?")[0]
    hdr = {"User-Agent": _BROWSER_UA}
    page = urllib.request.urlopen(
        urllib.request.Request(f"https://news.google.com/articles/{gid}", headers=hdr), timeout=timeout).read().decode("utf-8", "replace")
    sg, ts = re.search(r'data-n-a-sg="([^"]+)"', page), re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return ""
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None,
                                        None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], gid, int(ts.group(1)), sg.group(1)])
    body = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]])}).encode()
    req = urllib.request.Request("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body,
                                 headers={**hdr, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    res = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    m = re.search(r'garturlres.{0,6}?(https?:[^"\\]+)', res)
    return m.group(1) if m else ""


_META_AUTH = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:dable:author|og:article:author|article:author|author|byline|twitter:creator)["\'][^>]*>', re.I)
_LD_AUTH = re.compile(r'"author"\s*:\s*(?:\[\s*)?\{[^}]*?"name"\s*:\s*"([^"]+)"')
_TAG = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def page_author(page):
    """기사 HTML 에서 기자 이름을 찾는다: ① 메타 태그 ② JSON-LD ③ 제목 아래 바이라인('홍길동 기자')."""
    for m in _META_AUTH.finditer(page):
        c = re.search(r'content=["\']([^"\']*)["\']', m.group(0))
        name = clean_author(c.group(1)) if c else ""
        if name:
            return name
    for m in _LD_AUTH.finditer(page):
        name = clean_author(m.group(1))
        if name:
            return name
    h1 = re.search(r"<h1", page)
    start = h1.start() if h1 else 0
    text = html.unescape(_TAG.sub(" ", page[start:start + 20000]))
    for m in BYLINE_RE.finditer(text[:1500]):  # 제목 바로 아래 영역
        name = clean_author(m.group(0))
        if name:
            return name
    return ""


_authors = {}  # 기사 링크 -> 기자 이름(본문 페이지에서 읽은 결과를 서버가 켜져 있는 동안 기억한다)
_AUTHOR_META = re.compile(r'property="(?:dable:author|og:article:author)"\s*content="([^"]*)"')


_gn_block = {"until": 0.0}  # 구글이 429 로 막으면 이 시각까지 구글 요청을 하지 않는다
_gn_last = {"t": 0.0}
_gn_lock = threading.Lock()


def author_for_google(link):
    """구글 뉴스 링크 -> (기자 이름, 상태). 상태: ok(이름이 비어 있을 수 있음) / blocked / fail.
    구글에는 한 서버 안에서 순서대로, 최소 1.2초 간격으로만 요청하고 429 를 받으면 2분간 멈춘다."""
    if link in _authors:
        return _authors[link], "ok"
    if time.time() < _gn_block["until"]:
        return "", "blocked"
    with _gn_lock:
        wait = 1.2 - (time.time() - _gn_last["t"])
        if wait > 0:
            time.sleep(wait)
        try:
            url = resolve_google(link)
        except urllib.error.HTTPError as e:
            _gn_last["t"] = time.time()
            if e.code == 429:
                _gn_block["until"] = time.time() + 120
                return "", "blocked"
            return "", "fail"
        except Exception:
            _gn_last["t"] = time.time()
            return "", "fail"
        _gn_last["t"] = time.time()
    if not url:
        return "", "fail"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            page = r.read(400000).decode("utf-8", "replace")
    except Exception:
        return "", "fail"
    _authors[link] = page_author(page)
    return _authors[link], "ok"


def _article_author(link):
    """기사 본문 페이지 앞부분의 author 메타 태그에서 기자 이름을 읽는다."""
    if link in _authors:
        return _authors[link]
    name = ""
    try:
        req = urllib.request.Request(link, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=6) as r:
            head = r.read(60000).decode("utf-8", "replace")
        for m in _AUTHOR_META.finditer(head):
            name = clean_author(m.group(1))
            if name:
                break
    except Exception:
        pass
    _authors[link] = name
    return name


def fill_authors(arts, limit=30):
    """목록에서 기자 이름을 못 얻은 지역 기사만 본문 페이지로 보충한다(최신순, 한 번에 limit건까지)."""
    need = sorted((a for a in arts if a.get("local") and not a["author"]), key=lambda a: -a["ts"])
    fresh = [a for a in need if a["link"] not in _authors][:limit]
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda a: _article_author(a["link"]), fresh))
    for a in need:
        a["author"] = _authors.get(a["link"], "")


def collect(days, kws=None, fast=False):
    """fast=True 면 구글 뉴스만(빠른 첫 화면), 아니면 지역 신문까지."""
    sources = SOURCES[:1] if fast else SOURCES
    kws = [k for k in (kws or KEYWORDS)][:8]
    merged, failed = {}, {}
    with ThreadPoolExecutor(max(1, len(kws) * len(sources))) as ex:
        futs = [(kw, name, ex.submit(_cached, name, fn, kw, days)) for kw in kws for name, fn in sources]
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
                    a.setdefault("author", "")
                    a.setdefault("local", False)
                    merged[key] = a
        except Exception as e:
            failed.setdefault(name, f"{name}: 응답이 느려 일부 결과가 빠졌을 수 있습니다")
    arts = sorted(merged.values(), key=lambda a: a["ts"], reverse=True)
    if not fast:
        fill_authors(arts)
    cluster(arts)
    return {"articles": arts, "errors": list(failed.values()), "keywords": kws,
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
