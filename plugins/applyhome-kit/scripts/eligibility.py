#!/usr/bin/env python3
"""청약 공급유형 1차 판정기 (v2: 세부 인적사항·소득 % 계산·가점·지역 판정).

- 입력: 명령행 인자 key=value (범주형/숫자, 허용 키만). 파일·네트워크를 쓰지 않는다.
  예) python3 -I eligibility.py age_band=30-34 residence_sido=서울 homeless_household=true account_period=3y
- 출력: stdout JSON (유형별 민영/국민/공공 판정 + 근거 rule_id + 가점 + 조회 필터).
- 입력 원문 값은 오류 메시지에 되풀이하지 않는다.
- 기준: rules.json (청약홈 청약자격·특별공급 안내 페이지에서 확인한 값, verified 표시)
"""
import json
import os
import re
import sys

RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")
SIDO = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
        "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
YEARS = ["lt1"] + [f"{n}y" for n in range(1, 15)] + ["15y+"]          # n y = n년 이상 n+1년 미만
ACCOUNT = ["none", "lt6m", "6m-1y"] + [f"{n}y" for n in range(1, 15)] + ["15y+"]
B = [True, False]
ENUMS = {
    # 기본
    "age_band": ["under19", "19-29", "30-34", "35-39", "40-49", "50-64", "65+"],
    "residence_sido": SIDO, "target_sido": SIDO,
    "residence_years": ["lt1", "1-2", "2+"],
    "homeless_household": B, "house_count": ["0", "1", "2+"], "is_householder": B,
    # 청약통장
    "account_period": ACCOUNT, "payments_count": ["lt6", "6-11", "12-23", "24+"],
    "deposit_band": ["0-199", "200-249", "250-299", "300-399", "400-599",
                     "600-699", "700-999", "1000-1499", "1500+"],
    # 가족
    "marital_status": ["single", "engaged", "married"],
    "married_years": ["0-2", "3-7", "7+"],
    "single_parent": B,
    "children_count": ["0", "1", "2", "3+"],
    "youngest_child_age": ["none", "under2", "2-6", "7-18"],
    "pregnant": B,
    "supports_parent_65_3y": B,
    "dependents_count": ["0", "1", "2", "3", "4", "5", "6+"],
    "homeless_years": ["under30_single"] + YEARS,
    # 소득·자산
    "household_size": ["1", "2", "3", "4", "5", "6+"],
    "monthly_income_manwon": "int",
    "dual_income": B,
    "real_estate": ["none", "le33100", "gt33100", "unknown"],
    "income_tax_5y": B,
    # 이력
    "first_home_ever": B,
    "won_within_5y": B + ["unknown"],
    "prior_special_win": B + ["unknown"],
    "institution_eligible": B,
}
REQUIRED = ["age_band", "residence_sido", "homeless_household", "account_period"]
SCOPES = ["민영", "국민", "공공"]


class InputError(ValueError):
    """입력 검증 실패. 메시지에는 항목 이름만 담고 입력 값은 담지 않는다."""


def fail(msg):
    raise InputError(msg)


def _value(v):
    return {"true": True, "false": False}.get(v, v)


def load_profile(argv):
    data = {}
    for arg in argv:
        if "=" not in arg:
            fail("인자는 key=value 형식이어야 합니다")
        k, v = arg.split("=", 1)
        if k in data:
            fail(f"중복 항목: {k}")
        data[k] = _value(v)
    extra = sorted(set(data) - set(ENUMS))
    if extra:
        fail("허용되지 않은 입력 항목: " + ", ".join(extra) +
             " (실명·주민번호·연락처·주소 등은 받지 않습니다)")
    for k, v in data.items():
        allowed = ENUMS[k]
        if allowed == "int":
            if not (isinstance(v, str) and re.fullmatch(r"\d{1,6}", v)):
                fail(f"'{k}' 값은 0 이상의 정수(만원)여야 합니다")
            data[k] = int(v)
        elif v not in allowed:
            shown = ["true" if x is True else "false" if x is False else x for x in allowed]
            fail(f"'{k}' 값이 허용 범주가 아닙니다. 허용: {shown}")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        fail("필수 항목 누락: " + ", ".join(missing))
    data.setdefault("target_sido", data["residence_sido"])
    return data


# ── 계산 도우미 ────────────────────────────────────────────────
def months_low(period):
    if period == "none":
        return -1
    if period == "lt6m":
        return 0
    if period == "6m-1y":
        return 6
    return 180 if period == "15y+" else int(period[:-1]) * 12


