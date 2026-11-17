#!/bin/bash
# 등록된 키 값 대조 목록(KEYS)과 키 형태 패턴(KEY_PAT), check_secret_text.
# lib-guard-core.sh를 먼저 source 해야 한다. key-guard.sh와 commit-guard.sh가 함께 쓴다.
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

