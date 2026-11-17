"""eligibility.py(v2) 판정 케이스 테스트. 사용: python3 -I tests/test_eligibility.py
기대값은 청약홈 특별공급·청약자격 안내(2026-11-17 확인) 기준으로 손 계산한 값."""
import json, os, subprocess, sys
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "eligibility.py")

def run(profile):
    args = [f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in profile.items()]
    p = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)

def get(out, rid):
    return next(x for x in out["results"] if x["rule_id"] == rid)

def st(out, rid, sub=None):
    r = get(out, rid)
    if sub is None:
        return r["status"]
    return (r.get("by_scope") or r.get("by_regulation"))[sub]["status"]

fails = 0
def check(name, got, want):
    global fails
    ok = got == want; fails += not ok
    print(("PASS " if ok else "FAIL ") + f"{name}: got={got} want={want}")

base = dict(age_band="30-34", residence_sido="서울", homeless_household=True, is_householder=True, house_count="0",
            account_period="3y", payments_count="24+", deposit_band="300-399", marital_status="married", married_years="3-7",
            children_count="1", youngest_child_age="2-6", pregnant=False, household_size="3",
            monthly_income_manwon="700", dual_income=False, real_estate="none", income_tax_5y=True,
            first_home_ever=True, won_within_5y=False, prior_special_win=False, supports_parent_65_3y=False,
            dependents_count="2", homeless_years="3y")

rc, o = run(base)
check("소득 구간 출력(700만/3인=92.9% → 100% 이하)", o["income_band_of_urban_avg"], "100% 이하")
check("정확한 % 값은 출력에 없음", "92.9" in json.dumps(o, ensure_ascii=False), False)
check("서울 거주·서울 공고 → 해당지역", st(o, "REGION"), "가능")
check("규제지역 민영 1순위", st(o, "GEN-1-PRIVATE", "규제지역"), "가능")
check("예치금 300 서울 → 85㎡", o["deposit_max_area"], "전용 85㎡ 이하")
check("신혼 민영 우선(92.9% ≤100)", get(o, "SP-NEWLYWED")["by_scope"]["민영"]["reasons"][0].endswith("우선공급 구간(≤100%)"), True)
check("신생아 불가(막내 2~6세)", st(o, "SP-NEWBORN"), "불가")
check("가점 28점", get(o, "GEN-SCORE")["total"], 28)
check("조회 필터 비개인", sorted(o["notice_filters"]), ["candidate_types", "region_status", "sido"])

rc, o = run({**base, "monthly_income_manwon": "1100"})        # 146.0%
check("외벌이 146% → 신혼 민영 추첨(자산 OK)", st(o, "SP-NEWLYWED", "민영"), "가능")
check("외벌이 146% → 신혼 공공 불가(맞벌이 아님)", st(o, "SP-NEWLYWED", "공공"), "불가")
rc, o = run({**base, "monthly_income_manwon": "1100", "real_estate": "gt33100"})
check("146% + 부동산 초과 → 신혼 민영 불가", st(o, "SP-NEWLYWED", "민영"), "불가")
rc, o = run({**base, "monthly_income_manwon": "1100", "real_estate": "unknown"})
check("146% + 자산 모름 → 확인필요", st(o, "SP-NEWLYWED", "민영"), "확인필요")
rc, o = run({**base, "monthly_income_manwon": "1400", "dual_income": True})   # 185.8%
check("맞벌이 185.8% → 공공 추첨(≤200)", st(o, "SP-NEWLYWED", "공공"), "가능")

rc, o = run({**base, "marital_status": "engaged", "children_count": "0", "youngest_child_age": "none"})
check("예비신혼 → 민영 신혼 불가·공공만", list(get(o, "SP-NEWLYWED").get("by_scope", {})), ["공공"])
check("예비신혼 → 청년 특공 후보(확인필요)", st(o, "SP-YOUTH"), "확인필요")

rc, o = run({**base, "youngest_child_age": "under2"})
check("2세 미만 자녀 → 신생아 민영 가능", st(o, "SP-NEWBORN", "민영"), "가능")
rc, o = run({**base, "children_count": "0", "youngest_child_age": "none", "pregnant": True})
check("임신 → 신생아 가능", st(o, "SP-NEWBORN"), "가능")

rc, o = run({**base, "children_count": "2"})
check("자녀 2명 → 다자녀 민영(소득 미적용)", st(o, "SP-MULTICHILD", "민영"), "가능")

rc, o = run({**base, "income_tax_5y": False})
check("소득세 5년 미충족 → 생애최초 불가", st(o, "SP-FIRSTHOME"), "불가")
rc, o = run({**base, "prior_special_win": True})
check("특공 당첨 이력 → 다자녀 불가", st(o, "SP-MULTICHILD"), "불가")
check("특공 당첨 이력 → 신혼은 확인필요(배우자 혼인 전 예외)", st(o, "SP-NEWLYWED", "민영"), "확인필요")

rc, o = run({**base, "residence_sido": "경기", "target_sido": "서울"})
check("경기 거주·서울 공고 → 기타지역 가능", st(o, "REGION"), "가능")
check("경기 거주 예치금 300 → 102㎡", o["deposit_max_area"], "전용 102㎡ 이하")
rc, o = run({**base, "residence_sido": "부산", "target_sido": "서울"})
check("부산 거주·서울 공고 → 신청 불가", st(o, "REGION"), "불가")

rc, o = run({**base, "account_period": "1y", "is_householder": False})
check("서울 통장 1년 → 비규제 1순위 가능", st(o, "GEN-1-PRIVATE", "비규제지역"), "가능")
check("서울 통장 1년 → 규제 1순위 불가", st(o, "GEN-1-PRIVATE", "규제지역"), "불가")
rc, o = run({**base, "household_size": "6+"})
check("6인 이상 → 소득 % 계산 불가 확인필요", st(o, "SP-NEWLYWED", "민영"), "확인필요")
rc, o = run({**base, "homeless_household": False, "house_count": "1"})
check("유주택 → 특공 불가", st(o, "SP-NEWLYWED"), "불가")

rc, o = run({**base, "name": "x"})
check("허용 외 키 거부", (rc, "name" in o["error"]), (1, True))
rc, o = run({**base, "monthly_income_manwon": "칠백"})
check("소득 숫자 아님 거부·값 반복 안 함", (rc, "칠백" in o["error"]), (1, False))
rc, o = run({**base, "account_period": "none"})
check("통장 없음 → 불가", o["results"][0]["status"], "불가")
print("\n결과:", "OK" if not fails else f"{fails} FAIL"); sys.exit(1 if fails else 0)
