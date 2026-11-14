#!/usr/bin/env bash
# 1시간마다 cron에서 실행: 수집 → web/data.json 갱신 → 로그
set -u
cd "$(dirname "$0")"
mkdir -p logs web
LOCK=/tmp/tennis_collect.lock
exec 9>"$LOCK"
flock -n 9 || { echo "$(date '+%F %T') 이전 수집이 아직 실행 중 — 건너뜀" >> logs/collect.log; exit 0; }

{
  echo "=== $(date '+%F %T') 수집 시작"
  if python3 -m tennis.collect --days 14; then
    python3 -m tennis.export
    # 갱신 후 공개(publish) 단계가 정해지면 여기에 추가한다.
    [ -x ./publish.sh ] && ./publish.sh
  else
    echo "수집 실패 (이전 data.json 유지)"
  fi
  echo "=== $(date '+%F %T') 끝"
} >> logs/collect.log 2>&1

# 로그가 너무 커지지 않게 마지막 2000줄만 유지
tail -n 2000 logs/collect.log > logs/collect.log.tmp && mv logs/collect.log.tmp logs/collect.log
