#!/bin/bash
# クラウドのセッションで、開始時にsession_start.shが裏で起動したDB・Redisを待つ。起動が
# 終わっていれば即座に返る。手元のセッションでは何もしない（手元のDBは各自が起動する）。

[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0

status=/tmp/ridecompass-db-status
log=/tmp/ridecompass-db.log
pid="$(cat "$status.pid" 2>/dev/null)"

for _ in $(seq 1 240); do
  [ -f "$status" ] && break
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    [ -f "$status" ] && break
    echo "DBの裏の起動が見当たらない。CLAUDE_CODE_REMOTE=true bash scripts/remote_dev/session_start.sh db で起動する（$log）"
    exit 1
  fi
  sleep 0.5
done

result="$(cat "$status" 2>/dev/null)"
case "$result" in
  ok*) echo "DB・Redis: $result"; exit 0 ;;
  "") echo "DBの起動が120秒で終わらない（$log）"; exit 1 ;;
  *) echo "DB・Redis: $result（$log）"; exit 1 ;;
esac
