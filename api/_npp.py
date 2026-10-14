"""열린원전운영정보(npp.khnp.co.kr) 메인 화면의 실시간 운영현황을 읽어 온다.

공개된 화면이 쓰는 것과 같은 주소만 호출한다.
  GET  /                              : 설비용량·발전량·운영 기수, 본부별 호기 운전/정비 상태(HTML)
  POST /branch-operation-info         : 본부 호기별 상태·원자로출력(%)·발전기출력(MWe)
  POST /branch-radiation-level-info   : 주변지역 방사선량
  POST /branch-weather-info           : 본부 기상(기온·습도·강수·풍속)
"""
import html as _html
import http.cookiejar
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

BASE = "https://npp.khnp.co.kr"
UA = "Mozilla/5.0 (compatible; khnp-news-scrap)"
KST = timezone(timedelta(hours=9))
# 화면(onClickBranchPin)이 쓰는 본부 코드: 이름 -> (branchCd, branchCd2)
BRANCHES = {"고리": ("BR0302", "2100"), "한빛": ("BR0303", "2300"), "월성": ("BR0305", "2200"),
            "한울": ("BR0304", "2400"), "새울": ("BR0312", "2800")}
_PTU = {"INFO1": "frstPtuCd", "INFO2": "scndPtuCd", "INFO3": "thirdPtuCd", "INFO4": "forthPtuCd", "INFO5": "ffthPtuCd",
        "INFO6": "sxthPtuCd", "INFO7": "svnthPtuCd", "INFO8": "eghthPtuCd", "INFO9": "ninthPtuCd", "INFO10": "tenthPtuCd"}


class _Client:
    """쿠키를 유지하는 작은 HTTP 클라이언트(화면이 먼저 세션을 받은 뒤 AJAX 를 부르는 것과 같게)."""

    def __init__(self, timeout=10):
        self.timeout = timeout
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, path):
        req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept-Language": "ko"})
        return self.op.open(req, timeout=self.timeout).read().decode("utf-8", "replace")

    def post(self, path, body):
        req = urllib.request.Request(
            BASE + path, data=json.dumps(body).encode(), method="POST",
            headers={"User-Agent": UA, "Content-Type": "application/json; charset=UTF-8", "Accept": "application/json",
                     "X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": BASE + "/"})
        return json.loads(self.op.open(req, timeout=self.timeout).read().decode("utf-8", "replace"))


def _txt(s):
    return _html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def parse_main(page):
    """메인 HTML -> {"summary": {...}, "branches": {이름: {"units": [{name, state}]}}}"""
    summary = {}
    for m in re.finditer(r'<div class="blue-info">(.*?)</div>\s*</div>', page, re.S):
        block = m.group(1)
        title = _txt(re.search(r"<p>(.*?)</p>", block, re.S).group(1)) if re.search(r"<p>", block) else ""
        spans = [_txt(x) for x in re.findall(r"<span>(.*?)</span>", block, re.S)]
        if "설비용량" in title:
            summary["capacity"] = spans[0] if spans else ""
        elif "발전량" in title:
            summary["generation"] = spans[0] if spans else ""
        elif "운영현황" in title:
            summary["units_total"] = spans[0] if spans else ""
            summary["units_running"] = spans[1] if len(spans) > 1 else ""
    nums = re.findall(r"\d+", summary.get("units_total", "")), re.findall(r"\d+", summary.get("units_running", ""))
    summary["total"] = int(nums[0][0]) if nums[0] else None
    summary["running"] = int(nums[1][0]) if nums[1] else None

    branches = {}
    for chunk in re.split(r'<div class="map-point ', page)[1:]:
        m = re.search(r"onClickBranchPin\(event,\s*'(\w+)',\s*'(\d+)'\)\"?>\s*([^<]+?)\s*</a>", chunk)
        if not m:
            continue
        units = []
        for u in re.finditer(r'unitCd=\d+"><span class="(\w+)" title="([^"]*)"></span>\s*([^<]+?)\s*</a>', chunk):
            units.append({"name": _txt(u.group(3)), "state": _txt(u.group(2)) or ("운영중" if u.group(1) == "circle" else "정비중")})
        branches[_txt(m.group(3))] = {"units": units}
    return {"summary": summary, "branches": branches}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_weather(res):
    rows = (res or {}).get("weatherInfoList") or []
    out = {"time": None}
    for r in rows:
        key = {"온도": "temp", "습도": "humidity", "풍속": "wind", "강우량": "rain"}.get(r.get("EXPL"))
        if key:
            out[key] = _num(r.get("VALUE"))
        if r.get("EXPL") == "온도":
            out["time"] = r.get("TIME")
    if out["time"] is None and rows:
        out["time"] = rows[0].get("TIME")
    return out


