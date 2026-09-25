#!/bin/bash
# SessionStartフックの本体（.claude/settings.json）。クラウドのセッションでだけ動き、
# 手元のセッションでは何もせずに抜ける——フックは全セッションの開始時に走るため、
# 手元で重い処理をすると全員の開始が待たされる。
#
# lockfileが変わっていなければ依存は入れ直さない（setup.shが置いたものを繋ぐだけ）。
# DB（postgres）とRedisはプロセスが保存されないため毎回起動する。

[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
mkdir -p "$RC_CACHE"
started=$SECONDS

rc_timed backend rc_ensure_backend >&2 &
rc_timed frontend rc_ensure_frontend >&2 &
rc_timed db rc_db >&2 &
wait

# この行はセッションの文脈に入る。失敗があれば、流し直して詳細を見る方法を添える。
summary="$(rc_summary)"
echo "開発環境（クラウド）: ${summary}合計$((SECONDS - started))s"
case "$summary" in *失敗*)
  echo "詳細は CLAUDE_CODE_REMOTE=true bash scripts/remote_dev/session_start.sh を流し直すと標準エラーに出る" ;;
esac
exit 0
