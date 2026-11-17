#!/bin/bash
# 가드 훅 회귀 테스트. 가짜 HOME에 가짜 키를 넣은 .claude.json을 두고 종료 코드를 단언한다.
# 사용: bash tests/run-hook-tests.sh
# 테스트용 개인정보 값은 모두 가짜이며, 파일 자체가 DLP 훅에 걸리지 않도록
# 구분자 D를 실행 시점에 끼워 조립한다.
set -u
S="$(cd "$(dirname "$0")/../scripts" && pwd)"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME" "$T/ws"
D='-'
SKN="service""Key"; ENVK="APPLYHOME_API""_KEY"   # 키 패턴 테스트용 이름도 실행 시점에 조립(소스에 키 형태 문자열을 남기지 않음)
FAKE='TESTKEY0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT'           # 가짜 키(실제 키 아님)
FAKE_ENC_SRC='Ab+Cd/Ef==TESTKEYwithSpecialChars0123'
jq -n --arg k "$FAKE" --arg k2 "$FAKE_ENC_SRC" \
  '{projects: {"/x": {mcpServers: {applyhome: {type:"stdio", command:"python3", env:{APPLYHOME_API_KEY:$k}}}}},
    mcpServers: {other: {env:{TOKEN:$k2, SHORT:"1"}}}}' > "$HOME/.claude.json"
ln -s "$HOME/.claude.json" "$T/ws/innocent.txt"
ELIG="$(realpath -e "$S/eligibility.py")"

