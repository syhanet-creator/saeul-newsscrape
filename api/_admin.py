"""관리자 모드 + 광고 배너 로직.

공개: public_banners()            -> 노출 중인 배너 (화면 상단에 표시)
관리: handle(method, path, ...)   -> /api/admin?op=login|logout|me|list|save|delete  (비밀번호 로그인 필요)

환경변수: ADMIN_PASSWORD(필수), ADMIN_SECRET(선택: 로그인 서명 키), SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.parse
from datetime import datetime, timezone

import _sb

SESSION_SEC = 8 * 3600
MAX_IMAGE = 2_500_000
TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
FIELDS = "id,caption,image_url,link_url,active,start_at,end_at,sort,created_at"


# ---------- 로그인 세션(서명된 쿠키) ----------
def _password():
    return os.environ.get("ADMIN_PASSWORD", "")


def _secret():
    return (os.environ.get("ADMIN_SECRET") or (_password() + "|" + _sb._cfg()[1])).encode()


def make_token(now=None):
    exp = str(int((now or time.time()) + SESSION_SEC))
    return exp + "." + hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()


def verify_token(tok, now=None):
    try:
        exp, sig = tok.split(".", 1)
        ok = hmac.compare_digest(sig, hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest())
        return ok and int(exp) > (now or time.time())
    except Exception:
        return False


def _cookie(headers):
    c = {}
    for part in (headers.get("Cookie") or headers.get("cookie") or "").split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            c[k] = v
    return c.get("adm", "")


# ---------- 입력 검증 ----------
def _url(v, field, allow_empty=True):
    v = (v or "").strip()
    if not v:
        if allow_empty:
            return ""
        raise ValueError(field + " 을(를) 입력하세요")
    if len(v) > 800 or not re.match(r"^https?://[^\s]+$", v, re.I):
        raise ValueError(field + " 은(는) http:// 또는 https:// 로 시작하는 주소여야 합니다")
    return v


def _date(v):
    v = (v or "").strip() if isinstance(v, str) else ""
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("날짜 형식이 올바르지 않습니다")
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def clean_banner(d):
    out = {"caption": (d.get("caption") or "").strip()[:100], "link_url": _url(d.get("link_url"), "링크"),
           "active": bool(d.get("active", True)), "start_at": _date(d.get("start_at")), "end_at": _date(d.get("end_at"))}
    try:
        out["sort"] = max(-9999, min(9999, int(d.get("sort") or 0)))
    except (TypeError, ValueError):
        out["sort"] = 0
    if out["start_at"] and out["end_at"] and out["end_at"] < out["start_at"]:
        raise ValueError("종료일이 시작일보다 빠릅니다")
    return out


def _upload(data_url):
    m = re.match(r"^data:(image/[a-z+]+);base64,(.+)$", data_url or "", re.S)
    if not m or m.group(1) not in TYPES:
        raise ValueError("이미지는 JPG·PNG·WEBP·GIF 만 올릴 수 있습니다")
    raw = base64.b64decode(m.group(2), validate=False)
    if len(raw) > MAX_IMAGE:
        raise ValueError("이미지가 너무 큽니다(2.5MB 이하)")
    name = "%s-%s.%s" % (time.strftime("%Y%m%d"), secrets.token_hex(6), TYPES[m.group(1)])
    return _sb.storage_put(name, raw, m.group(1))


# ---------- 공개: 노출 중인 배너 ----------
def _live(b, now):
    if not b.get("active"):
        return False
    for key, cmp in (("start_at", lambda t: t <= now), ("end_at", lambda t: now <= t)):
        if b.get(key):
            try:
                t = datetime.fromisoformat(b[key].replace("Z", "+00:00"))
            except ValueError:
                return False
            if not cmp(t):
                return False
    return True


def public_banners(now=None):
    if not _sb.configured():
        return []
    now = now or datetime.now(timezone.utc)
    rows = _sb.rest("GET", "banners", "select=%s&active=eq.true&order=sort.asc,id.asc" % FIELDS) or []
    return [{"id": b["id"], "image": b["image_url"], "link": b.get("link_url") or "", "caption": b.get("caption") or ""}
            for b in rows if _live(b, now)]


# ---------- 관리 API ----------
def handle(method, path, headers, body=b""):
    """-> (status, extra_headers, obj)"""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    op = (q.get("op") or [""])[0]
    if not _password() or not _sb.configured():
        missing = [n for n, ok in (("ADMIN_PASSWORD", bool(_password())), ("SUPABASE_URL", bool(_sb._cfg()[0])),
                                   ("SUPABASE_SERVICE_ROLE_KEY", bool(_sb._cfg()[1]))) if not ok]
        return 503, {}, {"error": "설정 필요", "missing": missing}
    authed = verify_token(_cookie(headers))
    if op == "me":
        return 200, {}, {"ok": authed}
    if method != "POST" and op != "list":
        return 405, {}, {"error": "허용되지 않는 요청"}
    if method == "POST":
        ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
        host = headers.get("Host") or headers.get("host") or ""
        origin = headers.get("Origin") or headers.get("origin") or ""
        if "application/json" not in ctype or (origin and urllib.parse.urlparse(origin).netloc != host):
            return 403, {}, {"error": "허용되지 않는 요청"}
    try:
        data = json.loads(body.decode("utf-8")) if body else {}
    except ValueError:
        return 400, {}, {"error": "요청 형식이 올바르지 않습니다"}

    if op == "login":
        if hmac.compare_digest(str(data.get("password", "")).encode(), _password().encode()):
            ck = "adm=%s; Path=/; Max-Age=%d; HttpOnly; Secure; SameSite=Strict" % (make_token(), SESSION_SEC)
            return 200, {"Set-Cookie": ck}, {"ok": True}
        time.sleep(1)  # 무차별 대입을 늦춘다
        return 401, {}, {"error": "비밀번호가 맞지 않습니다"}
    if op == "logout":
        return 200, {"Set-Cookie": "adm=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"}, {"ok": True}
    if not authed:
        return 401, {}, {"error": "로그인이 필요합니다"}
    try:
        if op == "list":
            return 200, {}, {"banners": _sb.rest("GET", "banners", "select=%s&order=sort.asc,id.asc" % FIELDS) or []}
        if op == "save":
            return 200, {}, {"banner": _save(data)}
        if op == "delete":
            return 200, {}, _delete(data)
    except ValueError as e:
        return 400, {}, {"error": str(e)}
    except _sb.SBError as e:
        return 502, {}, {"error": str(e)}
    return 400, {}, {"error": "알 수 없는 요청"}


def _save(d):
    row = clean_banner(d)
    bid = d.get("id")
    old = None
    if bid:
        found = _sb.rest("GET", "banners", "select=id,image_url&id=eq.%d" % int(bid))
        if not found:
            raise ValueError("해당 배너가 없습니다")
        old = found[0]["image_url"]
    if d.get("image_data"):
        row["image_url"] = _upload(d["image_data"])
    elif d.get("image_url"):
        row["image_url"] = _url(d["image_url"], "이미지 주소", allow_empty=False)
    elif old:
        row["image_url"] = old
    else:
        raise ValueError("이미지를 올리거나 이미지 주소를 입력하세요")
    if bid:
        res = _sb.rest("PATCH", "banners", "id=eq.%d" % int(bid), row)
    else:
        res = _sb.rest("POST", "banners", "", row)
    if old and old != row["image_url"] and _sb.own_object_name(old):
        _sb.storage_delete(_sb.own_object_name(old))
    return (res or [row])[0]


def _delete(d):
    bid = int(d.get("id") or 0)
    found = _sb.rest("GET", "banners", "select=id,image_url&id=eq.%d" % bid)
    if not found:
        raise ValueError("해당 배너가 없습니다")
    _sb.rest("DELETE", "banners", "id=eq.%d" % bid)
    name = _sb.own_object_name(found[0]["image_url"])
    if name:
        _sb.storage_delete(name)
    return {"ok": True}
