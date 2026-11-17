#!/bin/bash
# 가드 훅 공통 헬퍼. 각 가드에서 GUARD_NAME을 정한 뒤 source 한다.
# 원칙: exit 2 = 차단. 검사기를 믿을 수 없는 모든 경로(jq 없음, 입력 해석 실패,
#       grep 오류)도 exit 2로 끝낸다(fail-closed). 감지된 값 자체는 출력하지 않는다.
source "$(dirname "${BASH_SOURCE[0]}")/lib-guard-core.sh" || { echo "GUARD: 검사기 오류(공용 스크립트 로드 실패) - 차단" >&2; exit 2; }

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

