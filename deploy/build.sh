#!/bin/bash
# Lambda 배포 패키지(zip) 만들기: 진입점 + 플러그인의 판정 엔진·기준표·공고 모듈(복사, 로직 재작성 없음)
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"; R="$(dirname "$D")"; P="$R/plugins/applyhome-kit"
OUT="$D/build"; rm -rf "$OUT"; mkdir -p "$OUT/pkg"
cp "$D/lambda/handler.py" "$P/scripts/eligibility.py" "$P/scripts/rules.json" "$P/mcp/applyhome_server.py" "$OUT/pkg/"
(cd "$OUT/pkg" && zip -q -X -r ../lambda.zip .)
echo "$OUT/lambda.zip ($(stat -c %s "$OUT/lambda.zip") bytes)"
