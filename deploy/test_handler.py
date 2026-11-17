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
check("상태: 키 없음·에이전트 없음", (s, b["key_registered"], b["agent_available"]), (200, False, False))
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
check("에이전트 실행 403", call("POST", "/api/agent-run", body={})[0], 403)
check("없는 경로 404", call("GET", "/etc/passwd")[0], 404)
print("\n결과:", "OK" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