PASS=0; FAIL=0
run() {  # run <기대코드> <스크립트> <설명> <JSON>   (RUNENV로 env 접두 지정 가능)
  local want="$1" script="$2" desc="$3" json="$4" got
  ${RUNENV:-} bash "$S/$script" <<<"$json" >/dev/null 2>"$T/err"; got=$?
  if [ "$got" = "$want" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL [$script] $desc: want $want got $got ($(head -c 200 "$T/err"))"; fi
}
pre()  { jq -cn --arg t "$1" --argjson i "$2" --arg c "$T/ws" '{hook_event_name:"PreToolUse",tool_name:$t,tool_input:$i,cwd:$c}'; }
bashc(){ pre Bash "$(jq -cn --arg c "$1" '{command:$c}')"; }
prompt(){ jq -cn --arg p "$1" --arg c "$T/ws" '{hook_event_name:"UserPromptSubmit",prompt:$p,cwd:$c}'; }

echo "== key-guard"
run 2 key-guard.sh "프롬프트에 등록 키"        "$(prompt "내 키는 $FAKE 야")"
run 2 key-guard.sh "프롬프트에 URL 인코딩 키"  "$(prompt "값 $(jq -rn --arg k "$FAKE_ENC_SRC" '$k|@uri')")"
run 2 key-guard.sh "Write 내용에 키"          "$(pre Write "$(jq -cn --arg k "$FAKE" '{file_path:"/tmp/a.py",content:("KEY=\""+$k+"\"")}')")"
run 2 key-guard.sh "Bash 명령에 키"           "$(bashc "export X=$FAKE")"
run 2 key-guard.sh "미등록 serviceKey 패턴"    "$(bashc "echo ?${SKN}=QWERTYUIOPASDFGHJKLzxcvbnm123")"
run 2 key-guard.sh "mcp add --env 패턴"        "$(bashc "claude mcp add applyhome --env ${ENVK}=abcd1234efgh -- python3 s.py")"
run 2 key-guard.sh "Read ~/.claude.json"       "$(pre Read '{"file_path":"~/.claude.json"}')"
run 2 key-guard.sh "Read 절대경로"             "$(pre Read "$(jq -cn --arg p "$HOME/.claude.json" '{file_path:$p}')")"
run 2 key-guard.sh "Read 백업 파일"            "$(pre Read "$(jq -cn --arg p "$HOME/.claude.json.backup" '{file_path:$p}')")"
run 2 key-guard.sh "Read 심볼릭 링크 우회"     "$(pre Read '{"file_path":"innocent.txt"}')"
run 2 key-guard.sh "Grep 홈 전체"              "$(pre Grep "$(jq -cn --arg p "$HOME" '{pattern:"KEY",path:$p}')")"
run 2 key-guard.sh "Glob 설정 파일 탐색"       "$(pre Glob '{"pattern":"**/.claude.json"}')"
run 2 key-guard.sh "cat ~/.claude.json"        "$(bashc 'cat ~/.claude.json')"
run 2 key-guard.sh "cat ~/.cl* 글롭 우회"      "$(bashc 'cat ~/.cl*')"
run 2 key-guard.sh "cd ~; cat .c?aude*"        "$(bashc 'cd ~ && cat .c?aude*')"
run 2 key-guard.sh "jq 홈 경로 조합"           "$(bashc 'jq . "$HOME/.claude.json"')"
run 2 key-guard.sh "grep -r 홈 루트"           "$(bashc 'grep -r KEY ~')"
run 2 key-guard.sh "claude mcp get"            "$(bashc 'claude mcp get applyhome')"
run 0 key-guard.sh "일반 프롬프트 통과"         "$(prompt '서울 거주, 무주택, 청약통장 24개월 이상이에요')"
run 0 key-guard.sh "판정 스크립트 실행 통과"     "$(bashc "python3 -I $ELIG age_band=30-34 residence_sido=서울")"
run 2 key-guard.sh "허용 목록 밖 명령(echo) 차단" "$(bashc 'echo hello')"

echo "== key-guard: 보안 리뷰 지적 사항(따옴표 우회·/proc 환경변수)"
run 2 key-guard.sh "따옴표 끼운 경로 우회"      "$(bashc "cat ~/.cla''ude.json")"
run 2 key-guard.sh "큰따옴표 끼운 경로 우회"    "$(bashc 'cat ~/.c"laude".json')"
run 2 key-guard.sh "백슬래시 끼운 경로 우회"    "$(bashc 'cat ~/.cl\aude.json')"
run 2 key-guard.sh "/proc environ (Bash)"        "$(bashc 'cat /proc/1234/environ')"
run 2 key-guard.sh "ps e 환경변수 출력"          "$(bashc 'ps eww -p 1234')"
run 2 key-guard.sh "/proc environ (Read)"        "$(pre Read '{"file_path":"/proc/self/environ"}')"
run 2 key-guard.sh "/proc 심볼릭 경로 (Read)"    "$(pre Read '{"file_path":"/proc/1/../1234/environ"}')"
run 2 key-guard.sh "/proc 검색 (Grep)"           "$(pre Grep '{"pattern":"KEY","path":"/proc"}')"
run 2 key-guard.sh "environ 글롭 (Glob)"         "$(pre Glob '{"pattern":"*/environ","path":"/tmp"}')"
run 2 key-guard.sh "git diff 작업 폴더 밖 파일"  "$(bashc 'git diff ~/.claude.json /dev/null')"
run 2 key-guard.sh "git diff 절대경로"           "$(bashc 'git diff /etc/hosts /dev/null')"
run 2 key-guard.sh "git --no-index"              "$(bashc 'git diff --no-index a b')"
run 2 key-guard.sh "git 명령 치환"               "$(bashc 'git commit -m "$(id)"')"
run 2 key-guard.sh "git -c 설정 주입"            "$(bashc 'git -c core.pager=sh log')"
run 2 key-guard.sh "여러 줄 명령"                "$(bashc "git status
cat x")"
run 2 key-guard.sh "git 명령도 허용 목록 밖"     "$(bashc 'git status')"
run 2 key-guard.sh "git commit도 허용 목록 밖"   "$(bashc 'git commit -m docs')"
run 2 key-guard.sh "다른 위치의 같은 이름 스크립트" "$(bashc 'python3 -I /tmp/x/scripts/eligibility.py age_band=30-34')"
run 2 key-guard.sh "상위 경로(..) 우회"          "$(bashc "python3 -I $S/../scripts/eligibility.py age_band=30-34")"
run 2 key-guard.sh "상대 경로 실행"              "$(bashc 'python3 -I scripts/eligibility.py age_band=30-34')"
run 2 key-guard.sh "-I 없는 실행"                "$(bashc "python3 $ELIG age_band=30-34")"

echo "== commit-guard (저장소 git 훅: pre-commit·commit-msg)"
G="$T/repo"; mkdir -p "$G"; git -C "$G" init -q; git -C "$G" config user.email t@t; git -C "$G" config user.name t
for h in pre-commit commit-msg; do printf '#!/bin/bash\nexec bash "%s/commit-guard.sh" "$@"\n' "$S" > "$G/.git/hooks/$h"; chmod +x "$G/.git/hooks/$h"; done
gcommit() { (cd "$G" && git commit -q -m "$1" >/dev/null 2>"$T/err"); echo $?; }
printf 'key = "%s"\n' "$FAKE" > "$G/conf.py"; git -C "$G" add conf.py
chk() { if [ "$2" = "$3" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL [commit-guard] $1: want $3 got $2 ($(head -c 200 "$T/err"))"; fi; }
chk "스테이징된 변경에 등록 키 → 커밋 실패" "$(gcommit 'add config')" 1
git -C "$G" rm -q --cached conf.py; rm "$G/conf.py"; echo ok > "$G/readme.md"; git -C "$G" add readme.md
chk "커밋 메시지에 등록 키 → 커밋 실패" "$(gcommit "key $FAKE")" 1
chk "커밋 메시지에 키 형태(serviceKey) → 실패" "$(gcommit "url ?${SKN}=QWERTYUIOPASDFGHJKLzxcvbnm123")" 1
chk "깨끗한 커밋 → 성공" "$(gcommit 'docs')" 0
(cd "$T/ws" && bash "$S/commit-guard.sh" >/dev/null 2>&1); chk "git 저장소 밖 실행 → 차단(2)" "$?" 2
mkdir -p "$T/nojq-early"; for b in bash cat realpath dirname; do ln -s "$(command -v $b)" "$T/nojq-early/$b"; done
echo 'x' > "$T/msg"; (cd "$G" && env PATH="$T/nojq-early" bash "$S/commit-guard.sh" "$T/msg" >/dev/null 2>&1); chk "jq·grep 없음 → 차단(2)" "$?" 2

echo "== url-guard"
run 0 url-guard.sh "지정 URL 허용"             "$(pre WebFetch '{"url":"https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancListView.do","prompt":"목록"}')"
run 0 url-guard.sh "도메인 하위 경로 허용"      "$(pre WebFetch '{"url":"https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=1","prompt":"x"}')"
run 2 url-guard.sh "다른 도메인"               "$(pre WebFetch '{"url":"https://example.com/","prompt":"x"}')"
run 2 url-guard.sh "userinfo 우회"             "$(pre WebFetch '{"url":"https://www.applyhome.co.kr@evil.com/","prompt":"x"}')"
run 2 url-guard.sh "접미 도메인 우회"          "$(pre WebFetch '{"url":"https://www.applyhome.co.kr.evil.com/","prompt":"x"}')"
run 2 url-guard.sh "http 평문"                 "$(pre WebFetch '{"url":"http://www.applyhome.co.kr/","prompt":"x"}')"
run 2 url-guard.sh "포트 지정"                 "$(pre WebFetch '{"url":"https://www.applyhome.co.kr:8443/","prompt":"x"}')"
run 2 url-guard.sh "WebSearch"                 "$(pre WebSearch '{"query":"청약"}')"
run 2 url-guard.sh "curl로 API 직접 호출"      "$(bashc 'curl https://api.odcloud.kr/api/x')"
run 2 url-guard.sh "curl 허용 도메인도 차단"   "$(bashc 'curl -L https://www.applyhome.co.kr/')"
run 2 url-guard.sh "python urllib"             "$(bashc 'python3 -c "import urllib.request"')"
run 2 url-guard.sh "/dev/tcp"                  "$(bashc 'exec 3<>/dev/tcp/1.2.3.4/80')"
run 2 url-guard.sh "git push"                  "$(bashc 'git push origin main')"
run 2 url-guard.sh "명령 속 외부 URL"          "$(bashc 'echo https://evil.example/x')"
run 2 url-guard.sh "브라우저 MCP"              "$(pre mcp__plugin_playwright_playwright__browser_navigate '{"url":"https://www.applyhome.co.kr/"}')"
run 2 url-guard.sh "다른 MCP"                  "$(pre mcp__plugin_aws-core_aws-mcp__aws___run_script '{"code":"x"}')"
run 0 url-guard.sh "applyhome MCP 허용"        "$(pre mcp__applyhome__search_notices '{"sido":"서울"}')"
run 0 url-guard.sh "Read는 대상 아님"          "$(pre Read '{"file_path":"/tmp/x"}')"

echo "== pii-guard"
run 2 pii-guard.sh "주민번호"                  "$(prompt "제 번호는 900101${D}1234567 입니다")"
run 2 pii-guard.sh "주민번호 앞자리+성별"      "$(prompt "900101${D}1 이에요")"
run 2 pii-guard.sh "휴대폰"                    "$(prompt "연락처 010${D}1234${D}5678")"
run 2 pii-guard.sh "이메일"                    "$(prompt 'me@example.com 으로 보내줘')"
run 2 pii-guard.sh "상세주소"                  "$(prompt '서울 마포구 월드컵로 123 살아요')"
run 2 pii-guard.sh "동호수"                    "$(prompt '101동 1203호 거주')"
run 2 pii-guard.sh "이름 기재"                 "$(prompt '이름: 홍길동')"
run 2 pii-guard.sh "생년월일"                  "$(prompt '생년월일 1990.01.01')"
run 2 pii-guard.sh "Write 차단"                "$(pre Write '{"file_path":"/tmp/profile.json","content":"{}"}')"
run 2 pii-guard.sh "Edit 차단"                 "$(pre Edit '{"file_path":"/tmp/a","old_string":"a","new_string":"b"}')"
run 2 pii-guard.sh "리다이렉션 저장"           "$(bashc "python3 $ELIG <<'EOF' > out.json
{}
EOF")"
run 2 pii-guard.sh "tee 저장"                  "$(bashc 'echo hi | tee profile.txt')"
run 2 pii-guard.sh "python -c"                 "$(bashc 'python3 -c "open(\"x\",\"w\").write(\"a\")"')"
run 2 pii-guard.sh "판정+명령 치환 혼합"       "$(bashc "python3 -I $ELIG age_band=\$(id)")"
run 2 pii-guard.sh "판정+세미콜론 명령"        "$(bashc "python3 -I $ELIG age_band=30-34; rm -rf x")"
run 2 pii-guard.sh "판정+따옴표 인자"          "$(bashc "python3 -I $ELIG 'age_band=30-34'")"
run 2 pii-guard.sh "heredoc 형태는 이제 차단"  "$(bashc "python3 -I $ELIG <<'EOF'
{}
EOF")"
run 2 pii-guard.sh "-I 없는 실행"              "$(bashc "python3 $ELIG age_band=30-34")"
run 2 pii-guard.sh "다른 python 스크립트"      "$(bashc "python3 -I /tmp/evil.py age_band=30-34")"
run 2 pii-guard.sh "MCP 허용 외 입력"          "$(pre mcp__applyhome__search_notices '{"sido":"서울","age":"34"}')"
run 0 pii-guard.sh "MCP 허용 입력"             "$(pre mcp__applyhome__search_notices '{"sido":"서울","date_from":"2026-11-01","only_open":true}')"
run 0 pii-guard.sh "MCP 구 필터 허용"          "$(pre mcp__applyhome__search_notices '{"sido":"서울","sigungu":"강남구"}')"
run 0 pii-guard.sh "세부 프로필(소득 숫자) 통과" "$(bashc "python3 -I $ELIG age_band=30-34 marital_status=engaged household_size=3 monthly_income_manwon=850 dual_income=true real_estate=le33100 account_period=3y")"
run 0 pii-guard.sh "범주형 프로필 통과"        "$(prompt '만 30~34세, 무주택 세대주, 서울 거주, 통장 24개월 이상, 예치금 300만원, 혼인 3년차, 자녀 1명')"
run 0 pii-guard.sh "판정 스크립트 실행 통과"   "$(bashc "python3 -I $ELIG age_band=30-34 residence_sido=서울 homeless_household=true account_months=24+ deposit_band=300-399 income_band=le140")"
run 0 pii-guard.sh "/dev/null 리다이렉트 통과" "$(bashc 'ls 2>/dev/null')"

echo "== fail-closed (오류 경로도 exit 2)"
NOJQ="$T/nojq"; mkdir -p "$NOJQ"
for b in bash cat grep sed head tr realpath dirname git mktemp; do p=$(command -v $b) && ln -s "$p" "$NOJQ/$b"; done
BADGREP="$T/badgrep"; mkdir -p "$BADGREP"
for b in bash cat sed head tr realpath dirname git jq; do p=$(command -v $b) && ln -s "$p" "$BADGREP/$b"; done
printf '#!/bin/bash\nexit 2\n' > "$BADGREP/grep"; chmod +x "$BADGREP/grep"
OK_JSON="$(prompt '안녕하세요')"
for g in key-guard.sh url-guard.sh pii-guard.sh; do
  RUNENV="env PATH=$NOJQ"    run 2 $g "jq 없음"     "$OK_JSON"
  RUNENV="env PATH=$BADGREP" run 2 $g "grep 오류"   "$(pre WebFetch '{"url":"https://www.applyhome.co.kr/"}')"
  run 2 $g "깨진 JSON 입력"  '{"hook_event_name": "PreToolUse", tool_name'
  run 2 $g "빈 입력"         ''
  run 2 $g "JSON 배열 입력"  '[1,2]'
done
mkdir -p "$T/lonely"; for g in key-guard.sh url-guard.sh pii-guard.sh; do cp "$S/$g" "$T/lonely/"; done
for g in key-guard.sh url-guard.sh pii-guard.sh; do
  bash "$T/lonely/$g" <<<"$OK_JSON" >/dev/null 2>&1; got=$?
  if [ "$got" = 2 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL [$g] 공용 스크립트 없음: want 2 got $got"; fi
done
echo '{ broken' > "$HOME/.claude.json"
run 2 key-guard.sh "깨진 ~/.claude.json"       "$OK_JSON"
rm -f "$HOME/.claude.json"
run 0 key-guard.sh "설정 파일 없음 → 키 0개로 계속" "$OK_JSON"

echo
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
