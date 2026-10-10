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

# ---------- v2.0 탭 구성 (서버 수집과 화면이 모두 이 설정을 쓴다: /api/tabs) ----------
# main: 처음 열리는 메인 탭 / local: 울산 지역 신문까지 수집 / keywords: 탭마다 검색하는 해시태그(#) 키워드
TABS_CFG = {
    "version": "2.0",
    # 다른 곳도 쓰는 일반적인 이름(지명이 들어간 시설·기관명 등)은 '한수원/한국수력원자력'이 함께 나온 기사만 가져온다.
    # 구글 뉴스가 따옴표 검색을 느슨하게 처리해 관련 없는 글(여행 블로그, 게임 등)이 섞이는 것을 막는다.
    # 탭에 "context": True 를 주면 그 탭의 모든 키워드에, "ambiguous" 에 적으면 그 키워드에만 적용된다.
    "context_terms": ["한수원", "한국수력원자력"],
    "ambiguous": ["미주지사", "유럽지사"],
    "tabs": [
        # 전체: 모든 탭의 키워드를 한꺼번에 수집(키워드는 아래에서 채운다). 지역 신문은 새울본부 키워드에만 적용.
        {"id": "all", "name": "전체", "all": True, "local": True, "keywords": []},
        {"id": "saeul", "name": "새울본부", "main": True, "local": True,
         "keywords": ["새울원자력본부", "새울본부"]},
        {"id": "khnp", "name": "한수원",
         "keywords": ["한국수력원자력주식회사", "한국수력원자력", "한수원", "한수원(주)"]},
        {"id": "hanul", "name": "한울본부", "keywords": ["한울원자력본부", "한울본부"]},
        {"id": "kori", "name": "고리본부", "keywords": ["고리원자력본부", "고리본부"]},
        {"id": "hanbit", "name": "한빛본부", "keywords": ["한빛원자력본부", "한빛본부"]},
        {"id": "wolsong", "name": "월성본부", "keywords": ["월성원자력본부", "월성본부"]},
        {"id": "overseas", "name": "해외사업소",
         "keywords": ["바라카건설소", "미주지사", "유럽지사", "엘바다건설소", "체르나보다TRF건설소",
                      "체르나보다설비개선건설소", "두코바니건설소"]},
        {"id": "pumped", "context": True, "name": "양수건설",
         "keywords": ["영동양수건설소", "홍천양수건설소", "포천양수건설소"]},
        {"id": "hydro", "context": True, "name": "수력양수",
         "keywords": ["한강수력본부", "청평양수발전소", "삼랑진양수발전소", "무주양수발전소", "산청양수발전소",
                      "양양양수발전소", "청송양수발전소", "예천양수발전소", "원자력수소융복합센터"]},
        {"id": "research", "context": True, "name": "연구보건", "keywords": ["중앙연구원", "방사선보건원"]},
        {"id": "etc", "context": True, "name": "기타 기관", "keywords": ["인재개발원", "구매기술센터", "공간디자인센터"]},
    ],
}
_all_kws = []
for _t in TABS_CFG["tabs"]:
    if not _t.get("all"):
        _all_kws += [k for k in _t["keywords"] if k not in _all_kws]
for _t in TABS_CFG["tabs"]:
    if _t.get("all"):
        _t["keywords"] = _all_kws
TABS = {t["id"]: t for t in TABS_CFG["tabs"]}
MAIN_TAB = next(t["id"] for t in TABS_CFG["tabs"] if t.get("main"))
KEYWORDS = TABS[MAIN_TAB]["keywords"]
CONTEXT_KWS = set(TABS_CFG["ambiguous"]) | {k for t in TABS_CFG["tabs"] if t.get("context") for k in t["keywords"]}
# 구글이 본문 어딘가에만 단어가 나와도 결과에 넣어서(예: 시장 일정 기사에 '한수원'·'인재개발원'이 스쳐 지나감) 잡음이 생긴다.
# 이런 키워드(와 검색이 불안정한 '한수원(주)' 등)의 기사는 **제목에** 한수원/한국수력원자력 또는 그 키워드가 있어야 인정한다.
TITLE_REQUIRED = CONTEXT_KWS | {"한수원(주)", "한국수력원자력주식회사"}


def _stem(kw):
    """시설 이름에서 끝말(건설소·발전소·본부·센터)을 뗀 앞부분. 영동양수건설소 -> 영동양수 (기사 제목은 '영동양수발전소'로 쓰기도 한다)."""
    for suf in ("건설소", "발전소", "본부", "센터"):
        if kw.endswith(suf) and len(kw) - len(suf) >= 2:
            return kw[: -len(suf)]
    return kw


