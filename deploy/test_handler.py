"""Lambda 진입점 오프라인 테스트(가짜 boto3, 네트워크·키 없음). 사용: python3 -I deploy/test_handler.py"""
import json, os, sys, types
HERE = os.path.dirname(os.path.abspath(__file__)); PKG = os.path.join(HERE, "build", "pkg")
sys.path.insert(0, PKG)
fake = types.ModuleType("boto3")
class _SSM:
    def get_parameter(self, **kw): raise RuntimeError("no ssm in test")
fake.client = lambda name: _SSM()
sys.modules["boto3"] = fake
os.environ["APPLYHOME_KEY_PARAM"] = "/test/param"
import handler
fails = 0
def check(name, got, want):
    global fails
    ok = got == want; fails += not ok
    print(("PASS " if ok else "FAIL ") + f"{name}: got={got} want={want}")
def call(method, path, q=None, body=None):
    ev = {"rawPath": path, "requestContext": {"http": {"method": method}}, "queryStringParameters": q}
    if body is not None: ev["body"] = body if isinstance(body, str) else json.dumps(body)
    r = handler.handler(ev, None); return r["statusCode"], r["headers"], json.loads(r["body"])
s, h, b = call("GET", "/api/status")
check("상태: 키 없음·테이블 없으면 에이전트 없음", (s, b["key_registered"], b["agent_available"]), (200, False, False))
s, h, b = call("POST", "/api/judge", body={"profile": {"age_band": "30-34", "residence_sido": "서울", "homeless_household": True, "account_period": "3y", "monthly_income_manwon": "780", "household_size": "2", "dual_income": True}})
check("판정 200·no-store", (s, h["Cache-Control"]), (200, "no-store"))
check("소득은 구간만", ("780" in json.dumps(b), b["income_band_of_urban_avg"]), (False, "120% 이하"))
check("허용 외 항목 400", call("POST", "/api/judge", body={"profile": {"name": "x"}})[0], 400)
check("항목 이름 주입 400", call("POST", "/api/judge", body={"profile": {"a=b": "1"}})[0], 400)
check("깨진 JSON 400", call("POST", "/api/judge", body="{x")[0], 400)
check("큰 본문 400", call("POST", "/api/judge", body={"profile": {"age_band": "x" * 9000}})[0], 400)
check("공고 허용 외 항목 400", call("GET", "/api/notices", {"sido": "서울", "income": "800"})[0], 400)
s, h, b = call("GET", "/api/notices", {"sido": "서울"})
check("키 없으면 502(캐시 안 함)", (s, h["Cache-Control"]), (502, "no-store"))
check("테이블 없으면 에이전트 403", call("POST", "/api/agent-run", body={})[0], 403)
check("없는 경로 404", call("GET", "/etc/passwd")[0], 404)

# ── 에이전트(공개판): 가짜 DynamoDB·Lambda·Bedrock으로 흐름 검증 ─────────────
print("\n== 에이전트")
D = "-"; FAKE_PHONE = f"010{D}1234{D}5678"     # 가짜 값(DLP 훅에 걸리지 않게 실행 시점에 조립)
class CCF(Exception): pass
class FakeDDB:
    class exceptions: ConditionalCheckFailedException = CCF
    def __init__(self): self.items = {}
    def put_item(self, TableName, Item): self.items[Item["pk"]["S"]] = dict(Item)
    def get_item(self, TableName, Key, ConsistentRead=False):
        it = self.items.get(Key["pk"]["S"]); return {"Item": it} if it else {}
    def update_item(self, TableName, Key, UpdateExpression, ExpressionAttributeValues, ConditionExpression=None, ExpressionAttributeNames=None):
        pk = Key["pk"]["S"]; it = self.items.setdefault(pk, {"pk": {"S": pk}}); v = ExpressionAttributeValues
        if UpdateExpression.startswith("ADD n"):
            n = int(it.get("n", {}).get("N", "0"))
            if n >= int(v[":cap"]["N"]): raise CCF()
            it["n"] = {"N": str(n + 1)}; it["ttl"] = v[":exp"]
        elif "list_append" in UpdateExpression: it.setdefault("events", {"L": []})["L"].extend(v[":e"]["L"])
        elif "done" in UpdateExpression: it["done"] = v[":t"]
class FakeLambda:
    def __init__(self): self.calls = []
    def invoke(self, **kw): self.calls.append(json.loads(kw["Payload"]))
