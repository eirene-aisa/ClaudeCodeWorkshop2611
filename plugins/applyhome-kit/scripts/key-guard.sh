#!/bin/bash
# API 키 가드: 키가 프롬프트·파일·명령·커밋에 나타나거나, 키가 저장된
# 사용자 설정(~/.claude.json)을 열려는 요청을 막는다.
GUARD_NAME="KEY-GUARD"
source "$(dirname "$0")/lib-guard.sh" || { echo "GUARD: 검사기 오류(공용 스크립트 로드 실패) - 차단" >&2; exit 2; }

source "$(dirname "$0")/lib-keys.sh" || { echo "GUARD: 검사기 오류(공용 스크립트 로드 실패) - 차단" >&2; exit 2; }

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

# 4) Bash: 이 작업 폴더에서는 허용 목록 명령(판정 스크립트 실행)만 실행한다.
#    명령 문자열 금지 목록은 따옴표 끼우기 등으로 우회될 수 있고, git 같은 도구는 설정·훅으로
#    다른 프로그램을 실행할 수 있으므로 허용 목록에 넣지 않는다.
#    판정 스크립트는 이 가드와 같은 폴더의 eligibility.py 실제 경로와 정확히 같을 때만 허용한다.
#    (커밋 키 검사는 저장소 git 훅 commit-guard.sh가 맡는다)
if [ "$TOOL" = "Bash" ]; then
  is_elig_cmd "$CMD" || block "이 작업 폴더에서 Bash는 판정 스크립트(python3 -I <플러그인>/scripts/eligibility.py key=value ...) 실행만 가능"

  # 2차 방어선: 따옴표·백슬래시를 지운 정규화 문자열에도 금지 패턴 적용
  NORM=$(tr -d "'\"\\\\" <<<"$CMD") || block "검사기 오류(tr)"
  CFG_PAT='claude\.js|\.claude\.j|claude[[:space:]]+mcp[[:space:]]+(get|add|add-json|add-from-claude-desktop)|/proc/|environ'
  has_eri "$CFG_PAT" "$CMD"  && block "사용자 설정 파일·프로세스 환경 또는 MCP 키 조회·등록 명령"
  has_eri "$CFG_PAT" "$NORM" && block "따옴표로 감싼 설정 파일·프로세스 환경 접근"
  # .c* / .cl?ude* / .* / .[c]* 같은 숨김 파일 글롭
  has_ere '(^|[[:space:]/=])\.(c[^[:space:]/]*)?[*?[]' "$NORM" && block "숨김 파일 글롭(설정 파일 우회 가능)"

fi

exit 0