NAME_IS_CONTEXT = {"한수원(주)", "한국수력원자력주식회사"}  # 이 둘은 회사 이름 자체라 '한수원/한국수력원자력'이 제목에 있으면 인정
# 기사 본문에 행사 장소·주최 기관으로 자주 나오지만 제목에는 거의 안 나오는 기관(원문 확인: "서울 방사선보건원에서 설명회 개최",
# "한수원 중앙연구원 관계자는"). 이 키워드는 제목에 한수원/한국수력원자력이 있으면 인정한다.
LENIENT_KWS = {"중앙연구원"}  # 방사선보건원은 행사 장소로만 나오는 경우가 많아 제목에 있어야 인정(엄격)


def title_relevant(kw, title):
    """제목에 키워드(시설 이름 앞부분)가 있어야 관련 기사로 본다. 공백은 무시한다.
    ('한수원'이 제목에 있다는 것만으로는 부족하다: 한수원 기사는 거의 다 그렇고, 구글은 페이지 옆 목록의 글자까지 읽어
    인재개발원 같은 단어가 본문에 없는 기사도 결과에 넣는다.)"""
    t = re.sub(r"\s+", "", title)
    if kw in NAME_IS_CONTEXT or kw in LENIENT_KWS:
        return any(c in t for c in TABS_CFG["context_terms"])
    return re.sub(r"\s+", "", _stem(kw)) in t
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsScrap/1.0"
KST = timezone(timedelta(hours=9))
SIM_THRESHOLD = 0.4
FETCH_TIMEOUT = 8  # 지역 신문 한 번 요청의 제한 시간(초). 시간 초과 시 한 번 더 시도한다.
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
def google_query(kw):
    """키워드 검색식. 일반적인 이름(예: 미주지사)은 '한수원 OR 한국수력원자력'이 함께 나온 기사만."""
    q = f'"{kw}"'
    if kw in CONTEXT_KWS:
        ctx = " OR ".join(f'"{c}"' for c in TABS_CFG["context_terms"])
        q += f" ({ctx})"
    return q


def fetch_google(kw, days):
    q = f"{google_query(kw)} when:{days}d"
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
        src_el = it.find("source")
        host = urllib.parse.urlparse((src_el.get("url") if src_el is not None else "") or "").hostname or ""
        items.append({"title": html.unescape(title), "link": it.findtext("link") or "",
                      "source": source, "ts": dt.timestamp(),
                      "domain": re.sub(r"^(www|m|mobile)\.", "", host)})  # 출처 사이트 주소(기자명을 같은 신문사에서만 빌리기 위해)
    return items


# ---------- 기자 이름 ----------
NOT_NAMES = {"울주신문", "울산뉴스넷", "울산매일", "울산신문", "경상일보", "울산제일일보", "울산종합일보", "울산시민신문",
             "관리자", "편집부", "편집국", "보도자료", "취재", "담당", "본지", "현장", "사진", "영상", "수습", "인턴", "선임",
             "사회", "정치", "경제", "문화", "지역", "온라인", "뉴시스", "연합", "프레시안", "오마이", "한겨레", "동아",
             "조선", "중앙", "한경", "매경", "머니", "이데일리", "아이뉴스", "파이낸셜", "헤럴드", "세계일보", "전문"}
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
_gsem = threading.Semaphore(8)
_down = {}  # 출처 이름 -> 이 시각까지 건너뜀
_locks = {name: threading.Semaphore(2) for name, _ in SOURCES}


def _cached(name, fn, kw, days, ttl=120):
    """같은 (출처, 키워드, 기간) 요청은 2분간 재사용해 지역 신문 사이트에 부담을 줄인다."""
    key = (name, kw, days)
    hit = _fcache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return [dict(a) for a in hit[1]]
    try:
        if name == "google":
            with _gsem:  # 전체 탭처럼 키워드가 많아도 구글에는 동시에 8개까지만
                res = fn(kw, days)
        else:
            # 지역 신문은 같은 사이트에 요청을 동시에 많이 보내지 않는다. 429 면 한 번 더 시도하고,
            # 응답이 없으면(시간 초과) 그 출처를 1분간 건너뛴다 -> 느린 사이트 하나가 전체를 붙잡지 못한다.
            with _locks[name]:
                if time.time() < _down.get(name, 0):  # 차례를 기다리는 사이 다른 요청이 이미 실패했다면 바로 포기
                    raise TimeoutError(f"{name} 일시 중단")
                for attempt in (0, 1):
                    try:
                        res = fn(kw, days)
                        break
                    except urllib.error.HTTPError as e:
                        if e.code != 429 or attempt:
                            raise
                        time.sleep(1.5)
                    except (TimeoutError, urllib.error.URLError):
                        _down[name] = time.time() + 60
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
    # 응답은 JSON 안의 JSON 이라 주소 속 '=' '&' 가 = & 처럼 이스케이프돼 있다 -> 풀어서 돌려준다.
    return _extract_gn_url(res)


