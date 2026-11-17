"""공개판 에이전트 파이프라인 (Lambda 안에서 Amazon Bedrock Claude 호출).

플러그인의 에이전트·스킬 정의(agents/*.md, SKILL.md)를 시스템 프롬프트로 그대로 쓰고,
판정·공고 조회는 플러그인 코드(eligibility.evaluate, MCP 서버 모듈)를 도구로 준다.

  ① 판정        : eligibility.evaluate (eligibility-checker 에이전트가 실행하는 바로 그 스크립트)
  ② 공고 탐색    : notice-finder 프롬프트 + search_notices·get_notice_models 도구 (Sonnet)
  ③ 답변 작성    : check-eligibility 스킬의 4~5단계 지침 (Sonnet)
  ④ 개인정보 점검 : privacy-reviewer 프롬프트 (Haiku) → FAIL이면 ③을 한 번 고쳐 씀
  ⑤ 코드 가드    : 최종 답변에서 PII·키 패턴을 다시 가림

개인 조건 원문은 ②④에 넘기지 않는다(②는 비개인 필터만, ④는 초안만 본다).
"""
import json
import os
import re

import boto3

import applyhome_server as mcp
import eligibility

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("AGENT_MODEL", "us.anthropic.claude-sonnet-5-5")
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "us.anthropic.claude-haiku-5-5")
# 비용 추정용(USD / 1M 토큰). 정확한 청구액은 AWS 청구서 기준.
PRICE = {MODEL: (3.0, 15.0), REVIEW_MODEL: (1.0, 5.0)}
MAX_TOOL_CALLS = 8

_brt = None


def brt():
    global _brt
    if _brt is None:
        _brt = boto3.client("bedrock-runtime")
    return _brt


def prompt_file(rel):
    """에이전트·스킬 마크다운에서 frontmatter를 뗀 본문."""
    with open(os.path.join(HERE, "prompts", rel), encoding="utf-8") as f:
        text = f.read()
    return re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S).strip()


TOOLS = [{"toolSpec": {"name": t["name"], "description": t["description"],
                       "inputSchema": {"json": t["inputSchema"]}}} for t in mcp.TOOLS]
ALLOWED = {t["name"]: set(t["inputSchema"]["properties"]) for t in mcp.TOOLS}
HANDLERS = {"search_notices": mcp.search_notices, "get_notice_models": mcp.get_notice_models}


class Usage:
    def __init__(self):
        self.cost = 0.0
        self.calls = 0

    def add(self, model, usage):
        i, o = PRICE.get(model, (3.0, 15.0))
        self.cost += usage.get("inputTokens", 0) / 1e6 * i + usage.get("outputTokens", 0) / 1e6 * o
        self.calls += 1


def converse(model, system, messages, usage, tools=None, max_tokens=3000):
    kw = {"modelId": model, "system": [{"text": system}], "messages": messages,
          "inferenceConfig": {"maxTokens": max_tokens}}
    if tools:
        kw["toolConfig"] = {"tools": tools}
    r = brt().converse(**kw)
    usage.add(model, r.get("usage") or {})
    return r["output"]["message"], r.get("stopReason")


def text_of(msg):
    return "\n".join(c["text"] for c in msg.get("content", []) if "text" in c).strip()


def compact_judgement(j):
    """답변 작성에 넘길 판정 요약(프로필 원문·소득 금액 없음)."""
    keep = []
    for r in j["results"]:
        item = {k: r[k] for k in ("rule_id", "type", "status", "reasons") if k in r}
        for k in ("by_scope", "by_regulation"):
            if k in r:
                item[k] = r[k]
        if r["rule_id"] == "GEN-SCORE":
            item = {"rule_id": "GEN-SCORE", "total": r.get("total"), "parts": r.get("parts"), "notes": r.get("notes")}
        keep.append(item)
    return {"as_of": j["as_of"], "income_band": j["income_band_of_urban_avg"], "deposit_max_area": j["deposit_max_area"],
            "results": keep, "disclaimer": j["disclaimer"]}


def find_notices(filters, emit, usage):
    system = prompt_file("notice-finder.md") + (
        "\n\n# 이 실행 환경\n- 사용할 수 있는 도구는 search_notices, get_notice_models뿐입니다(WebFetch 없음)."
        "\n- 조회 결과를 근거로만 정리하고, 마지막에 공고별 요약을 한국어로 씁니다.")
    messages = [{"role": "user", "content": [{"text": "notice_filters: " + json.dumps(filters, ensure_ascii=False)}]}]
    for _ in range(MAX_TOOL_CALLS + 1):
        msg, stop = converse(MODEL, system, messages, usage, tools=TOOLS)
        messages.append(msg)
        uses = [c["toolUse"] for c in msg.get("content", []) if "toolUse" in c]
        if stop != "tool_use" or not uses:
            return text_of(msg)
        results = []
        for u in uses:
            name, args = u["name"], u.get("input") or {}
            if name not in HANDLERS or set(args) - ALLOWED[name]:
                out, status = {"error": "허용되지 않은 도구 또는 입력 항목"}, "error"
            else:
                emit({"kind": "mcp", "label": name, "detail": args})
                try:
                    out, status = HANDLERS[name](args), "success"
                    if name == "search_notices":      # 토큰 절약: 공고는 10건까지만
                        out = {**out, "notices": out["notices"][:10]}
                except mcp.ToolError as e:
                    out, status = {"error": str(e)}, "error"
            results.append({"toolResult": {"toolUseId": u["toolUseId"], "status": status,
                                           "content": [{"json": out}]}})
        messages.append({"role": "user", "content": results})
    return "공고 조회 도구 호출 한도를 넘어 중단했습니다."