def years_low(v):
    return 15 if v == "15y+" else (0 if v == "lt1" else int(v[:-1]))


def deposit_max_area(p, R):
    if "deposit_band" not in p:
        return None, "예치금 미입력"
    sido = p["residence_sido"]          # 예치금은 신청자 주민등록 거주지 기준
    cls = "A" if sido in R["deposit_region_class"]["A"] else "B" if sido in R["deposit_region_class"]["B"] else "C"
    table = R["deposit_table_manwon"][cls]
    low = int(p["deposit_band"].rstrip("+").split("-")[0])
    idx = max([i for i, need in enumerate(table) if low >= need], default=-1)
    if idx < 0:
        return -1, f"예치금 부족(거주지 기준 최소 {table[0]}만원)"
    return idx, R["area_labels"][idx]


def income_pct(p, R):
    """가구 월평균소득의 도시근로자 월평균소득 대비 %. 계산 불가면 (None, 사유)."""
    if "monthly_income_manwon" not in p:
        return None, "가구 월소득 미입력"
    size = p.get("household_size")
    if size is None:
        return None, "가구원 수 미입력"
    t = R["income_monthly_won_100pct"]
    base = t["le3"] if size in ("1", "2", "3") else t.get(size)
    if not base:
        return None, "6인 이상 가구 소득 기준은 공고문 확인"
    return round(p["monthly_income_manwon"] * 10000 / base * 100, 1), None


def pct_band(pct):
    if pct is None:
        return None
    for hi in (70, 100, 120, 130, 140, 150, 160, 200):
        if pct <= hi:
            return f"{hi}% 이하"
    return "200% 초과"


def has_child(p):
    return p.get("children_count", "0") != "0" or p.get("pregnant") is True


def best(statuses):
    for s in ("가능", "확인필요", "불가"):
        if s in statuses:
            return s
    return "해당없음"


def score(p, R):
    """가점제 예상 점수(무주택 32 + 부양가족 35 + 통장 17 = 84)."""
    S = R["score"]
    parts, notes = {}, []
    hy = p.get("homeless_years")
    if hy is None:
        notes.append("무주택기간 미입력")
    elif not p["homeless_household"]:
        parts["무주택기간"] = 0; notes.append("유주택 세대는 무주택기간 0점")
    elif hy == "under30_single":
        parts["무주택기간"] = 0
    else:
        h = S["homeless_years_points"]
        parts["무주택기간"] = min(h["max"], h["lt1"] + h["per_year"] * years_low(hy))
    dc = p.get("dependents_count")
    if dc is None:
        notes.append("부양가족 수 미입력")
    else:
        d = S["dependents_points"]
        parts["부양가족"] = min(d["max"], d["base"] + d["per_person"] * (6 if dc == "6+" else int(dc)))
    a, ap = S["account_points"], p["account_period"]
    m = months_low(ap)
    if m >= 0:
        parts["통장가입기간"] = (a["lt6m"] if ap == "lt6m" else a["6m-1y"] if ap == "6m-1y"
                             else min(a["max"], a["start_1y"] + a["per_year_from_1y"] * (years_low(ap) - 1)))
    total = sum(parts.values()) if len(parts) == 3 else None
    notes.append("부양가족·통장 점수는 규칙 별표 기준(청약홈 페이지 미기재), 배우자 통장 가산(최대 3점) 미반영")
    return {"rule_id": "GEN-SCORE", "type": "가점제 예상 점수", "status": "참고", "parts": parts,
            "total": total, "max": 84, "notes": notes}


# ── 판정 ───────────────────────────────────────────────────────
def item(rid, R, status, reasons, **extra):
    r = next(x for x in R["rules"] if x["id"] == rid)
    out = {"rule_id": rid, "type": r["name"], "category": r["category"], "status": status, "reasons": reasons}
    out.update(extra)
    return out