def _extract_gn_url(res):
    m = re.search(r'garturlres\\*"\s*,\s*\\*"(https?:.+?)\\*"', res)
    if not m:
        return ""
    url = re.sub(r"\\+u([0-9a-fA-F]{4})", lambda x: chr(int(x.group(1), 16)), m.group(1))
    return url.replace("\\/", "/")


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


_fails = {}  # 기사 링크 -> 마지막 조회 실패 시각
_bing_last = {"t": 0.0}
_bing_block = {"until": 0.0}
_bing_lock = threading.Lock()


def same_site(url, domain):
    """url 의 사이트가 domain(예: energydaily.co.kr)과 같은 신문사 사이트인지. www./m./mobile. 은 무시한다."""
    host = re.sub(r"^(www|m|mobile)\.", "", urllib.parse.urlparse(url).hostname or "")
    return bool(domain and host and (host == domain or host.endswith("." + domain) or domain.endswith("." + host)))


def bing_find_url(title, domain):
    """같은 신문사(domain)에서 낸 같은 제목의 기사를 빙 뉴스 RSS 에서 찾아 원문 주소를 돌려준다(제목 유사도 0.5 이상).
    없으면 ''. 다른 신문사의 비슷한 기사는 작성자가 다를 수 있어 쓰지 않는다. domain 을 모르면 찾지 않는다.
    빙 링크에는 원문 주소가 그대로 들어 있어 구글처럼 주소를 풀 필요가 없다."""
    if not domain:
        return ""
    clean = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", title)
    clean = re.sub(r"\s+", " ", clean).strip()
    # site:신문사주소 로 그 신문사 기사만 검색한다(시험: 40건 중 일치 21건 -> 28건). 제목 앞 25자 -> 못 찾으면 제목 전체
    queries = [f"site:{domain} {q}" for q in dict.fromkeys([clean[:25].strip(), clean]) if q]
    g = _grams(title)
    for q in queries:
        with _bing_lock:  # 한 서버에서는 순서대로, 0.4초 이상 간격
            wait = 0.4 - (time.time() - _bing_last["t"])
            if wait > 0:
                time.sleep(wait)
            _bing_last["t"] = time.time()
        u = "https://www.bing.com/news/search?q=" + urllib.parse.quote(q) + "&format=rss&setmkt=ko-KR&setlang=ko"
        root = ET.fromstring(urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": _BROWSER_UA}), timeout=10).read())
        best_sim, best = 0.0, ""
        for it in root.iter("item"):
            real = urllib.parse.parse_qs(urllib.parse.urlparse(it.findtext("link") or "").query).get("url", [""])[0]
            if not real or not same_site(real, domain):
                continue
            gg = _grams(it.findtext("title") or "")
            sim = len(g & gg) / max(1, len(g | gg))
            if sim > best_sim:
                best_sim, best = sim, real
        if best_sim >= 0.5:
            return best
    return ""


def author_for_article(link, title, domain=""):
    """기자 이름 조회. ① 빙에서 **같은 신문사의** 같은 제목 기사를 찾아 그 원문에서 읽는다 ② 못 찾으면 구글 링크를 풀어서 읽는다.
    반환: (이름, 상태, 출처) 상태 = ok(이름이 비어 있을 수 있음) / blocked(구글·빙 모두 막힘) / fail.
    출처 = mem(서버가 이미 알고 있어 외부에 묻지 않음) / bing / google (화면이 '느린 조회'를 세는 데 쓴다)"""
    if link in _authors:
        return _authors[link], "ok", "mem"
    if time.time() - _fails.get(link, 0) < 300:  # 방금 실패한 기사는 5분간 다시 묻지 않는다
        return "", "fail", "mem"
    bing_blocked = time.time() < _bing_block["until"]
    if title and not bing_blocked:
        try:
            url = bing_find_url(title, domain)
            if url:
                page = _get_page(url)
                name = page_author(page)
                if not name:
                    canon = _canonical(page, url)
                    if canon:
                        try:
                            name = page_author(_get_page(canon, timeout=8))
                        except Exception:
                            pass
                _authors[link] = name
                return name, "ok", "bing"
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                _bing_block["until"] = time.time() + 60
                bing_blocked = True
        except Exception:
            pass
    name, status = author_for_google(link)
    if status == "blocked" and not bing_blocked:
        status = "fail"  # 구글만 막힘: 빙은 계속 쓸 수 있으니 이 기사만 건너뛴다
    if status == "fail":
        _fails[link] = time.time()
    return name, status, "google"


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
        page = _get_page(url)
    except Exception:
        return "", "fail"
    name = page_author(page)
    if not name:
        # 구글이 알려 준 주소가 AMP·모바일 버전이면 기자 이름이 빠져 있다 -> 원래(canonical) 기사 주소로 한 번 더.
        canon = _canonical(page, url)
        if canon:
            try:
                name = page_author(_get_page(canon, timeout=8))
            except Exception:
                pass
    _authors[link] = name
    return name, "ok"


def _get_page(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(400000).decode("utf-8", "replace")


def _canonical(page, url):
    """페이지의 <link rel="canonical"> 주소. 없으면 AMP 주소 규칙(…Amp.html, /amp/)을 되돌려 본다."""
    for m in re.finditer(r"<link\b[^>]*>", page, re.I):
        tag = m.group(0)
        if re.search(r'rel=["\']canonical["\']', tag, re.I):
            h = re.search(r'href=["\']([^"\']+)["\']', tag)
            if h and h.group(1) != url:
                return urllib.parse.urljoin(url, html.unescape(h.group(1)))
    guess = url.replace("articleViewAmp.html", "articleView.html").replace("/amp/", "/").replace("view_amp.html", "view.html")
    return guess if guess != url else ""


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


def collect_tab(tab_id, days, fast=False):
    """탭 하나의 기사를 수집한다. 지역 신문은 local 탭(새울본부)에서만 함께 읽는다."""
    tab = TABS.get(tab_id)
    if not tab:
        return {"error": "알 수 없는 탭입니다."}
    use_local = set(TABS[MAIN_TAB]["keywords"]) if tab.get("all") else bool(tab.get("local"))
    data = collect(days, tab["keywords"], fast=fast, use_local=use_local)
    data["tab"] = tab_id
    return data


def collect(days, kws=None, fast=False, use_local=True):
    """fast=True 면 구글 뉴스만(빠른 첫 화면). 아니면 use_local 일 때 지역 신문까지."""
    kws = [k for k in (kws or KEYWORDS)][:60]

    def sources_for(kw):  # use_local: True(전부) / 키워드 집합(그 키워드만) / False
        if fast or not use_local or not (use_local is True or kw in use_local):
            return SOURCES[:1]
        return SOURCES
    jobs = [(kw, name, fn) for kw in kws for name, fn in sources_for(kw)]
    merged, failed = {}, {}
    with ThreadPoolExecutor(max(1, len(jobs))) as ex:
        futs = [(kw, name, ex.submit(_cached, name, fn, kw, days)) for kw, name, fn in jobs]
    for kw, name, f in futs:
        try:
            for a in f.result():
                if kw in TITLE_REQUIRED and not title_relevant(kw, a["title"]):
                    continue  # 본문에만 단어가 스친 기사(관련 없음)
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
    if not fast and use_local:
        fill_authors(arts)
    cluster(arts)
    return {"articles": arts, "errors": list(failed.values()), "keywords": kws,
            "fetched": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")}


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


def weekly_summary(days=7, tab_id=None):
    """탭 하나의 최근 days 일 기사를 AI 로 요약한다(탭마다 따로, 30분 서버 기억 + CDN 1시간 공유)."""
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return {"error": "GEMINI_API_KEY 또는 ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다."}
    tab_id = tab_id if tab_id in TABS else MAIN_TAB
    ck = (days, tab_id)
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    data = collect_tab(tab_id, days)
    if data.get("error"):
        return data
    groups = {}
    for a in data["articles"]:
        if not a["spam"]:
            groups.setdefault(a["gid"], []).append(a)
    ordered = sorted(groups.values(), key=len, reverse=True)[:60]
    lines = [f"- ({len(g)}건) {g[0]['title']} / {', '.join(sorted({x['source'] for x in g})[:4])}"
             for g in ordered]
    if not groups:
        return {"summary": "최근 기간에 이 탭의 기사가 없어 요약할 내용이 없습니다.", "count": 0, "groups": 0,
                "generated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "tab": tab_id}
    name = TABS[tab_id]["name"]
    kwtxt = "" if TABS[tab_id].get("all") else f"('{'·'.join(data['keywords'])}')"
    prompt = (f"아래는 최근 {days}일간 한국수력원자력(한수원) '{name}' 관련{kwtxt} 뉴스를 "
              "유사 기사끼리 묶은 목록입니다(괄호는 보도 건수).\n"
              "한국어로 이번 주 주요 이슈를 요약해 주세요. 형식: 먼저 2~3문장 총평, 이어서 "
              "건수가 많은 순으로 주요 이슈 3~6개를 '- **이슈명**: 한두 문장 설명' 형태의 목록으로. "
              "목록에 없는 내용은 추측하지 마세요.\n\n" + "\n".join(lines))
    try:
        text = _ask_llm(prompt)
    except Exception as e:
        return {"error": f"AI 요약 호출 실패: {e}"}
    out = {"summary": text, "count": sum(map(len, groups.values())), "groups": len(groups),
           "generated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "tab": tab_id}
    _cache[ck] = (time.time(), out)
    return out