def write_answer(judged, findings, region, usage, fixes=None, draft=None):
    skill = prompt_file("SKILL.md")
    # 4단계(맞춰 보기)만 쓴다. 5단계(점검)는 이 파이프라인에서 privacy-reviewer가 따로 맡는다.
    a, b = skill.find("## 4."), skill.find("## 5.")
    steps = skill[a:b] if a >= 0 and b > a else skill
    system = ("당신은 청약 자격·공고 확인 결과를 사용자에게 정리해 주는 작성자입니다. 아래 절차의 4~5단계를 따릅니다.\n\n"
              + steps + "\n\n# 작성 규칙\n- 한국어 마크다운. 판정마다 rule_id를 붙입니다.\n"
              "- 소득은 구간으로만 쓰고 금액이나 소수점 %는 쓰지 않습니다.\n"
              "- 링크는 https://www.applyhome.co.kr/ 아래 주소만 씁니다.\n"
              "- 출력 순서: ① 조회 지역·기준일 ② 가능한 공급 유형 요약 ③ 맞는 현재 공고 ④ 확인필요 항목 ⑤ 고지 문구.\n"
              "- 마지막에 disclaimer 문구를 그대로 붙입니다.\n"
              "- 개인정보 점검은 다음 단계에서 privacy-reviewer가 따로 합니다. 점검을 했다·못 했다는 말은 쓰지 않습니다.")
    if fixes and draft:
        user = f"아래 초안을 점검 의견에 맞게 고쳐 최종본만 출력하세요.\n\n# 점검 의견\n{fixes}\n\n# 초안\n{draft}"
    else:
        user = (f"# 조회 지역\n{region}\n\n# 판정 결과(eligibility.py)\n{json.dumps(judged, ensure_ascii=False)}"
                f"\n\n# 공고 탐색 결과(notice-finder)\n{findings}")
    msg, _ = converse(MODEL, system, [{"role": "user", "content": [{"text": user}]}], usage, max_tokens=4000)
    return text_of(msg)


def review(draft, rule_ids, usage):
    system = prompt_file("privacy-reviewer.md") + (
        "\n\n# 이 실행 환경\n- 파일 도구가 없습니다. rules.json의 rule_id 목록: " + ", ".join(rule_ids) +
        '\n- 마지막 줄에 반드시 JSON 한 줄로 결과를 씁니다: {"verdict": "PASS" 또는 "FAIL", "fixes": "고칠 점(없으면 빈 문자열)"}')
    msg, _ = converse(REVIEW_MODEL, system, [{"role": "user", "content": [{"text": draft}]}], usage, max_tokens=1500)
    text = text_of(msg)
    m = re.search(r'\{[^{}]*"verdict"[^{}]*\}\s*$', text)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        v = {}
    return (v.get("verdict") or ("FAIL" if "FAIL" in text else "PASS")).upper(), v.get("fixes") or "", text


PII = re.compile(r"(?<!\d)(\d{6}-?[1-8]\d{6}|01[016789]-?\d{3,4}-?\d{4}|\d{4}-\d{4}-\d{4}-\d{4})(?!\d)"
                 r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def final_guard(text):
    text = mcp._mask(text)
    return PII.sub("[가림]", text)


def run(args, region, sigungu, emit):
    """args: eligibility key=value 목록. emit(step): 진행 단계를 저장하는 콜백."""
    usage = Usage()
    emit({"kind": "agent", "label": "판정 에이전트"})
    judged = eligibility.evaluate(args)
    emit({"kind": "tool", "label": "판정 스크립트 실행"})
    filters = {**judged["notice_filters"], "sigungu": sigungu}

    emit({"kind": "agent", "label": "공고 탐색 에이전트"})
    findings = find_notices(filters, emit, usage)

    emit({"kind": "agent", "label": "답변 작성"})
    compact = compact_judgement(judged)
    draft = write_answer(compact, findings, region, usage)

    emit({"kind": "agent", "label": "개인정보 점검 에이전트"})
    rule_ids = [r["rule_id"] for r in judged["results"]]
    verdict, fixes, _ = review(draft, rule_ids, usage)
    emit({"kind": "tool", "label": f"점검 결과 {verdict}"})
    if verdict == "FAIL" and fixes:
        emit({"kind": "agent", "label": "답변 고쳐 쓰기"})
        draft = write_answer(compact, findings, region, usage, fixes=fixes, draft=draft)

    emit({"kind": "result", "text": final_guard(draft), "cost_usd": round(usage.cost, 4),
          "turns": usage.calls, "denials": 0, "estimated": True})
