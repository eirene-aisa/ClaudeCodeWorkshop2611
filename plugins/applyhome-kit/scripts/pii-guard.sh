#!/bin/bash
# 개인정보 가드: 식별 가능한 개인정보 입력을 막고, 입력된 조건이 파일로 저장되거나
# 다른 곳으로 나가지 않게 한다. (외부 URL 차단은 url-guard.sh가 맡는다)
GUARD_NAME="PII-GUARD"
source "$(dirname "$0")/lib-guard.sh"

# 1) 식별 가능한 개인정보 패턴 (asset-team-kit dlp-guard.sh의 PAT를 확장)
PII='(^|[^0-9])([0-9]{6}-?[1-8][0-9]{6}|[0-9]{6}-[1-8]([^0-9]|$)'          # 주민·외국인등록번호(앞자리+성별 포함)
PII+='|[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{4}'                                 # 카드번호
PII+='|01[016789]-?[0-9]{3,4}-?[0-9]{4}'                                    # 휴대폰
PII+='|[0-9]{3}-[0-9]{2,6}-[0-9]{5,7})([^0-9]|$)'                           # 계좌번호
PII+='|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}'      # 이메일
PII+='|[^[:space:]]+(로|길)[[:space:]]?[0-9]+(-[0-9]+)?([[:space:],]|번|$)'   # 도로명 상세주소
PII+='|[0-9]+동[[:space:]]?[0-9]+호'                                        # 동·호수
PII+='|(생년월일|생일|출생일)[^0-9]{0,6}[0-9]{2,4}[-./년[:space:]]'          # 생년월일
PII+='|(성명|실명|이름)[[:space:]]*(:|=|은[[:space:]]|는[[:space:]])'        # 이름 기재

has_ere "$PII" "$TEXT" && block "식별 가능한 개인정보 패턴이 있음(실명·주민번호·연락처·상세주소는 입력하지 마세요)"

# 2) 저장 금지: 이 작업 폴더에서는 어떤 파일도 쓰지 않는다
case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    block "파일 저장 금지(입력한 조건이 파일로 남지 않도록 쓰기 도구를 막음)" ;;
esac

if [ "$TOOL" = "Bash" ]; then
  # /dev/null 리다이렉트와 fd 복제(2>&1)는 저장이 아니므로 지우고 나머지 '>'를 찾는다
  STRIPPED=$(sed -E 's#[0-9]?>>?[[:space:]]*/dev/null##g; s#[0-9]?>&[0-9-]##g' <<<"$CMD") \
    || block "검사기 오류(sed)"
  has_ere '>' "$STRIPPED" && block "출력 리다이렉션으로 파일 저장"
  WRITERS='(^|[^[:alnum:]_.-])(tee|cp|mv|dd|install|ln|touch|truncate|sponge|split|sqlite3|tar|zip|gzip|mkdir|mktemp|perl|ruby|node|awk|sed[[:space:]]+-i)([[:space:]]|$)'
  has_ere "$WRITERS" "$CMD" && block "파일을 쓰거나 만들 수 있는 명령"

  # python은 판정 스크립트를 한 줄 key=value 인자로 실행하는 형태만 허용
  # (값에 셸 특수문자·따옴표·공백·줄바꿈이 없어야 함 → 다른 명령을 섞을 수 없음)
  if has_ere '(^|[^[:alnum:]_.-])python[0-9.]*([[:space:]]|$)' "$CMD"; then
    has_ere '^python3[[:space:]]+-I[[:space:]]+/[^[:space:];&|`$<>()'"'"'"\\]*/scripts/eligibility\.py([[:space:]]+[a-z_0-9]+=[^[:space:];&|`$<>()'"'"'"\\{}*?]+)*[[:space:]]*$' "$CMD" \
      || block "python은 'python3 -I <경로>/scripts/eligibility.py key=value ...' 형태만 허용"
    [ "$(wc -l <<<"$CMD")" -eq 1 ] || block "판정 스크립트 실행은 한 줄이어야 함"
  fi
fi

# 3) 외부 전송 금지: 공고 조회 MCP에는 비개인 필터 키만 허용
if [[ "$TOOL" == mcp__applyhome__* ]]; then
  jq -e '(.tool_input // {} | keys) - ["sido","sigungu","date_from","date_to","house_type","only_open","page","house_manage_no","pblanc_no"] | length == 0' \
     >/dev/null 2>&1 <<<"$INPUT" || block "공고 조회 MCP에 허용되지 않은 입력 항목"
fi

exit 0
