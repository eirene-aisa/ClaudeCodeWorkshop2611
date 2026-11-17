#!/usr/bin/env python3
"""청약홈 분양정보 조회 MCP 서버 (stdio, 외부 의존성 없음).

- 호출 대상은 아래 BASE에 고정된 공공데이터포털 API뿐이며, URL을 입력으로 받지 않는다.
- 인증키는 환경변수 APPLYHOME_API_KEY에서만 읽는다(claude mcp add --env 로 등록).
- 도구 입력은 비개인 필터(시·도, 날짜, 주택 구분, 공고번호)만 허용한다.
- 응답·오류 문자열에서 키 값(원문·인코딩 형태)을 가린 뒤 돌려준다.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/"
ENDPOINTS = {
    "APT": "getAPTLttotPblancDetail",            # APT 분양정보
    "REMNDR": "getRemndrLttotPblancDetail",      # 무순위·잔여세대
    "OFFICETEL": "getUrbtyOfctlLttotPblancDetail",  # 오피스텔·도시형·민간임대
}
MODEL_ENDPOINT = "getAPTLttotPblancMdl"          # APT 주택형별 공급 세대수
SIDO = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
        "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SIGUNGU_RE = re.compile(r"^[가-힣]{1,10}(시|군|구)$")
# 주소 첫 단어 → 시·도 약칭 (무순위·오피스텔 API는 공급지역 조건을 서버에서 걸 수 없어 주소로 거른다)
SIDO_ALIASES = {
    "서울": ["서울특별시", "서울"], "부산": ["부산광역시", "부산"], "대구": ["대구광역시", "대구"],
    "인천": ["인천광역시", "인천"], "광주": ["광주광역시"], "대전": ["대전광역시", "대전"],
    "울산": ["울산광역시", "울산"], "세종": ["세종특별자치시", "세종"], "경기": ["경기도", "경기"],
    "강원": ["강원특별자치도", "강원도", "강원"], "충북": ["충청북도", "충북"], "충남": ["충청남도", "충남"],
    "전북": ["전북특별자치도", "전라북도", "전북"], "전남": ["전라남도", "전남"],
    "경북": ["경상북도", "경북"], "경남": ["경상남도", "경남"], "제주": ["제주특별자치도", "제주"],
}
NO_RE = re.compile(r"^\d{1,12}$")
NOTICE_FIELDS = [
    "HOUSE_MANAGE_NO", "PBLANC_NO", "HOUSE_NM", "HOUSE_SECD_NM", "HOUSE_DTL_SECD_NM",
    "RENT_SECD_NM", "SUBSCRPT_AREA_CODE_NM", "HSSPLY_ADRES", "TOT_SUPLY_HSHLDCO",
    "RCRIT_PBLANC_DE", "RCEPT_BGNDE", "RCEPT_ENDDE", "SPSPLY_RCEPT_BGNDE", "SPSPLY_RCEPT_ENDDE",
    "GNRL_RNK1_CRSPAREA_RCPTDE", "GNRL_RNK2_CRSPAREA_RCPTDE", "PRZWNER_PRESNATN_DE",
    "SPECLT_RDN_EARTH_AT", "MDAT_TRGET_AREA_SECD", "PARCPRC_ULS_AT", "PBLANC_URL",
]
MODEL_FIELDS = [
    "HOUSE_TY", "SUPLY_AR", "SUPLY_HSHLDCO", "SPSPLY_HSHLDCO", "MNYCH_HSHLDCO", "NWWDS_HSHLDCO",
    "LFE_FRST_HSHLDCO", "OLD_PARNTS_SUPORT_HSHLDCO", "INSTT_RECOMEND_HSHLDCO", "NWBB_HSHLDCO",
    "ETC_HSHLDCO", "LTTOT_TOP_AMOUNT",
]

TOOLS = [
    {
        "name": "search_notices",
        "description": "청약홈 분양 공고를 조회한다. 개인 조건은 받지 않고 지역·기간·주택 구분 필터만 받는다.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sido": {"type": "string", "enum": SIDO, "description": "공급 지역(시·도). 기본 서울"},
                "sigungu": {"type": "string", "pattern": SIGUNGU_RE.pattern, "description": "시·군·구 이름(예: 강남구). 주소로 거름"},
                "date_from": {"type": "string", "pattern": DATE_RE.pattern, "description": "모집공고일 시작(YYYY-MM-DD), 기본 60일 전"},
                "date_to": {"type": "string", "pattern": DATE_RE.pattern, "description": "모집공고일 끝(YYYY-MM-DD)"},
                "house_type": {"type": "string", "enum": list(ENDPOINTS), "description": "APT(기본) | REMNDR(무순위·잔여) | OFFICETEL"},
                "only_open": {"type": "boolean", "description": "접수 마감 전 공고만(기본 true)"},
                "page": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
    },
    {
        "name": "get_notice_models",
        "description": "APT 공고의 주택형별 공급 세대수(특별공급 종류별 배정 포함)를 조회한다.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["house_manage_no"],
            "properties": {
                "house_manage_no": {"type": "string", "pattern": NO_RE.pattern},
                "pblanc_no": {"type": "string", "pattern": NO_RE.pattern},
            },
        },
    },
]


class ToolError(Exception):
    pass


# 웹 화면 서버처럼 이 모듈을 import해서 쓰는 쪽은 키를 환경변수 대신 이 변수에 넣는다
# (환경변수는 /proc/<pid>/environ으로 같은 사용자에게 보이므로).
API_KEY = None


def _raw_key():
    return (API_KEY or os.environ.get("APPLYHOME_API_KEY", "")).strip()


def _key():
    k = _raw_key()
    if not k:
        raise ToolError("인증키가 등록되지 않았습니다. Claude 세션 밖 터미널에서 "
                        "'claude mcp add --scope local applyhome --env APPLYHOME_API_KEY=... -- python3 <이 파일>' 로 등록하세요.")
    return k


def _mask(text):
    k = _raw_key()
    if not k:
        return text
    for form in {k, urllib.parse.quote(k, safe=""), urllib.parse.unquote(k),
                 urllib.parse.quote(urllib.parse.unquote(k), safe="")}:
        if form:
            text = text.replace(form, "***")
    return text


def _call(endpoint, params):
    key = _key()
    # Encoding 키(이미 %XX 포함)는 그대로, Decoding 키는 한 번만 인코딩
    enc_key = key if "%" in key else urllib.parse.quote(key, safe="")
    query = urllib.parse.urlencode(params, safe=":[]") + "&serviceKey=" + enc_key
    url = BASE + endpoint + "?" + query
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ToolError(_mask(f"API 오류 HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}"))
    except Exception as e:  # 네트워크 오류 메시지에도 URL이 섞일 수 있어 가린다
        raise ToolError(_mask(f"API 호출 실패: {type(e).__name__}: {e}"))
    try:
        return json.loads(body)
    except ValueError:
        raise ToolError(_mask("API 응답을 해석할 수 없습니다: " + body[:200]))


def _pick(row, fields):
    # 지정 필드 + 엔드포인트마다 이름이 다른 날짜형 필드(…DE, …BGNDE, …ENDDE)를 함께 보존
    return {k: v for k, v in row.items()
            if v not in (None, "") and (k in fields or k.endswith("DE"))}


# 청약 접수 마감일 필드(엔드포인트마다 이름이 다름). 계약일(CNTRCT_*)은 접수 마감 판단에 쓰지 않는다.
RCEPT_END_FIELDS = ["RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE", "GNRL_RCEPT_ENDDE"]


def _end_date(row):
    for f in RCEPT_END_FIELDS:
        if row.get(f):
            return row[f]
    ends = [v for k, v in row.items() if k.endswith("RCEPT_ENDDE") and v]
    return max(ends) if ends else None


def _addr_tokens(row):
    return (row.get("HSSPLY_ADRES") or "").split()


def _in_sido(row, sido):
    if row.get("SUBSCRPT_AREA_CODE_NM"):
        return row["SUBSCRPT_AREA_CODE_NM"] == sido
    t = _addr_tokens(row)
    return bool(t) and t[0] in SIDO_ALIASES[sido]


def _sigungu(row):
    t = _addr_tokens(row)
    return t[1] if len(t) > 1 and SIGUNGU_RE.match(t[1]) else None


def search_notices(args):
    today = dt.date.today()
    date_from = args.get("date_from") or (today - dt.timedelta(days=60)).isoformat()
    for k in ("date_from", "date_to"):
        if k in args and not DATE_RE.match(args[k]):
            raise ToolError(f"{k} 형식은 YYYY-MM-DD")
    kind = args.get("house_type", "APT")
    if kind not in ENDPOINTS:
        raise ToolError("house_type 값이 올바르지 않습니다")
    sido = args.get("sido")
    if sido is not None and sido not in SIDO:
        raise ToolError("sido 값이 올바르지 않습니다")
    sigungu = args.get("sigungu")
    if sigungu is not None and not SIGUNGU_RE.match(sigungu):
        raise ToolError("sigungu는 '강남구'처럼 시·군·구 이름이어야 합니다")
    params = {"page": int(args.get("page", 1)), "perPage": 100,
              "cond[RCRIT_PBLANC_DE::GTE]": date_from}
    if args.get("date_to"):
        params["cond[RCRIT_PBLANC_DE::LTE]"] = args["date_to"]
    if sido and kind == "APT":
        params["cond[SUBSCRPT_AREA_CODE_NM::EQ]"] = sido
    data = _call(ENDPOINTS[kind], params)
    rows = data.get("data") or []
    if sido:
        rows = [r for r in rows if _in_sido(r, sido)]
    if args.get("only_open", True):
        today_s = today.isoformat()
        rows = [r for r in rows if (_end_date(r) or "9999-12-31") >= today_s]
    by_sigungu = {}
    for r in rows:
        g = _sigungu(r) or "기타"
        by_sigungu[g] = by_sigungu.get(g, 0) + 1
    if sigungu:
        rows = [r for r in rows if _sigungu(r) == sigungu]
    rows.sort(key=lambda r: r.get("RCEPT_BGNDE") or r.get("SUBSCRPT_RCEPT_BGNDE") or r.get("RCRIT_PBLANC_DE") or "")
    return {"house_type": kind, "sido": sido, "sigungu": sigungu,
            "total_from_api": data.get("matchCount", data.get("totalCount")),
            "returned": len(rows), "today": today.isoformat(),
            "sigungu_counts": dict(sorted(by_sigungu.items(), key=lambda x: -x[1])),
            "notices": [_pick(r, NOTICE_FIELDS) for r in rows]}


def get_notice_models(args):
    no = args.get("house_manage_no", "")
    if not NO_RE.match(no):
        raise ToolError("house_manage_no는 숫자")
    params = {"page": 1, "perPage": 100, "cond[HOUSE_MANAGE_NO::EQ]": no}
    if args.get("pblanc_no"):
        if not NO_RE.match(args["pblanc_no"]):
            raise ToolError("pblanc_no는 숫자")
        params["cond[PBLANC_NO::EQ]"] = args["pblanc_no"]
    data = _call(MODEL_ENDPOINT, params)
    return {"house_manage_no": no, "models": [_pick(r, MODEL_FIELDS) for r in data.get("data") or []]}


HANDLERS = {"search_notices": search_notices, "get_notice_models": get_notice_models}
ALLOWED_ARGS = {t["name"]: set(t["inputSchema"]["properties"]) for t in TOOLS}


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion", "2025-06-18")
        return {"protocolVersion": ver, "capabilities": {"tools": {}},
                "serverInfo": {"name": "applyhome", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        p = msg.get("params") or {}
        name, args = p.get("name"), p.get("arguments") or {}
        if name not in HANDLERS:
            raise LookupError(name)
        try:
            extra = set(args) - ALLOWED_ARGS[name]
            if extra:  # 스키마 밖 입력(개인 조건 등)은 API로 보내지 않는다
                raise ToolError("허용되지 않은 입력 항목: " + ", ".join(sorted(extra)))
            out = HANDLERS[name](args)
            return {"content": [{"type": "text", "text": _mask(json.dumps(out, ensure_ascii=False))}]}
        except ToolError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    if mid is None:
        return None  # 알림(notifications/*)은 응답하지 않음
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid = msg.get("id")
        try:
            result = handle(msg)
            if mid is None:
                continue
            resp = {"jsonrpc": "2.0", "id": mid, "result": result}
        except LookupError as e:
            resp = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"지원하지 않음: {e}"}}
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": _mask(str(e))}}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
