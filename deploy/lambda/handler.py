"""공개 배포용 API (Lambda 함수 URL, CloudFront OAC 뒤에서만 호출됨).

경로: GET /api/status · GET /api/notices · GET /api/models · POST /api/judge
- 판정은 플러그인의 eligibility.evaluate()를, 공고 조회는 MCP 서버 모듈의 함수를 그대로 쓴다.
- 인증키는 SSM SecureString에서 콜드 스타트 때 읽어 모듈 변수(API_KEY)에만 둔다.
  환경변수·응답·로그에 내보내지 않는다.
- 요청 본문(개인 조건)은 기록하지 않는다. 판정 응답은 no-store, 공고 응답만 5분 캐시한다.
- 에이전트 실행(claude -p)은 비용 남용 방지를 위해 공개판에 없다.
"""
import base64
import json
import os
import time

import boto3

import applyhome_server as mcp
import eligibility

PARAM = os.environ["APPLYHOME_KEY_PARAM"]
MAX_BODY = 8 * 1024
NOTICE_ARGS = {"sido", "sigungu", "house_type", "only_open", "date_from", "date_to", "page"}
MODEL_ARGS = {"house_manage_no", "pblanc_no"}
CACHE_TTL = 300
_cache = {}


def _load_key():
    try:
        r = boto3.client("ssm").get_parameter(Name=PARAM, WithDecryption=True)
        return r["Parameter"]["Value"].strip() or None
    except Exception:  # 키가 없거나 권한이 없으면 판정만 동작
        return None


mcp.API_KEY = _load_key()


def _resp(code, obj, cache=False):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": f"public, max-age={CACHE_TTL}" if cache and code == 200 else "no-store",
            "X-Content-Type-Options": "nosniff",
        },
        "body": json.dumps(obj, ensure_ascii=False),
    }


def _cached(key, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    if len(_cache) > 200:
        _cache.pop(next(iter(_cache)))
    return val


def _profile_args(profile):
    if not isinstance(profile, dict):
        raise eligibility.InputError("프로필은 객체여야 합니다")
    args = []
    for k, v in profile.items():
        if v in (None, ""):
            continue
        if not isinstance(k, str) or not k.replace("_", "").isalnum():
            raise eligibility.InputError("허용되지 않은 항목 이름")
        args.append(f"{k}={'true' if v is True else 'false' if v is False else v}")
    return args


def handler(event, context):
    http = (event.get("requestContext") or {}).get("http") or {}
    method, path = http.get("method", "GET"), event.get("rawPath", "/")
    q = event.get("queryStringParameters") or {}
    try:
        if method == "GET" and path == "/api/status":
            return _resp(200, {"key_registered": bool(mcp.API_KEY), "agent_available": False,
                               "today": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9 * 3600))})
        if method == "GET" and path == "/api/notices":
            extra = set(q) - NOTICE_ARGS
            if extra:
                return _resp(400, {"error": "허용되지 않은 조회 항목: " + ", ".join(sorted(extra))})
            args = dict(q)
            if "only_open" in args:
                args["only_open"] = args["only_open"] != "false"
            key = "n:" + json.dumps(args, sort_keys=True, ensure_ascii=False)
            return _resp(200, _cached(key, lambda: mcp.search_notices(args)), cache=True)
        if method == "GET" and path == "/api/models":
            if set(q) - MODEL_ARGS:
                return _resp(400, {"error": "허용되지 않은 조회 항목"})
            key = "m:" + json.dumps(q, sort_keys=True)
            return _resp(200, _cached(key, lambda: mcp.get_notice_models(dict(q))), cache=True)
        if method == "POST" and path == "/api/judge":
            raw = event.get("body") or ""
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw).decode("utf-8")
            if not raw or len(raw.encode("utf-8")) > MAX_BODY:
                return _resp(400, {"error": "요청 본문 크기가 올바르지 않습니다"})
            body = json.loads(raw)
            return _resp(200, eligibility.evaluate(_profile_args(body.get("profile"))))
        if path == "/api/agent-run":
            return _resp(403, {"error": "공개판에서는 에이전트 실행을 제공하지 않습니다"})
        return _resp(404, {"error": "없는 경로"})
    except eligibility.InputError as e:
        return _resp(400, {"error": str(e)})
    except mcp.ToolError as e:
        return _resp(502, {"error": str(e)})
    except (ValueError, UnicodeDecodeError):
        return _resp(400, {"error": "요청을 해석할 수 없습니다"})
    except Exception:
        # 상세 내용(입력 값이 섞일 수 있음)은 기록하지 않는다
        return _resp(500, {"error": "처리 중 오류가 발생했습니다"})
