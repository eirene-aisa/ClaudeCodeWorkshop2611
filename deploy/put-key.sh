#!/bin/bash
# ~/.claude.json에 등록된 applyhome MCP 인증키를 SSM SecureString으로 복사한다.
# 키 값은 화면·명령행 인자(ps로 보임)에 내보내지 않는다. aws cli v2는 파이프(/dev/stdin)를 읽지 못하므로
# 메모리 파일시스템(/dev/shm)의 본인 전용(0600) 임시 파일로 넘기고 즉시 지운다. 출력은 파라미터 버전뿐.
#   사용: bash deploy/put-key.sh [파라미터 이름(기본 /applyhome/api-key)] [리전(기본 us-east-1)]
set -euo pipefail
NAME="${1:-/applyhome/api-key}"; REGION="${2:-us-east-1}"
WS="$(cd "$(dirname "$0")/.." && pwd)/workspace"
command -v jq >/dev/null && command -v aws >/dev/null || { echo "jq와 aws cli가 필요합니다" >&2; exit 1; }
umask 077
TMPD="$(mktemp -d /dev/shm/applyhome.XXXXXX)"; trap 'rm -rf "$TMPD"' EXIT
jq -e --arg ws "$WS" --arg name "$NAME" '
  ([.projects[$ws].mcpServers.applyhome.env.APPLYHOME_API_KEY?]
   + [.projects[]?.mcpServers.applyhome.env.APPLYHOME_API_KEY?]
   + [.mcpServers.applyhome.env.APPLYHOME_API_KEY?]) | map(select(type == "string" and length > 0)) | first
  | if . == null then error("등록된 applyhome 키가 없습니다") else . end
  | {Name: $name, Type: "SecureString", Overwrite: true, Tier: "Standard",
     Description: "applyhome 공개 화면용 청약홈 분양정보 API 인증키", Value: .}' "$HOME/.claude.json" > "$TMPD/in.json"
V="$(aws ssm put-parameter --region "$REGION" --cli-input-json "file://$TMPD/in.json" --query Version --output text)"
rm -rf "$TMPD"
echo "SSM 파라미터 등록 완료: $NAME (버전 $V)"