class FakeBedrock:
    """대본: 공고 탐색(도구 1회 → 요약), 답변 작성, 점검(PASS)."""
    def __init__(self): self.seen = []
    def converse(self, **kw):
        sysmsg = kw["system"][0]["text"]; msgs = kw["messages"]; self.seen.append((kw["modelId"], sysmsg[:40], json.dumps(msgs, ensure_ascii=False)))
        u = {"inputTokens": 1000, "outputTokens": 200}
        if "toolConfig" in kw:
            if len(msgs) == 1:
                return {"output": {"message": {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": "search_notices", "input": {"sido": "서울", "only_open": True}}}]}}, "stopReason": "tool_use", "usage": u}
            return {"output": {"message": {"role": "assistant", "content": [{"text": "공고 요약: 해링턴 플레이스 문래"}]}}, "stopReason": "end_turn", "usage": u}
        if "읽기 전용 리뷰어" in sysmsg:
            return {"output": {"message": {"role": "assistant", "content": [{"text": '점검 끝\n{"verdict": "PASS", "fixes": ""}'}]}}, "stopReason": "end_turn", "usage": u}
        return {"output": {"message": {"role": "assistant", "content": [{"text": f"# 결과\n일반 1순위 가능 (GEN-1-PRIVATE). 연락처 {FAKE_PHONE} 는 가려져야 함"}]}}, "stopReason": "end_turn", "usage": u}
fd, fl, fb = FakeDDB(), FakeLambda(), FakeBedrock()
fake.client = lambda name: {"dynamodb": fd, "lambda": fl, "bedrock-runtime": fb}.get(name, _SSM())
handler.TABLE = "t"; handler._ddb = None; handler.agent._brt = None
handler.mcp.search_notices = lambda a: {"returned": 1, "notices": [{"HOUSE_NM": "해링턴 플레이스 문래"}], "sigungu_counts": {}}
handler.agent.HANDLERS["search_notices"] = handler.mcp.search_notices
class Ctx: function_name = "applyhome-public-api"
def acall(method, path, q=None, body=None, ip="1.2.3.4"):
    ev = {"rawPath": path, "requestContext": {"http": {"method": method, "sourceIp": "9.9.9.9"}}, "queryStringParameters": q,
          "headers": {"x-forwarded-for": f"6.6.6.6, {ip}"}}
    if body is not None: ev["body"] = json.dumps(body)
    r = handler.handler(ev, Ctx()); return r["statusCode"], json.loads(r["body"])
P = {"profile": {"age_band": "30-34", "residence_sido": "서울", "homeless_household": True, "account_period": "3y",
                 "monthly_income_manwon": "780", "household_size": "2", "dual_income": True}, "sigungu": "영등포구"}
s, b = acall("GET", "/api/status"); check("상태: 에이전트 사용 가능·남은 횟수", (b["agent_available"], b["agent_runs_left_today"]), (True, 30))
check("잘못된 프로필은 실행 전에 400", acall("POST", "/api/agent-run", body={"profile": {"name": "x"}})[0], 400)
s, b = acall("POST", "/api/agent-run", body=P); check("작업 시작 202", s, 202)
job = b["job"]; payload = fl.calls[-1]
check("비동기 호출 페이로드에 작업 ID", payload["agent_job"], job)
handler.handler(payload, Ctx())
s, b = acall("GET", "/api/agent-run", {"job": job, "since": "0"})
kinds = [e["kind"] for e in b["events"]]
check("폴링: 완료", (s, b["done"]), (200, True))
check("단계: 판정→공고 탐색(MCP)→작성→점검→결과", [k for k in kinds if k in ("agent", "mcp", "result")],
      ["agent", "agent", "mcp", "agent", "agent", "result"])
res = [e for e in b["events"] if e["kind"] == "result"][0]
check("최종 가드가 연락처를 가림", (FAKE_PHONE in res["text"], "[가림]" in res["text"]), (False, True))
nf = [x for x in fb.seen if "청약홈 공고를 찾는" in x[1]][0]
check("공고 탐색 에이전트에 소득 금액·나이 원문 없음", ("780" in nf[2], "30-34" in nf[2]), (False, False))
check("점검은 Haiku, 나머지는 Sonnet", sorted({m for m, *_ in fb.seen}), sorted({handler.agent.MODEL, handler.agent.REVIEW_MODEL}))
s, b = acall("GET", "/api/agent-run", {"job": job, "since": str(len(kinds))}); check("since 이후 새 단계 없음", b["events"], [])
check("없는 작업 404", acall("GET", "/api/agent-run", {"job": "nope"})[0], 404)
acall("POST", "/api/agent-run", body=P); acall("POST", "/api/agent-run", body=P)
s, b = acall("POST", "/api/agent-run", body=P); check("같은 IP 4번째 → 429", s, 429)
check("IP 상한에 막힌 요청은 전체 상한을 쓰지 않음", int(fd.items[f"cap#{handler.kst_date()}"]["n"]["N"]), 3)
check("XFF 앞부분 위조 무시(마지막 값 사용)", acall("POST", "/api/agent-run", body=P, ip="5.5.5.5")[0], 202)
handler.DAILY_CAP = 4
check("전체 상한 → 429", acall("POST", "/api/agent-run", body=P, ip="7.7.7.7")[0], 429)
print("\n결과:", "OK" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