def judge(p, R):
    res = []
    target, home = p["target_sido"], p["residence_sido"]
    cap = R["capital_area"]
    months = months_low(p["account_period"])
    homeless = p["homeless_household"] is True
    householder = p.get("is_householder")
    houses = p.get("house_count", "0" if homeless else None)
    won5 = p.get("won_within_5y", "unknown")
    married = p.get("marital_status")
    pct, pct_why = income_pct(p, R)
    dual = p.get("dual_income") is True
    estate = p.get("real_estate", "unknown")
    area_idx, area_label = deposit_max_area(p, R)

    if p["age_band"] == "under19":
        return [item("REGION", R, "불가", ["만 19세 미만은 원칙적으로 신청 불가(자녀 양육·형제자매 부양 세대주 예외는 공고 확인)"])], None, pct
    if months < 0:
        return [item("REGION", R, "불가", ["청약통장(주택청약종합저축)이 있어야 신청 가능(국가유공자·장애인 등 기관추천은 예외)"])], area_label, pct

    # 공급 지역: 해당지역 / 기타지역 / 신청 불가
    if target == home:
        reg = ("가능", [f"{target} 해당지역 거주자", "해당지역 우선 거주기간 요건은 공고문 확인"
                        + (" (현재 거주 1년 미만)" if p.get("residence_years") == "lt1" else "")])
    elif target in cap and home in cap:
        reg = ("가능", [f"{target} 공고에 수도권({home}) 거주자로 기타지역 신청 가능(해당지역 우선 후 배정)"])
    elif target in cap:
        reg = ("불가", [f"{target} 등 수도권 공고는 수도권 거주자만 신청 가능(공고 확인)"])
    else:
        reg = ("확인필요", [f"{home} 거주자가 {target} 공고에 신청 가능한지(인근지역 포함)는 공고 확인"])
    res.append(item("REGION", R, reg[0], reg[1], target_sido=target))

    # 일반공급 1순위 (가입기간은 공급 지역 기준)
    need_non = R["rank1_months"]["capital" if target in cap else "non_capital"]
    need_reg = R["rank1_months"]["regulated"]

    def rank1_private(regulated):
        need = need_reg if regulated else need_non
        if months < need:
            return "불가", [f"가입기간 {need}개월 이상 필요"]
        if area_idx is None:
            return "확인필요", ["예치금 미입력"]
        if area_idx < 0:
            return "불가", [area_label]
        st, rs = "가능", [f"예치금 기준 신청 가능 면적: {area_label}"]
        if regulated:
            if householder is not True:
                return ("불가" if householder is False else "확인필요"), ["규제지역 1순위는 세대주"]
            if houses == "2+":
                return "불가", ["규제지역은 2주택 이상 세대 1순위 불가"]
            if won5 is True:
                return "불가", ["과거 5년 내 당첨 세대는 규제지역 1순위 불가"]
            if won5 == "unknown":
                st = "확인필요"; rs.append("과거 5년 내 당첨 이력 확인")
        return st, rs

    nr, rg = rank1_private(False), rank1_private(True)
    res.append(item("GEN-1-PRIVATE", R, best([nr[0], rg[0]]), [],
                    by_regulation={"비규제지역": {"status": nr[0], "reasons": nr[1]},
                                   "규제지역": {"status": rg[0], "reasons": rg[1]}}))
    rank1_ok = nr[0] == "가능" or rg[0] == "가능"

    pay_need = R["rank1_payments_national"]
    pay_low = {"lt6": 0, "6-11": 6, "12-23": 12, "24+": 24}.get(p.get("payments_count"))

    def rank1_national(regulated):
        need_m = need_reg if regulated else need_non
        need_p = pay_need["regulated" if regulated else ("capital" if target in cap else "non_capital")]
        if not homeless:
            return "불가", ["무주택세대구성원만 신청 가능"]
        if months < need_m:
            return "불가", [f"가입기간 {need_m}개월 이상 필요"]
        if pay_low is None:
            return "확인필요", [f"납입 인정 {need_p}회 이상인지 확인(납입 회차 미입력)"]
        if pay_low < need_p:
            return "불가", [f"납입 인정 {need_p}회 이상 필요"]
        if regulated and householder is not True:
            return ("불가" if householder is False else "확인필요"), ["규제지역 1순위는 세대주"]
        return "가능", []

    n1, n2 = rank1_national(False), rank1_national(True)
    res.append(item("GEN-1-NATIONAL", R, best([n1[0], n2[0]]), [],
                    by_regulation={"비규제지역": {"status": n1[0], "reasons": n1[1]},
                                   "규제지역": {"status": n2[0], "reasons": n2[1]}}))
    res.append(item("GEN-2", R, "가능", ["청약통장 가입자는 1순위 미달이어도 2순위 신청 가능"]))

    # 특별공급 공통 전제
    base_fail = []
    if not homeless:
        base_fail.append("무주택세대구성원만 신청 가능")
    if months < 6:
        base_fail.append("통장 가입 6개월 이상 필요")
    psw = p.get("prior_special_win", "unknown")

    def tiered(rid, scope):
        """소득 구간 판정 → (status, reason)."""
        tiers = R["income_tiers"][rid].get(scope)
        if tiers is None:
            return "가능", "소득 기준 미적용" if scope == "민영" else "소득 기준은 사업주체에 따라 다름(공고 확인)"
        if pct is None:
            return "확인필요", pct_why
        lo, hi = tiers["dual" if dual else "single"]
        tag = f"소득 {pct_band(pct)}({'맞벌이' if dual else '외벌이'})"
        if pct <= lo:
            return "가능", f"{tag} → 우선공급 구간(≤{lo}%)"
        if pct <= hi:
            return "가능", f"{tag} → 일반공급 구간(≤{hi}%)"
        lot = tiers["lottery"]
        if lot == "dual_le200":
            return ("가능", f"{tag} → 추첨 구간(맞벌이 ≤200%, 자산 기준 공고 확인)") if dual and pct <= 200 \
                else ("불가", f"{tag} → 소득 기준 초과")
        if lot == "asset_with_child" and not has_child(p) and p.get("household_size") != "1":
            return "불가", f"{tag} → 기준 초과, 추첨은 자녀 있는 가구 또는 1인가구만"
        if estate in ("none", "le33100"):
            return "가능", f"{tag} → 추첨 구간(부동산 {R['real_estate_limit_manwon']}만원 이하)"
        if estate == "unknown":
            return "확인필요", f"{tag} → 추첨은 부동산 {R['real_estate_limit_manwon']}만원 이하일 때만(자산 미입력)"
        return "불가", f"{tag} → 소득·자산 기준 초과"

    def special(rid, cond, cond_reason, scopes=SCOPES, extra_reason=None, need_rank1=False,
                allow_spouse_prior=False):
        if base_fail:
            return item(rid, R, "불가", base_fail)
        if psw is True and not allow_spouse_prior:
            return item(rid, R, "불가", ["특별공급은 세대당 평생 1회(과거 당첨 이력 있음)"])
        if cond is None:
            return item(rid, R, "확인필요", [cond_reason + " — 입력 필요"])
        if cond is False:
            return item(rid, R, "불가", [cond_reason + " 요건 미충족"])
        common = list(extra_reason or [])
        if need_rank1 and not rank1_ok:
            common.append("일반공급 1순위 요건도 충족해야 함(현재 1순위 미충족 또는 확인필요)")
        if psw is True:
            common.append("과거 특공 당첨이 배우자의 혼인 전 당첨이면 신청 가능, 아니면 불가")
        elif psw == "unknown":
            common.append("세대 내 과거 특별공급 당첨 이력 확인(평생 1회)")
        by = {}
        for sc in scopes:
            st, why = tiered(rid, sc)
            if need_rank1 and not rank1_ok and st == "가능":
                st = "확인필요"
            if psw is True and st == "가능":
                st = "확인필요"
            by[sc] = {"status": st, "reasons": [why]}
        return item(rid, R, best([v["status"] for v in by.values()]), common, by_scope=by)

    # 신혼부부: 민영·국민은 혼인 7년 이내, 공공은 예비신혼·6세 이하 자녀·한부모 포함
    my = p.get("married_years")
    child_le6 = p.get("youngest_child_age") in ("under2", "2-6") or p.get("pregnant") is True
    if married is None:
        nw_private = nw_public = None
    else:
        nw_private = married == "married" and my in ("0-2", "3-7")
        nw_public = nw_private or married == "engaged" or child_le6 or (p.get("single_parent") is True and child_le6)
    rank_note = ["특공 내 순위: 미성년 자녀(태아 포함) 있으면 1순위, 없으면 2순위"]
    if married == "married" and my is None:
        nw_private = None
    if nw_private is False and nw_public:
        it = special("SP-NEWLYWED", True, "", scopes=["공공"],
                     extra_reason=["민영·국민은 혼인 7년 이내만 해당 → 공공주택만 가능(예비신혼·6세 이하 자녀·한부모)"])
    else:
        it = special("SP-NEWLYWED", nw_private, "혼인 7년 이내(공공은 예비신혼·6세 이하 자녀 한부모 포함)",
                     extra_reason=rank_note + (["공공 나눔형 우선공급: 혼인 2년 이내·2세 이하 자녀·예비신혼"] if my == "0-2" else []),
                     allow_spouse_prior=True)
    res.append(it)

    # 생애최초: 세대원 전원 주택 소유 이력 없음 + 1순위 + 소득세 5년 + (기혼 또는 미혼 자녀 또는 1인가구)
    fh = p.get("first_home_ever")
    one_person = p.get("household_size") == "1"
    fh_family = None if married is None else (married == "married" or has_child(p) or one_person)
    cond = None if fh is None else (fh and (fh_family is not False))
    extra = []
    if p.get("income_tax_5y") is False:
        cond = False if cond is not None else cond
        extra.append("소득세 5년 이상 납부 필요")
    elif p.get("income_tax_5y") is None:
        extra.append("소득세 5년 이상 납부(과거 1년 내 포함) 확인")
    if one_person:
        extra.append("1인가구는 추첨분만, 단독세대는 전용 60㎡ 이하만 가능")
    if fh_family is None and fh:
        cond = None
    res.append(special("SP-FIRSTHOME", cond, "세대원 전원 과거 주택 소유 이력 없음·혼인 또는 자녀 또는 1인가구·소득세 5년",
                       extra_reason=extra, need_rank1=True, allow_spouse_prior=True))

    # 다자녀: 미성년 자녀 2명 이상(태아 포함)
    cc = p.get("children_count")
    res.append(special("SP-MULTICHILD", None if cc is None else cc in ("2", "3+"), "미성년 자녀 2명 이상(태아·입양 포함)"))

    # 노부모부양: 무주택 세대주 + 만65세 이상 직계존속 3년 이상 부양 + 1순위
    par = p.get("supports_parent_65_3y")
    if par is True and householder is not True:
        res.append(item("SP-ELDERLY", R, "불가" if householder is False else "확인필요", ["무주택 세대주만 신청 가능"]))
    else:
        res.append(special("SP-ELDERLY", par, "만 65세 이상 직계존속 3년 이상 부양", need_rank1=True))

    # 신생아: 2세 미만 자녀(임신·입양 포함)
    yc = p.get("youngest_child_age")
    nb = None if (yc is None and p.get("pregnant") is None) else (yc == "under2" or p.get("pregnant") is True)
    res.append(special("SP-NEWBORN", nb, "입주공고일 현재 2세 미만 자녀(임신·입양 포함)",
                       need_rank1=True, allow_spouse_prior=True))

    # 청년(공공): 만19~39세, 혼인 중 아님, 과거 주택 소유 이력 없음, 본인 소득 140% 이하
    young = p["age_band"] in ("19-29", "30-34", "35-39")
    ycond = None if married is None or fh is None else (young and married != "married" and fh)
    yreason = ["공공분양 공고에만 해당", "본인 월평균소득 140%(1인 기준 약 533.9만원) 이하·자산 기준은 공고 확인"]
    if p.get("income_tax_5y"):
        yreason.append("소득세 5년 납부 → 우선공급(30%) 대상 가능")
    if ycond:
        res.append(item("SP-YOUTH", R, "확인필요" if not base_fail else "불가", base_fail or yreason))
    else:
        res.append(item("SP-YOUTH", R, "확인필요" if ycond is None else "불가",
                        ["만 19~39세·혼인 중 아님·과거 주택 소유 이력 없음" + (" — 입력 필요" if ycond is None else " 요건 미충족")]))

    ie = p.get("institution_eligible")
    res.append(item("SP-INSTITUTION", R, "가능" if ie else ("불가" if ie is False else "확인필요"),
                    ["국가유공자·장애인 등 관계기관 추천을 받아야 함(통장 없이도 가능한 경우 있음)"]
                    if ie is not False else ["해당 없음"]))

    res.append(score(p, R))
    return res, area_label, pct


def evaluate(argv):
    """key=value 인자 목록을 판정해 결과 dict를 돌려준다(Lambda 등에서 import해 쓰는 진입점).
    입력이 잘못되면 InputError를 던진다."""
    with open(RULES_PATH, encoding="utf-8") as f:
        R = json.load(f)
    p = load_profile(argv)
    results, area, pct = judge(p, R)
    possible = [r["type"] for r in results
                if r.get("status") in ("가능", "확인필요") and r["rule_id"] not in ("SP-INSTITUTION", "REGION", "GEN-SCORE")]
    region = next((r for r in results if r["rule_id"] == "REGION"), None)
    return {
        "as_of": R["as_of"],
        "sources": R["source"],
        "disclaimer": R["disclaimer"],
        # 정확한 %·금액은 역산 위험이 있어 구간만 출력
        "income_band_of_urban_avg": pct_band(pct),
        "deposit_max_area": area,
        "results": results,
        # notice-finder에 넘길 비개인 필터(개인 조건 원문은 넘기지 않음)
        "notice_filters": {"sido": p["target_sido"], "candidate_types": possible,
                           "region_status": region["status"] if region else None},
    }


def main():
    try:
        out = evaluate(sys.argv[1:])
    except InputError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
