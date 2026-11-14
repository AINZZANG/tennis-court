#!/usr/bin/env bash
# GitHub Actions 전용: 한 번의 실행 안에서 정해진 간격으로 수집을 반복한다.
#   사용: scripts/run_loop.sh <간격(초)> <총 실행 시간(초)> "<한 회차에 실행할 명령>"
# GitHub 의 시간 예약(cron)은 몇 시간씩 늦거나 아예 안 도는 경우가 있어서,
# 실행 하나가 5시간 넘게 머물며 직접 간격을 지키고, 끝나면 워크플로가 다음 실행을 스스로 시작한다.
INTERVAL=$1; TOTAL=$2; CMD=$3
END=$((SECONDS + TOTAL))
n=0
while :; do
  t0=$SECONDS; n=$((n + 1))
  echo "::group::${n}회차 $(date '+%H:%M:%S')"
  bash -c "$CMD" || echo "이번 회차 실패 — 다음 회차에 다시 시도"
  echo "::endgroup::"
  left=$((INTERVAL - (SECONDS - t0)))
  [ $((SECONDS + left)) -ge $END ] && break
  [ "$left" -gt 0 ] && sleep "$left"
done
echo "총 ${n}회 수집 후 종료"
