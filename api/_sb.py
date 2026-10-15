"""Supabase REST(PostgREST)·Storage 를 표준 라이브러리만으로 부르는 얇은 도우미.

환경변수: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (서버에서만 쓴다. 화면으로 내려가지 않는다)
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BUCKET = "banners"


class SBError(Exception):
    pass


def _cfg():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or "").strip()
    return url, key


def configured():
    url, key = _cfg()
    return bool(url and key)


def public_url(name):
    return "%s/storage/v1/object/public/%s/%s" % (_cfg()[0], BUCKET, urllib.parse.quote(name))


def own_object_name(url):
    """우리 버킷에 올린 이미지 주소면 파일 이름을, 아니면 None."""
    prefix = "%s/storage/v1/object/public/%s/" % (_cfg()[0], BUCKET)
    if url and url.startswith(prefix):
        return urllib.parse.unquote(url[len(prefix):])
    return None


def _call(method, url, key, data=None, headers=None, timeout=15):
    h = {"apikey": key, "Authorization": "Bearer " + key}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise SBError("Supabase %s %s: %s" % (method, e.code, e.read()[:200].decode("utf-8", "replace")))
    except Exception as e:
        raise SBError("Supabase 접속 실패 (%s)" % type(e).__name__)


def rest(method, table, query="", body=None):
    """PostgREST 호출. 변경(POST/PATCH)은 바뀐 행을 돌려받는다."""
    url, key = _cfg()
    h = {"Content-Type": "application/json"}
    if method in ("POST", "PATCH"):
        h["Prefer"] = "return=representation"
    raw = _call(method, "%s/rest/v1/%s%s" % (url, table, ("?" + query) if query else ""), key,
                json.dumps(body).encode() if body is not None else None, h)
    return json.loads(raw) if raw else None


def storage_put(name, data, ctype):
    url, key = _cfg()
    _call("POST", "%s/storage/v1/object/%s/%s" % (url, BUCKET, urllib.parse.quote(name)), key, data,
          {"Content-Type": ctype, "x-upsert": "false", "Cache-Control": "max-age=31536000"}, timeout=30)
    return public_url(name)


def storage_delete(name):
    url, key = _cfg()
    try:
        _call("DELETE", "%s/storage/v1/object/%s/%s" % (url, BUCKET, urllib.parse.quote(name)), key)
    except SBError:
        pass  # 이미 없어도 상관없다
