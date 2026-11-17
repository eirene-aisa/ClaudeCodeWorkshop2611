# applyhome-kit

청약 조건(범주형)으로 신청 가능한 공급 유형을 판정하고 청약홈의 현재 공고와 맞춰 보여주는 플러그인.

- 사용 폴더: `workspace/` (플러그인은 여기서만 project 스코프로 켜짐). `cd workspace && claude` → `/applyhome-kit:check-eligibility`
- 에이전트: eligibility-checker(판정) · notice-finder(공고 조회) · privacy-reviewer(출력 전 점검)
- 훅(모두 exit 2 차단, 오류 경로 fail-closed): key-guard · url-guard · pii-guard
- 테스트: `bash plugins/applyhome-kit/tests/run-hook-tests.sh`, `python3 -I plugins/applyhome-kit/tests/test_eligibility.py`

## 05 단계: 인증키 등록 (Claude 세션 밖 터미널에서)
공공데이터포털 「한국부동산원_청약홈 분양정보 조회 서비스」 활용신청 후 일반 인증키(Decoding)를 사용한다.

    cd workspace
    claude mcp add --scope local applyhome --env APPLYHOME_API_KEY='<Decoding 키>' \
      -- python3 <이 저장소 절대경로>/plugins/applyhome-kit/mcp/applyhome_server.py
    claude mcp list    # applyhome ✓ Connected

키는 `~/.claude.json`(작업 폴더 밖)에만 저장된다. 채팅이나 `!` 명령으로 넣지 않는다.

## 화면(웹 프런트엔드)
표준 라이브러리만 쓰는 로컬 서버입니다. 127.0.0.1에만 열리고, 키는 `~/.claude.json`의 applyhome MCP 등록값을 시작할 때 메모리로만 읽습니다.

    python3 -I web/server.py                      # http://127.0.0.1:8765
    # code-server(VS Code 웹) 프록시로 볼 때: 그 도메인을 허용 Host로 지정
    APPLYHOME_WEB_ALLOWED_HOSTS=<code-server 도메인> python3 -I web/server.py
    # → https://<code-server 도메인>/proxy/8765/  (끝의 / 필수, VS Code 로그인 필요)

- 판정·공고 조회: 즉시(eligibility.py + MCP 서버 모듈 직접 호출, 무료)
- 에이전트 실행: workspace에서 claude -p로 플러그인 스킬 실행(2~3분, 약 $0.8), 단계를 실시간 표시
- 테스트: `python3 -I web/test_server.py`

## 커밋 키 검사(git 훅)
    bash plugins/applyhome-kit/scripts/install-git-hooks.sh   # pre-commit·commit-msg에 commit-guard.sh 연결
