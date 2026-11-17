"""화면 서버 오프라인 테스트(키·네트워크 없이). 사용: python3 -I web/test_server.py"""
import http.client, importlib.util, json, os, sys, threading
from http.server import ThreadingHTTPServer
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("web", os.path.join(HERE, "server.py")); web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
web.mcp.API_KEY = None
srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler); port = srv.server_address[1]; web.PORT = port
threading.Thread(target=srv.serve_forever, daemon=True).start()
fails = 0
def check(name, got, want):
    global fails
    ok = got == want; fails += not ok
    print(("PASS " if ok else "FAIL ") + f"{name}: got={got} want={want}")
def req(method, path, body=None, host=None, ctype="application/json"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    h = {"Host": host or f"127.0.0.1:{port}"}
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode(); h["Content-Type"] = ctype
    c.request(method, path, body=data, headers=h); r = c.getresponse(); b = r.read()
    return r.status, dict(r.getheaders()), b

s, h, b = req("GET", "/")
check("첫 화면 200", s, 200)
check("CSP self", "default-src 'self'" in h.get("Content-Security-Policy", ""), True)
check("no-store", h.get("Cache-Control"), "no-store")
check("프레임 금지", h.get("X-Frame-Options"), "DENY")
check("화면은 상대 경로 사용", (b'href="app.css"' in b, b'src="app.js"' in b), (True, True))
check("다른 Host 거부(DNS 리바인딩)", req("GET", "/api/status", host="evil.example")[0], 421)
s, h, b = req("GET", "/api/status"); st = json.loads(b)
check("키 없음 표시", st["key_registered"], False)
check("상태 응답에 키 값 없음", set(st), {"key_registered", "agent_busy", "today"})
s, _, b = req("POST", "/api/judge", {"profile": {"age_band": "30-34", "residence_sido": "서울", "homeless_household": True, "account_period": "3y", "monthly_income_manwon": "780", "household_size": "2", "dual_income": True}})
j = json.loads(b)
check("판정 200", s, 200)
check("소득은 구간만(금액·정확한 % 없음)", ("780" in b.decode(), j["income_band_of_urban_avg"]), (False, "120% 이하"))
check("허용 외 항목 400", req("POST", "/api/judge", {"profile": {"name": "x"}})[0], 400)
check("항목 이름 주입 400", req("POST", "/api/judge", {"profile": {"a=b c": "1"}})[0], 400)
check("JSON 아닌 요청 400", req("POST", "/api/judge", b"x=1", ctype="application/x-www-form-urlencoded")[0], 400)
check("큰 본문 400", req("POST", "/api/judge", {"profile": {"age_band": "x" * 9000}})[0], 400)
check("공고 허용 외 조회 항목 400", req("GET", "/api/notices?sido=%EC%84%9C%EC%9A%B8&income=800")[0], 400)
s, _, b = req("GET", "/api/notices?sido=%EC%84%9C%EC%9A%B8")
check("키 없으면 502 + 안내", (s, "인증키" in json.loads(b)["error"]), (502, True))
check("잘못된 구 이름 400/502", req("GET", "/api/notices?sido=%EC%84%9C%EC%9A%B8&sigungu=a.com")[0] in (400, 502), True)
check("없는 경로 404", req("GET", "/etc/passwd")[0], 404)
check("에이전트 실행도 같은 검증", req("POST", "/api/agent-run", {"profile": {"name": "x"}})[0], 400)
print("\n결과:", "OK" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
