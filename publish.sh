#!/usr/bin/env bash
# web/ 폴더를 GitHub Pages 저장소에 올린다. run_collect.sh 가 수집 후 호출한다.
# 설정: deploy.conf 에 REPO="git@github.com:<아이디>/<저장소>.git"
# 기록이 쌓여 저장소가 커지지 않도록 매번 커밋 1개짜리 브랜치로 강제 푸시한다.
set -euo pipefail
cd "$(dirname "$0")"
[ -f deploy.conf ] || { echo "deploy.conf 없음 — 업로드 건너뜀"; exit 0; }
source deploy.conf
: "${REPO:?deploy.conf 에 REPO 가 필요합니다}"
BRANCH="${BRANCH:-main}"
KEY="${KEY:-$HOME/.ssh/tennis_deploy}"
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
cp web/index.html web/data.json "$OUT"/
touch "$OUT/.nojekyll"
cd "$OUT"
git init -q -b "$BRANCH"
git -c user.name="tennis-bot" -c user.email="tennis-bot@users.noreply.github.com" \
    add -A
git -c user.name="tennis-bot" -c user.email="tennis-bot@users.noreply.github.com" \
    commit -q -m "데이터 갱신 $(date '+%F %H:%M')"
git push -q --force "$REPO" "$BRANCH"
echo "업로드 완료 → $REPO ($BRANCH)"
