#!/bin/bash
# 가드 공통 핵심(입력 파싱 없음): block, 검사 도구 확인, grep 래퍼.
# 훅(lib-guard.sh)과 git 훅(commit-guard.sh)이 함께 쓴다.
# 원칙: exit 2 = 차단. 검사기를 믿을 수 없는 모든 경로(jq 없음, 입력 해석 실패,
#       grep 오류)도 exit 2로 끝낸다(fail-closed). 감지된 값 자체는 출력하지 않는다.
set -o pipefail
export LC_ALL=C   # 바이트 단위로 매칭해 로캘 차이에 영향받지 않게 함

block() { echo "${GUARD_NAME:-GUARD}: $1 - 차단" >&2; exit 2; }

command -v jq   >/dev/null 2>&1 || block "검사기 오류(jq 없음)"
command -v grep >/dev/null 2>&1 || block "검사기 오류(grep 없음)"

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

# 판정 스크립트 실행 명령 허용 여부: 이 가드와 같은 폴더의 eligibility.py 실제 경로와
# 정확히 같을 때만, 인자는 key=value(셸 특수문자 없음)일 때만 0을 돌려준다.
ELIG_PATH_REAL=$(realpath -e -- "$(dirname "${BASH_SOURCE[0]}")/eligibility.py" 2>/dev/null) || ELIG_PATH_REAL=""
is_elig_cmd() {
  local cmd="$1" path rp
  [ -n "$ELIG_PATH_REAL" ] || block "검사기 오류(판정 스크립트 경로 확인 불가)"
  [ "$(wc -l <<<"$cmd")" -eq 1 ] || return 1
  has_ere '^python3[[:space:]]+-I[[:space:]]+/[^[:space:];&|`$<>()'"'"'"\\]+([[:space:]]+[a-z_0-9]+=[^[:space:];&|`$<>()'"'"'"\\{}*?]+)*[[:space:]]*$' "$cmd" || return 1
  path=$(awk '{print $3}' <<<"$cmd") || block "검사기 오류(awk)"
  case "$path" in *..*) return 1;; esac
  rp=$(realpath -e -- "$path" 2>/dev/null) || return 1
  [ "$rp" = "$ELIG_PATH_REAL" ] && [ "$path" = "$rp" ]
}
