"""공개 배포용 API (Lambda 함수 URL, CloudFront OAC 뒤에서만 호출됨).

경로: GET /api/status · GET /api/notices · GET /api/models · POST /api/judge
- 판정은 플러그인의 eligibility.evaluate()를, 공고 조회는 MCP 서버 모듈의 함수를 그대로 쓴다.
- 인증키는 SSM SecureString에서 콜드 스타트 때 읽어 모듈 변수(API_KEY)에만 둔다.
  환경변수·응답·로그에 내보내지 않는다.
- 요청 본문(개인 조건)은 기록하지 않는다. 판정 응답은 no-store, 공고 응답만 5분 캐시한다.
- 에이전트 실행: POST /api/agent-run(작업 시작) · GET /api/agent-run?job=&since=(폴링).
  실행은 자기 자신을 비동기 호출해 agent.run()으로 Bedrock Claude 파이프라인을 돌린다.
  비용 상한: 하루 전체 DAILY_CAP회, 같은 IP(해시) IP_CAP회. 작업 결과는 DynamoDB에 15분 TTL로만 둔다.
"""
import base64
import hashlib
import json
import os
import secrets
import time

import boto3

import agent
import applyhome_server as mcp
import eligibility

PARAM = os.environ["APPLYHOME_KEY_PARAM"]
TABLE = os.environ.get("AGENT_TABLE", "")
DAILY_CAP = int(os.environ.get("DAILY_CAP", "30"))
IP_CAP = int(os.environ.get("IP_CAP", "3"))
JOB_TTL = 15 * 60
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
_ddb = None


def ddb():
    global _ddb
    if _ddb is None:
        _ddb = boto3.client("dynamodb")
    return _ddb


def kst_date():
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9 * 3600))


def viewer_ip(event):
    # CloudFront가 붙이는 X-Forwarded-For의 마지막 값이 CloudFront가 본 접속 IP
    xff = ((event.get("headers") or {}).get("x-forwarded-for") or "").split(",")
    return xff[-1].strip() if xff and xff[-1].strip() else ((event.get("requestContext") or {}).get("http") or {}).get("sourceIp", "")


def take_quota(ip_hash):
    """하루 전체·IP별 실행 횟수를 원자적으로 1 올린다. 상한이면 사유 문자열, 통과면 None."""
    today, exp = kst_date(), str(int(time.time()) + 2 * 86400)
    # IP 상한을 먼저 본다(한 사람의 반복 요청이 전체 상한을 소모하지 않도록)
    for pk, cap, why in ((f"ip#{ip_hash}#{today}", IP_CAP, f"같은 접속 환경에서는 하루 {IP_CAP}회까지 실행할 수 있습니다."),
                         (f"cap#{today}", DAILY_CAP, f"오늘 공개판 에이전트 실행 한도({DAILY_CAP}회)를 다 썼습니다. 내일 다시 시도해 주세요.")):
        try:
            ddb().update_item(TableName=TABLE, Key={"pk": {"S": pk}},
                              UpdateExpression="ADD n :one SET #t = :exp",
                              ConditionExpression="attribute_not_exists(n) OR n < :cap",
                              ExpressionAttributeNames={"#t": "ttl"},
                              ExpressionAttributeValues={":one": {"N": "1"}, ":cap": {"N": str(cap)}, ":exp": {"N": exp}})
        except ddb().exceptions.ConditionalCheckFailedException:
            return why
    return None


def quota_left():
    try:
        r = ddb().get_item(TableName=TABLE, Key={"pk": {"S": f"cap#{kst_date()}"}})
        used = int(r.get("Item", {}).get("n", {}).get("N", "0"))
    except Exception:
        return None
    return max(0, DAILY_CAP - used)


def job_emit(job_id):
    def emit(step):
        ddb().update_item(TableName=TABLE, Key={"pk": {"S": f"job#{job_id}"}},
                          UpdateExpression="SET events = list_append(events, :e)",
                          ExpressionAttributeValues={":e": {"L": [{"S": json.dumps(step, ensure_ascii=False)}]}})
    return emit


