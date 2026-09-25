#!/bin/bash
# SessionStartフックとSetupフック（.claude/settings.json）の本体。クラウドのセッションでだけ動き、
# 手元のセッションでは何もせずに抜ける——フックは全セッションの開始時に走るため、
# 手元で重い処理をすると全員の開始が待たされる。
#
# lockfileが変わっていなければ依存は入れ直さない（setup.shが置いたものを繋ぐだけ）。
# DB（postgres）とRedisはプロセスが保存されないため毎回起動する。保存から戻したディスクでは
# 起動に20秒ほどかかるため、フックは待たずに裏で起動し（引数 db）、結果を$RC_DB_STATUSへ書く。
# DBを使う前に待つのはwait_db.sh。
#
# 環境のキャッシュを作る実行（`claude --init-only`）でも、新規のセッション（`claude --init`）でも、
# Setupフック（trigger init）に続いてSessionStartフックが同じ入力で走る。見分けられるのはClaude Code
# 本体（$CLAUDE_PID）の起動引数だけなので、`--init-only`のときはSetupフック（引数 setup）が
# setup.shを流し、SessionStartは何もしない。起動したままのDBがファイルシステムと一緒に保存
# されないようにするため。それ以外のSetupフックは何もしない（SessionStartが用意する）。

[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0

here="$(dirname "${BASH_SOURCE[0]}")"
RC_DB_STATUS=/tmp/ridecompass-db-status
RC_DB_LOG=/tmp/ridecompass-db.log

if [ "$1" = "db" ]; then
  . "$here/lib.sh"
  started=$SECONDS
  if rc_db; then result="ok($((SECONDS - started))s)"; else result="失敗($((SECONDS - started))s)"; fi
  echo "$result" > "$RC_DB_STATUS.tmp" && mv "$RC_DB_STATUS.tmp" "$RC_DB_STATUS"
  exit 0
fi

init_only=0
[ -n "$CLAUDE_PID" ] && tr '\0' '\n' < "/proc/$CLAUDE_PID/cmdline" 2>/dev/null | grep -qx -- --init-only && init_only=1

if [ "$1" = "setup" ]; then
  [ "$init_only" = 1 ] && bash "$here/setup.sh" >&2
  exit 0
fi
[ "$init_only" = 1 ] && exit 0

. "$here/lib.sh"
mkdir -p "$RC_CACHE"
started=$SECONDS

rm -f "$RC_DB_STATUS"
setsid nohup bash "$here/session_start.sh" db > "$RC_DB_LOG" 2>&1 < /dev/null &
echo $! > "$RC_DB_STATUS.pid"

rc_timed backend rc_ensure_backend >&2 &
backend_pid=$!
rc_timed frontend rc_ensure_frontend >&2 &
wait "$backend_pid" $!

# この行はセッションの文脈に入る。失敗があれば、流し直して詳細を見る方法を添える。
summary="$(rc_summary)"
echo "開発環境（クラウド）: ${summary}合計$((SECONDS - started))s。DB・Redisは裏で起動中で、DBを使う前に bash scripts/remote_dev/wait_db.sh で待つ"
case "$summary" in *失敗*)
  echo "詳細は CLAUDE_CODE_REMOTE=true bash scripts/remote_dev/session_start.sh を流し直すと標準エラーに出る" ;;
esac
exit 0
