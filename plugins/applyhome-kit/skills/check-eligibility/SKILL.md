---
name: check-eligibility
description: 조회할 도시(기본 서울)와 구를 고른 뒤, 사용자의 세부 청약 조건(소득·예비신혼·맞벌이·자산·가점 항목 포함)으로 신청 가능한 공급 유형을 판정하고 청약홈 현재 공고와 맞춰 보여준다. "청약 자격", "넣을 수 있는 청약", "특별공급 해당", "서울 청약 공고", "지금 나온 공고"를 물으면 사용.
---
# 청약 자격·공고 확인 절차

이 작업 폴더에서는 훅이 파일 쓰기, 청약홈 외 URL, 키·개인정보 패턴을 막습니다. 결과는 화면에만 출력합니다.
처음에 한 번 안내합니다: "실명·주민번호·연락처·상세주소는 입력하지 마세요. 구간이나 숫자(만원)로만 답하시면 됩니다."
사용자가 조건을 이미 주었다면 해당 질문은 건너뜁니다.

## 0. 조회 지역 고르기 (서울 위주)
1. AskUserQuestion: "어느 지역 공고를 볼까요?" — 서울 (Recommended) / 경기 / 인천 / 그 외(직접 입력: 시·도 이름)
2. 고른 시·도로 `mcp__applyhome__search_notices`를 sido만 넣어 한 번 호출하고 `sigungu_counts`를 봅니다.
3. AskUserQuestion: "어느 구(시·군)를 볼까요?" — "전체 (N건)" + 공고 수가 많은 구 상위 3개 "강남구 (2건)" 형식.
   공고가 0건이면 그 사실을 알리고 전체 기간(only_open=false)이나 다른 지역을 제안합니다.
→ 고른 값을 `target_sido`, `sigungu`로 기억합니다(sigungu는 공고 조회에만 쓰고 판정에는 넣지 않음).

## 1. 세부 조건 받기 (AskUserQuestion, 한 번에 4문항 이하, 6단계)
| 단계 | 질문 → 키(허용 값) |
|---|---|
| ① 기본 | 나이대 → age_band(19-29·30-34·35-39·40-49·50-64·65+·under19) / 거주 시·도 → residence_sido / 그 시·도 거주기간 → residence_years(lt1·1-2·2+) / 세대주 여부 → is_householder |
| ② 주택·통장 | 세대 주택 보유 → homeless_household + house_count(0·1·2+) / 통장 가입기간 → account_period(none·lt6m·6m-1y·1y…14y·15y+, "3y"=3년 이상 4년 미만) / 예치금 → deposit_band(0-199·200-249·250-299·300-399·400-599·600-699·700-999·1000-1499·1500+) / 5년 내 당첨 → won_within_5y(true·false·unknown) |
| ③ 혼인·자녀 | 혼인 상태 → marital_status(single 미혼·engaged 예비신혼·married 기혼) / 혼인 기간 → married_years(0-2·3-7·7+, 기혼만) / 미성년 자녀 수(태아 포함) → children_count(0·1·2·3+) / 막내 나이·임신 → youngest_child_age(none·under2·2-6·7-18), pregnant, 한부모면 single_parent=true |
| ④ 소득·자산 | 가구원 수 → household_size(1~5·6+) / 가구 월평균소득(세전, 만원) → monthly_income_manwon(정수) / 맞벌이 → dual_income / 부동산 자산 → real_estate(none·le33100 3억3,100만 이하·gt33100·unknown) |
| ⑤ 이력·특공 | 세대원 전원 과거 주택 소유 이력 없음 → first_home_ever / 소득세 5년 이상 납부 → income_tax_5y / 세대 내 과거 특공 당첨 → prior_special_win(true·false·unknown) / 만65세+ 부모 3년 이상 부양 → supports_parent_65_3y |
| ⑥ 가점(선택) | 무주택기간(만30세 또는 혼인 시점부터) → homeless_years(under30_single·lt1·1y…14y·15y+) / 부양가족 수 → dependents_count(0~5·6+) / 국가유공자·장애인 등 기관추천 대상 → institution_eligible / 국민주택 납입 회차 → payments_count(lt6·6-11·12-23·24+) |

- **소득 질문**: 선택지는 가구원 수 기준 구간으로 보여 주되(3인 이하 100%≈753만, 140%≈1,055만, 160%≈1,205만, 200%≈1,507만 / 4인 100%≈880만 …), 정확한 금액을 "Other"로 입력하도록 권합니다. 구간만 고르면 그 구간의 가운데 값을 넣고, 결과에 "구간 선택이라 경계 근처는 확인필요"라고 적습니다.
- 모르는 항목은 빼거나 unknown으로 둡니다. 답을 따옴표·JSON 없이 `key=value` 목록으로 만듭니다.
  예: `age_band=30-34 residence_sido=서울 target_sido=서울 homeless_household=true house_count=0 account_period=3y marital_status=engaged household_size=2 monthly_income_manwon=780 dual_income=true`

## 2. 자격 판정
eligibility-checker 에이전트에 key=value 프로필(target_sido 포함)과 스크립트 절대 경로 `${CLAUDE_PLUGIN_ROOT}/scripts/eligibility.py`를 넘깁니다.

## 3. 공고 찾기
notice-finder 에이전트에는 `notice_filters`(sido, candidate_types, region_status)와 0단계의 `sigungu`**만** 넘깁니다. 프로필 원문·소득 숫자는 넘기지 않습니다.
REGION이 "불가"면 공고 조회 대신 그 사유를 먼저 알리고, 조회는 참고용으로만 진행합니다.

## 4. 맞춰 보기
- 공고가 규제지역(투기과열 SPECLT_RDN_EARTH_AT=Y 또는 조정 MDAT_TRGET_AREA_SECD=Y)이면 판정의 "규제지역" 결과를, 아니면 "비규제지역" 결과를 씁니다.
- 공고 구분: 민영 → by_scope "민영", 국민 → "국민", 공공분양(뉴홈·신혼희망타운 등) → "공공" + SP-YOUTH.
- 특공은 소득 구간(우선/일반/추첨)을 함께 적습니다. 예치금 최대 면적(deposit_max_area) 초과 주택형은 1순위 불가로 표시합니다.
- 가점(GEN-SCORE)이 있으면 가점제 비중이 큰 85㎡ 이하 규제지역 공고에서 참고 정보로 보여줍니다.

## 5. 점검 후 출력
초안을 privacy-reviewer에 넘겨 점검하고, FAIL이 있으면 고친 뒤 출력합니다.
출력: ① 조회 지역(시·도/구)과 기준일 ② 가능한 공급 유형 요약(소득 % 포함) ③ 맞는 현재 공고 표 ④ 확인필요 항목 ⑤ 고지 문구(rules.json disclaimer)와 출처.
파일로 저장하지 않으며, 다음 대화에 쓰도록 조건을 기억하겠다고 하지 않습니다.
