"""MCP 서버 오프라인 테스트(네트워크·키 없이 내부 함수 검증). 사용: python3 -I tests/test_mcp_server.py"""
import importlib.util, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.join(HERE, "..", "mcp", "applyhome_server.py")
spec = importlib.util.spec_from_file_location("srv", SRV); srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)
fails = 0
def check(name, got, want):
    global fails
    ok = got == want; fails += not ok
    print(("PASS " if ok else "FAIL ") + f"{name}: got={got} want={want}")

remndr = {"SUBSCRPT_RCEPT_ENDDE": "2026-09-28", "CNTRCT_CNCLS_ENDDE": "2026-12-31", "HSSPLY_ADRES": "서울특별시 중구 청계천로 1"}
check("무순위: 계약일 아닌 접수 마감일 사용", srv._end_date(remndr), "2026-09-28")
check("APT: RCEPT_ENDDE 사용", srv._end_date({"RCEPT_ENDDE": "2026-11-19", "CNTRCT_CNCLS_ENDDE": "2027-01-01"}), "2026-11-19")
check("주소로 시·도 판별(SUBSCRPT_AREA 없음)", srv._in_sido({"HSSPLY_ADRES": "서울특별시 강남구 x"}, "서울"), True)
check("주소로 시·도 판별(다른 시·도)", srv._in_sido({"HSSPLY_ADRES": "경기도 성남시 x"}, "서울"), False)
check("구 추출", srv._sigungu(remndr), "중구")
check("날짜 필드 보존", sorted(k for k in srv._pick(remndr, srv.NOTICE_FIELDS) if k.endswith("DE")), ["CNTRCT_CNCLS_ENDDE", "SUBSCRPT_RCEPT_ENDDE"])

os.environ["APPLYHOME_API_KEY"] = "FAKE+key/for==test0123456789abcdef"
k = os.environ["APPLYHOME_API_KEY"]
masked = srv._mask(f"url?serviceKey={k} and {srv.urllib.parse.quote(k, safe='')}")
check("키 원문·인코딩 모두 마스킹", (k in masked, "FAKE%2Bkey" in masked), (False, False))

def rpc(*msgs):
    env = {k: v for k, v in os.environ.items() if k != "APPLYHOME_API_KEY"}
    p = subprocess.run([sys.executable, "-I", SRV], input="\n".join(json.dumps(m) for m in msgs), capture_output=True, text=True, env=env)
    return [json.loads(l) for l in p.stdout.splitlines()]
out = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
          {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search_notices", "arguments": {"sido": "서울", "income": "800"}}},
          {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_notices", "arguments": {"sigungu": "a.com"}}})
check("도구 2개", len(out[0]["result"]["tools"]), 2)
check("스키마 밖 입력(개인정보) 거부", out[1]["result"]["isError"], True)
check("잘못된 구 이름 거부", out[2]["result"]["isError"], True)
print("\n결과:", "OK" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
