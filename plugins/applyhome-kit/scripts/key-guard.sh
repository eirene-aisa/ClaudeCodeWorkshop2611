#!/bin/bash
# API 키 가드: 키가 프롬프트·파일·명령·커밋에 나타나거나, 키가 저장된
# 사용자 설정(~/.claude.json)을 열려는 요청을 막는다.
GUARD_NAME="KEY-GUARD"
source "$(dirname "$0")/lib-guard.sh"

CFG="$HOME/.claude.json"

# 1) 등록된 키 값 수집: 파일 어디에 있든 env/headers 객체 안의 문자열(16자 이상).
#    원문과 URL 인코딩 형태(@uri)를 함께 대조 목록에 넣는다.
KEYS=""
if [ -e "$CFG" ]; then
  [ -r "$CFG" ] || block "설정 파일을 읽을 수 없음"
  KEYS=$(jq -r '[.. | objects | (.env?, .headers?) | objects | .[] | strings
                 | select(length >= 16) | (., @uri)] | unique | .[]' "$CFG" 2>/dev/null) \
    || block "설정 파일 해석 실패"
fi

# 2) 키처럼 보이는 패턴(등록 전이거나 다른 키인 경우 대비)
KEY_PAT='serviceKey=[^&[:space:]'"'"'"<$]{16,}'
KEY_PAT+='|APPLYHOME_API_KEY[[:space:]]*[=:][[:space:]]*['"'"'"]?[^[:space:]'"'"'"<$]{8,}'
KEY_PAT+='|(--env|[[:space:]]-e)[[:space:]=]+[A-Za-z_][A-Za-z0-9_]*=[^[:space:]<$]{8,}'
KEY_PAT+='|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}'
KEY_PAT+='|[A-Za-z0-9+/]{60,}={1,2}|[A-Za-z0-9%]{60,}%3D%3D'

check_secret_text() {   # $1 = 검사할 텍스트, $2 = 위치 설명
  has_any_fixed "$KEYS" "$1" && block "$2에 등록된 API 키 값이 있음"
  has_eri "$KEY_PAT" "$1" && block "$2에 API 키 형태의 값이 있음"
  return 0
}

check_secret_text "$TEXT" "${EVENT:-입력}"

# 3) 설정 파일 접근 차단 (파일 도구: 경로를 풀어서 비교)
CFG_REAL=$(realpath -m -- "$CFG") || block "경로 해석 실패"
HOME_REAL=$(realpath -m -- "$HOME") || block "경로 해석 실패"
case "$TOOL" in
  Read|Edit|MultiEdit|Write|NotebookEdit|Grep|Glob)
    PATHS=$(jq -r '.tool_input | (.file_path?, .path?, .notebook_path?) | strings' <<<"$INPUT") \
      || block "입력 해석 실패(경로)"
    while IFS= read -r p; do
      [ -n "$p" ] || continue
      case "$p" in "~"|"~/"*) p="$HOME${p#\~}";; esac
      [ "${p#/}" = "$p" ] && p="${HOOK_CWD:-$PWD}/$p"
      rp=$(realpath -m -- "$p") || block "경로 해석 실패"
      case "$rp" in
        "$CFG_REAL"|"$CFG_REAL".*) block "사용자 설정 파일(~/.claude.json) 접근" ;;
      esac
      # 홈 디렉터리 자체나 그 상위를 통째로 검색하면 설정 파일 내용까지 읽힌다
      if [ "$TOOL" = "Grep" ]; then
        case "$HOME_REAL/" in "${rp%/}/"*) block "홈 디렉터리 전체 검색(설정 파일 포함)";; esac
      fi
    done <<<"$PATHS"
    if [ "$TOOL" = "Glob" ] || [ "$TOOL" = "Grep" ]; then
      PAT_ARGS=$(jq -r '.tool_input | (.pattern?, .glob?) | strings' <<<"$INPUT") || block "입력 해석 실패"
      has_eri 'claude\.j' "$PAT_ARGS" && block "사용자 설정 파일(~/.claude.json) 탐색"
    fi
    ;;
esac

# 4) Bash: 설정 파일을 가리키는 표현, 글롭 우회, 키 조회·등록 명령
if [ "$TOOL" = "Bash" ]; then
  CFG_PAT='claude\.js|\.claude\.j|claude[[:space:]]+mcp[[:space:]]+(get|add|add-json|add-from-claude-desktop)'
  has_eri "$CFG_PAT" "$CMD" && block "사용자 설정 파일 또는 MCP 키 조회·등록 명령"
  # .c* / .cl?ude* / .* / .[c]* 같은 숨김 파일 글롭
  has_ere '(^|[[:space:]/'"'"'"=])\.(c[^[:space:]/]*)?[*?[]' "$CMD" && block "숨김 파일 글롭(설정 파일 우회 가능)"
  # 홈 디렉터리 루트를 재귀 검색·복사·압축
  HOME_ROOT='(~|\$HOME|\$\{HOME\}|'"$HOME_REAL"')/?(["'"'"'[:space:];|&)]|$)'
  if has_ere "$HOME_ROOT" "$CMD"; then
    has_ere '(^|[^[:alnum:]_-])(find|rg|ag|ack|tar|zip|rsync|du|grep|cp|cat|strings|od|xxd|base64)([[:space:]]|$)' "$CMD" \
      && block "홈 디렉터리 루트 대상 검색·복사(설정 파일 포함)"
  fi

  # 5) 커밋: 스테이징된 변경과 작업 트리 변경(-a 대비), 메시지를 함께 검사
  if has_ere '(^|[^[:alnum:]_-])git([[:space:]]+-[cC][[:space:]]+[^[:space:]]+)*[[:space:]]+commit([[:space:]]|$)' "$CMD"; then
    command -v git >/dev/null 2>&1 || block "검사기 오류(git 없음)"
    GDIR="${HOOK_CWD:-$PWD}"
    STAGED=$(git -C "$GDIR" diff --cached --no-color 2>/dev/null) || block "커밋 검사 실패(git diff --cached 오류)"
    WORK=$(git -C "$GDIR" diff --no-color 2>/dev/null)            || block "커밋 검사 실패(git diff 오류)"
    check_secret_text "$STAGED" "커밋할 변경"
    check_secret_text "$WORK" "커밋할 변경(-a)"
  fi
fi

exit 0
