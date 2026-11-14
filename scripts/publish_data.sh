#!/usr/bin/env bash
# GitHub Actions 전용: 이 도시의 수집 결과를 data 브랜치에 올리고, 두 도시를 합친 data.json 을 만든다.
#   사용: scripts/publish_data.sh <snapshot 파일> <저장 이름: snapshot_hwaseong.json|snapshot_yongin.json> [--pages]
#   --pages: 합친 data.json 과 web/index.html 을 gh-pages(사이트)에도 올린다 (Pages 빌드 횟수 제한 때문에 용인만 사용)
#
# 화성(5분)과 용인(20분) 워크플로가 동시에 올릴 수 있으므로:
#   최신 data 브랜치를 받아 → 내 도시 파일만 바꾸고 → 합쳐서 → "받을 때와 그대로일 때만" 덮어쓴다(force-with-lease).
#   그사이 상대가 먼저 올렸으면 처음부터 다시 한다. data 브랜치는 기록이 쌓이지 않게 항상 커밋 1개.
set -euo pipefail
SNAP=$(realpath "$1"); NAME=$2; PAGES=${3:-}
ROOT=$(pwd)
: "${TOKEN:?TOKEN 환경변수가 필요합니다}"
URL="https://x-access-token:${TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
git config --global user.name "tennis-bot"
git config --global user.email "tennis-bot@users.noreply.github.com"

for attempt in 1 2 3 4 5 6; do
  W=$(mktemp -d)
  LEASE=""
  if git ls-remote --exit-code "$URL" refs/heads/data >/dev/null 2>&1; then
    git clone -q --depth 1 -b data "$URL" "$W/old"
    LEASE=$(git -C "$W/old" rev-parse HEAD)
    cp "$W"/old/snapshot_*.json "$W"/ 2>/dev/null || true
  fi
  cp "$SNAP" "$W/$NAME"
  python -m tennis.export --merge "$W/snapshot_hwaseong.json" "$W/snapshot_yongin.json" --out "$W/data.json"
  mkdir "$W/new" && cp "$W"/snapshot_*.json "$W/data.json" "$W/new/"
  git -C "$W/new" init -q -b data
  git -C "$W/new" add -A
  git -C "$W/new" commit -q -m "${NAME%.json} 갱신 $(TZ=Asia/Seoul date '+%F %H:%M')"
  if git -C "$W/new" push -q --force-with-lease="data:${LEASE}" "$URL" data; then
    echo "data 브랜치 업로드 완료 (시도 $attempt)"
    break
  fi
  echo "다른 수집과 동시에 올려서 거절됨 — 다시 시도 ($attempt)"
  rm -rf "$W"
  sleep $((RANDOM % 8 + 3))
  [ "$attempt" = 6 ] && { echo "업로드 실패"; exit 1; }
done

if [ "$PAGES" = "--pages" ]; then
  P=$(mktemp -d)
  cp "$ROOT/web/index.html" "$W/data.json" "$P"/
  touch "$P/.nojekyll"
  git -C "$P" init -q -b gh-pages
  git -C "$P" add -A
  git -C "$P" commit -q -m "사이트 갱신 $(TZ=Asia/Seoul date '+%F %H:%M')"
  git -C "$P" push -q --force "$URL" gh-pages
  echo "gh-pages 배포 완료"
fi
