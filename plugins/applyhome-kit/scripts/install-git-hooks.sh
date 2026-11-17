#!/bin/bash
# 이 저장소의 .git/hooks에 commit-guard.sh를 pre-commit·commit-msg로 연결한다.
set -euo pipefail
DIR="$(dirname "$(realpath -e -- "${BASH_SOURCE[0]}")")"
HOOKS="$(git -C "$DIR" rev-parse --path-format=absolute --git-path hooks)"
mkdir -p "$HOOKS"
for h in pre-commit commit-msg; do
  printf '#!/bin/bash\nexec bash "%s/commit-guard.sh" "$@"\n' "$DIR" > "$HOOKS/$h"
  chmod +x "$HOOKS/$h"
done
echo "설치됨: $HOOKS/pre-commit, $HOOKS/commit-msg → $DIR/commit-guard.sh"
