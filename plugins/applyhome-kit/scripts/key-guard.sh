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
        # MCP 서버는 키를 환경변수로 받으므로 /proc/<pid>/environ 등으로 읽을 수 있다
        /proc|/proc/*) block "/proc 접근(프로세스 환경변수의 키 노출 가능)" ;;
      esac
      # 홈 디렉터리 자체나 그 상위를 통째로 검색하면 설정 파일 내용까지 읽힌다
      if [ "$TOOL" = "Grep" ]; then
        case "$HOME_REAL/" in "${rp%/}/"*) block "홈 디렉터리 전체 검색(설정 파일 포함)";; esac
      fi
    done <<<"$PATHS"
    if [ "$TOOL" = "Glob" ] || [ "$TOOL" = "Grep" ]; then
      PAT_ARGS=$(jq -r '.tool_input | (.pattern?, .glob?) | strings' <<<"$INPUT") || block "입력 해석 실패"
      has_eri 'claude\.j|environ' "$PAT_ARGS" && block "사용자 설정 파일·프로세스 환경 탐색"
    fi
    ;;
esac

# 4) Bash: 이 작업 폴더에서는 허용 목록(allowlist) 명령만 실행한다.
#    명령 문자열 금지 목록은 따옴표 끼우기(.cla''ude) 같은 방법으로 우회될 수 있으므로,
#    필요한 명령(판정 스크립트, 안전한 git 하위 명령)만 통과시키는 것을 1차 방어선으로 둔다.
if [ "$TOOL" = "Bash" ]; then
  [ "$(wc -l <<<"$CMD")" -eq 1 ] || block "Bash는 한 줄 명령만 허용"
  ELIG_RE='^python3[[:space:]]+-I[[:space:]]+/[^[:space:];&|`$<>()'"'"'"\\]*/scripts/eligibility\.py([[:space:]]+[a-z_0-9]+=[^[:space:];&|`$<>()'"'"'"\\{}*?]+)*[[:space:]]*$'
  GIT_RE='^git[[:space:]]+(status|diff|log|show|add|commit)([[:space:]]|$)'
  if has_ere "$ELIG_RE" "$CMD"; then
    :
  elif has_ere "$GIT_RE" "$CMD"; then
    has_ere '[$`;&|<>\\]' "$CMD" && block "git 명령에 셸 특수문자 사용 불가"
    has_ere '(^|[[:space:]])(--no-index|--ext-diff|--textconv|--output(=|[[:space:]])|--exec|--upload-pack|-o[[:space:]])' "$CMD" \
      && block "git 외부 파일·외부 프로그램 실행 옵션 사용 불가"
    has_ere '(^|[[:space:]=])(~|\.\.|/)' "$CMD" && block "git 인자에 작업 폴더 밖 경로(~, .., 절대경로) 사용 불가"
  else
    block "이 작업 폴더에서 Bash는 허용 목록(판정 스크립트, git status/diff/log/show/add/commit)만 실행 가능"
  fi

  # 2차 방어선: 따옴표·백슬래시를 지운 정규화 문자열에도 금지 패턴 적용
  NORM=$(tr -d "'\"\\\\" <<<"$CMD") || block "검사기 오류(tr)"
  CFG_PAT='claude\.js|\.claude\.j|claude[[:space:]]+mcp[[:space:]]+(get|add|add-json|add-from-claude-desktop)|/proc/|environ'
  has_eri "$CFG_PAT" "$CMD"  && block "사용자 설정 파일·프로세스 환경 또는 MCP 키 조회·등록 명령"
  has_eri "$CFG_PAT" "$NORM" && block "따옴표로 감싼 설정 파일·프로세스 환경 접근"
  # .c* / .cl?ude* / .* / .[c]* 같은 숨김 파일 글롭
  has_ere '(^|[[:space:]/=])\.(c[^[:space:]/]*)?[*?[]' "$NORM" && block "숨김 파일 글롭(설정 파일 우회 가능)"

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
