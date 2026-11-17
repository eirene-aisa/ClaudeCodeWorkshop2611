#!/bin/bash
# URL 가드: 모델이 쓰는 도구로는 https://www.applyhome.co.kr/ 외의 주소에 접근할 수 없게 한다.
# 공고 API(api.odcloud.kr)는 applyhome MCP 서버 코드 안에만 고정되어 있고,
# 모델이 직접 호출하는 것(curl 등)은 막는다.
GUARD_NAME="URL-GUARD"
source "$(dirname "$0")/lib-guard.sh"

ALLOWED_HOST='^(www\.)?applyhome\.co\.kr$'
OWN_MCP='^mcp__applyhome__'

check_url() {   # 허용 URL이면 0, 아니면 차단
  local u="$1" auth host
  [[ "$u" =~ ^https://([^/?#]*)([/?#].*)?$ ]] || block "허용되지 않은 URL 형식(https만 허용)"
  auth="${BASH_REMATCH[1]}"
  case "$auth" in *@*|*:*|*%*|*\\*) block "URL 호스트에 사용자정보·포트·인코딩 문자가 있음";; esac
  host=$(tr '[:upper:]' '[:lower:]' <<<"$auth") || block "URL 해석 실패"
  has_ere "$ALLOWED_HOST" "$host" || block "허용 도메인(www.applyhome.co.kr) 외 URL 접근"
  return 0
}

case "$TOOL" in
  WebFetch)
    URL=$(jq -r '.tool_input.url // ""' <<<"$INPUT") || block "입력 해석 실패(url)"
    [ -n "$URL" ] || block "URL이 비어 있음"
    check_url "$URL"
    ;;
  WebSearch)
    block "웹 검색은 허용되지 않음(청약홈 도메인만 허용)"
    ;;
  Bash)
    # 네트워크 도구는 URL과 무관하게 차단 (리다이렉트·프록시 우회를 원천 차단)
    NET='(^|[^[:alnum:]_.-])(curl|wget|nc|ncat|netcat|socat|telnet|ssh|scp|sftp|ftp|rsync|aria2c|lynx|w3m|links|xh|httpie|http|https|pip3?|npm|npx|pnpm|yarn|uvx?|docker|podman)([[:space:]]|$)'
    NET+='|/dev/(tcp|udp)/|urllib|requests\.|http\.client|aiohttp|httpx|socket|fetch\(|axios|XMLHttpRequest'
    NET+='|git([[:space:]]+-[cC][[:space:]]+[^[:space:]]+)*[[:space:]]+(push|pull|fetch|clone|ls-remote|remote[[:space:]]+add|submodule)'
    has_eri "$NET" "$CMD" && block "Bash 네트워크 접근(curl·wget·소켓·패키지 설치 등)"
    # 명령에 들어 있는 모든 URL을 검사
    URLS=$(grep -Eio '[a-z][a-z0-9+.-]*://[^[:space:]"'"'"'<>`)]+' <<<"$CMD"); rc=$?
    [ "$rc" -le 1 ] || block "검사기 오류(grep 종료 코드 $rc)"
    while IFS= read -r u; do [ -n "$u" ] && check_url "$u"; done <<<"$URLS"
    ;;
  mcp__*|ListMcpResourcesTool|ReadMcpResourceTool|ReadMcpResourceDirTool)
    # 자기 MCP 외의 MCP 도구는 모두 외부 서비스로 나가므로 차단
    has_ere "$OWN_MCP" "$TOOL" || block "허용되지 않은 MCP 도구($TOOL)"
    has_eri '://' "$TEXT" && block "applyhome MCP 입력에 URL이 있음"
    ;;
esac

exit 0
