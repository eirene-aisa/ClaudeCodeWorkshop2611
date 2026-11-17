#!/bin/bash
# git 훅용 키 가드: 스테이징된 변경(pre-commit)과 커밋 메시지(commit-msg)에
# 등록된 API 키 값이나 키 형태 문자열이 있으면 커밋을 막는다.
# 명령 문자열 매칭이 아니라 git이 실제로 커밋하려는 내용을 검사하므로 누가·어디서 커밋하든 적용된다.
#   설치: bash plugins/applyhome-kit/scripts/install-git-hooks.sh
#   동작: 인자 없음 → pre-commit(스테이징 검사) / 인자 1개(메시지 파일) → commit-msg(메시지 검사)
# fail-closed: jq·grep·git 없음, 설정 파일 해석 실패, git 오류는 모두 커밋 중단(exit 2).
GUARD_NAME="COMMIT-GUARD"
DIR="$(dirname "$(realpath -e -- "${BASH_SOURCE[0]}")")" || { echo "COMMIT-GUARD: 경로 확인 실패 - 커밋 중단" >&2; exit 2; }
source "$DIR/lib-guard-core.sh" || { echo "COMMIT-GUARD: 공용 스크립트 로드 실패 - 커밋 중단" >&2; exit 2; }
source "$DIR/lib-keys.sh"       || { echo "COMMIT-GUARD: 공용 스크립트 로드 실패 - 커밋 중단" >&2; exit 2; }
command -v git >/dev/null 2>&1 || block "검사기 오류(git 없음)"

if [ $# -ge 1 ]; then
  [ -r "$1" ] || block "커밋 메시지 파일을 읽을 수 없음"
  MSG=$(cat -- "$1") || block "커밋 메시지 읽기 실패"
  check_secret_text "$MSG" "커밋 메시지"
else
  STAGED=$(git diff --cached --no-color --no-ext-diff --no-textconv 2>/dev/null) || block "git diff --cached 오류"
  check_secret_text "$STAGED" "커밋할 변경"
fi
exit 0