def radiation_status(value, tcheck):
    if tcheck == "N":
        return "점검"
    v = _num(value) or 0
    return "비상" if v >= 1000 else "경고" if v >= 1 else "정상"


def parse_radiation(res):
    """화면과 같이 이름이 'STD.C' 로 끝나는 측정값만 쓴다. -> {"max", "status", "name", "count"}"""
    items = [r for r in ((res or {}).get("radiationLevelInfoList") or []) if str(r.get("NAME", "")).endswith("STD.C")]
    vals = [(_num(r.get("VALUE")), r) for r in items if _num(r.get("VALUE")) is not None]
    if not vals:
        return None
    v, r = max(vals, key=lambda x: x[0])
    return {"max": v, "name": r.get("EXPL"), "status": radiation_status(v, r.get("TCHECK")), "count": len(vals), "time": r.get("TIME")}


def parse_operation(res):
    """-> {"name", "info", "units": [{name, state, reactor_pct, gen_mwe}]}"""
    res = res or {}
    plant = res.get("branchInfo") or {}
    name = res.get("branchName") or ""
    info = plant.get("msgCtt") or ""
    hq = name.replace(" 원자력", "")
    if plant.get("cd") == "1":
        info = hq + " 본부는 현재 " + info
    elif plant.get("cd") != "13":
        info = hq + " 원자력 " + info
    if plant.get("etc1"):
        info += " " + plant["etc1"]

    def out(rows, code):
        for r in rows or []:
            if r and r.get("VALUE") is not None and str(r.get("NAME", ""))[:4] == code:
                return _num(r["VALUE"])
        return 0.0

    units = []
    for u in res.get("unitInfoList") or []:
        uname = u.get("puCdNm") or ""
        uname = {"신고리3호기": "1호기", "신고리4호기": "2호기"}.get(uname, uname)
        running = plant.get(_PTU.get(u.get("ptuNo"), "")) == "KH1201"
        units.append({"name": uname, "state": "운영중" if running else "정비중",
                      "reactor_pct": out(res.get("nuclearOutput"), u.get("trgtPuCd")) if running else None,
                      "gen_mwe": out(res.get("generatorOutput"), u.get("trgtPuCd")) if running else None})
    return {"name": name, "info": info, "units": units}


def _branch(client, name):
    cd, cd2 = BRANCHES[name]
    errs, out = [], {}
    for key, path, body, parse in (
            ("operation", "/branch-operation-info", {"branchCd": cd, "branchCd2": cd2}, parse_operation),
            ("radiation", "/branch-radiation-level-info", {"branchCd": cd2}, parse_radiation),
            ("weather", "/branch-weather-info", {"branchCd": cd2}, parse_weather)):
        try:
            out[key] = parse(client.post(path, body))
        except Exception as e:  # 한 항목이 실패해도 나머지는 보여 준다
            out[key] = None
            errs.append("%s %s: %s" % (name, key, type(e).__name__ + (" " + str(e)[:60] if str(e) else "")))
    return name, out, errs


def fetch_all():
    errors = []
    client = _Client()
    try:
        main = parse_main(client.get("/"))
    except Exception as e:
        return {"error": "열린원전운영정보 접속 실패 (%s %s)" % (type(e).__name__, str(e)[:80])}
    branches = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        for name, data, errs in ex.map(lambda n: _branch(client, n), BRANCHES):
            errors += errs
            base = main["branches"].get(name, {})
            op = data.get("operation") or {}
            units = op.get("units") or base.get("units") or []
            branches[name] = {"units": units, "info": op.get("info", ""), "radiation": data.get("radiation"),
                              "weather": data.get("weather")}
    if not any(b["units"] for b in branches.values()) and not main["summary"].get("capacity"):
        return {"error": "열린원전운영정보 화면 형식을 읽지 못했습니다", "errors": errors}
    return {"source": BASE + "/", "fetched": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            "summary": main["summary"], "branches": branches, "order": list(BRANCHES), "errors": errors}
