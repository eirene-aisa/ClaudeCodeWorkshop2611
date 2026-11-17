#!/bin/bash
# 가드 훅 공통 헬퍼. 각 가드에서 GUARD_NAME을 정한 뒤 source 한다.
# 원칙: exit 2 = 차단. 검사기를 믿을 수 없는 모든 경로(jq 없음, 입력 해석 실패,
#       grep 오류)도 exit 2로 끝낸다(fail-closed). 감지된 값 자체는 출력하지 않는다.
set -o pipefail
export LC_ALL=C   # 바이트 단위로 매칭해 로캘 차이에 영향받지 않게 함

block() { echo "${GUARD_NAME:-GUARD}: $1 - 차단" >&2; exit 2; }

command -v jq   >/dev/null 2>&1 || block "검사기 오류(jq 없음)"
command -v grep >/dev/null 2>&1 || block "검사기 오류(grep 없음)"

INPUT=$(cat) || block "입력 읽기 실패"
[ -n "$INPUT" ] || block "입력 해석 실패(빈 입력)"
jq -e 'type == "object"' >/dev/null 2>&1 <<<"$INPUT" || block "입력 해석 실패(JSON 아님)"

EVENT=$(jq -r '.hook_event_name // ""' <<<"$INPUT")   || block "입력 해석 실패(event)"
TOOL=$(jq -r '.tool_name // ""' <<<"$INPUT")          || block "입력 해석 실패(tool_name)"
HOOK_CWD=$(jq -r '.cwd // ""' <<<"$INPUT")            || block "입력 해석 실패(cwd)"
# 검사 대상 텍스트: 프롬프트, 또는 tool_input 안의 모든 문자열(JSON 이스케이프 없이 원문)
TEXT=$(jq -r 'if has("prompt") then (.prompt // "")
              else ([.tool_input // {} | .. | strings] | join("\n")) end' <<<"$INPUT") \
  || block "입력 해석 실패(본문)"
CMD=$(jq -r '.tool_input.command // ""' <<<"$INPUT")  || block "입력 해석 실패(command)"

# grep 래퍼: 0=찾음, 1=없음, 그 밖(오류)=차단. 파이프 대신 here-string을 써서
# pipefail + grep -q 조기 종료로 생기는 SIGPIPE(141) 오판을 피한다.
_rc_check() { [ "$1" -le 1 ] || block "검사기 오류(grep 종료 코드 $1)"; return "$1"; }
has_ere()  { local rc; grep -Eq  -- "$1" <<<"$2"; rc=$?; _rc_check $rc; }
has_eri()  { local rc; grep -Eiq -- "$1" <<<"$2"; rc=$?; _rc_check $rc; }
# 고정 문자열 목록($1, 줄 단위) 중 하나라도 $2에 있으면 0. 목록이 비면 1.
has_any_fixed() {
  local rc
  [ -n "$1" ] || return 1
  grep -Fq -f <(printf '%s\n' "$1") <<<"$2"; rc=$?
  _rc_check $rc
}