def run_worker(event):
    """비동기 호출로 들어온 에이전트 작업. 결과·단계는 DynamoDB 작업 항목에만 쌓는다."""
    job_id = event["agent_job"]
    emit = job_emit(job_id)
    try:
        agent.run(event["args"], event["region"], event.get("sigungu"), emit)
    except eligibility.InputError as e:
        emit({"kind": "blocked", "label": str(e)})
    except Exception as e:  # 상세(입력이 섞일 수 있음)는 남기지 않고 종류만
        emit({"kind": "blocked", "label": f"실행 오류: {type(e).__name__}"})
    finally:
        ddb().update_item(TableName=TABLE, Key={"pk": {"S": f"job#{job_id}"}},
                          UpdateExpression="SET done = :t", ExpressionAttributeValues={":t": {"BOOL": True}})
    return {"ok": True}


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
    if "agent_job" in event:                    # 비동기 작업(자기 자신이 호출, 외부에서는 올 수 없음)
        return run_worker(event)
    http = (event.get("requestContext") or {}).get("http") or {}
    method, path = http.get("method", "GET"), event.get("rawPath", "/")
    q = event.get("queryStringParameters") or {}
    try:
        if method == "GET" and path == "/api/status":
            return _resp(200, {"key_registered": bool(mcp.API_KEY), "agent_available": bool(TABLE),
                               "agent_runs_left_today": quota_left() if TABLE else 0,
                               "agent_engine": "Amazon Bedrock Claude" if TABLE else None, "today": kst_date()})
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
        if path == "/api/agent-run" and not TABLE:
            return _resp(403, {"error": "에이전트 실행이 설정되지 않았습니다"})
        if method == "GET" and path == "/api/agent-run":
            job = q.get("job", "")
            if not job or len(job) > 64:
                return _resp(404, {"error": "작업이 없거나 만료되었습니다"})
            it = ddb().get_item(TableName=TABLE, Key={"pk": {"S": f"job#{job}"}}, ConsistentRead=True).get("Item")
            if not it or int(it["ttl"]["N"]) < time.time():
                return _resp(404, {"error": "작업이 없거나 만료되었습니다(결과는 15분간만 보관)"})
            events = [json.loads(e["S"]) for e in it.get("events", {}).get("L", [])]
            try:
                since = max(0, int(q.get("since", "0")))
            except ValueError:
                since = 0
            return _resp(200, {"events": events[since:], "next": len(events), "done": it.get("done", {}).get("BOOL", False)})
        if method == "POST" and path == "/api/agent-run":
            raw = event.get("body") or ""
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw).decode("utf-8")
            if not raw or len(raw.encode("utf-8")) > MAX_BODY:
                return _resp(400, {"error": "요청 본문 크기가 올바르지 않습니다"})
            body = json.loads(raw)
            args = _profile_args(body.get("profile"))
            judged = eligibility.evaluate(args)      # 같은 검증을 먼저 통과해야 실행(실패 시 InputError → 400)
            sigungu = body.get("sigungu")
            if sigungu and not mcp.SIGUNGU_RE.match(sigungu):
                return _resp(400, {"error": "구 이름이 올바르지 않습니다"})
            ip_hash = hashlib.sha256(f"{viewer_ip(event)}|{kst_date()}|{PARAM}".encode()).hexdigest()[:24]
            why = take_quota(ip_hash)
            if why:
                return _resp(429, {"error": why})
            job_id = secrets.token_urlsafe(16)
            ddb().put_item(TableName=TABLE, Item={"pk": {"S": f"job#{job_id}"}, "events": {"L": []},
                                                  "done": {"BOOL": False}, "ttl": {"N": str(int(time.time()) + JOB_TTL)}})
            region = judged["notice_filters"]["sido"] + (f" {sigungu}" if sigungu else " 전체")
            boto3.client("lambda").invoke(FunctionName=context.function_name, InvocationType="Event",
                                          Payload=json.dumps({"agent_job": job_id, "args": args, "region": region,
                                                              "sigungu": sigungu}, ensure_ascii=False).encode())
            return _resp(202, {"job": job_id})
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
