#!/bin/bash
# SessionStartフックとSetupフック（.claude/settings.json）の本体。クラウドのセッションでだけ動き、
# 手元のセッションでは何もせずに抜ける——フックは全セッションの開始時に走るため、
# 手元で重い処理をすると全員の開始が待たされる。
#
# lockfileが変わっていなければ依存は入れ直さない（setup.shが置いたものを繋ぐだけ）。
# DB（postgres）とRedisはプロセスが保存されないため毎回起動する。
#
# 環境のキャッシュを作る実行（`claude --init-only`）でも、Setupフック（trigger init）に続いて
# SessionStartフックが走る。そのSessionStartの入力は普通の開始と見分けがつかないため、
# Setupフック（引数 setup）が同じsession_idの印を残し、SessionStartはそれを見てDBを起動せずに
# 抜ける。起動したままのDBがファイルシステムと一緒に保存されないようにするため。

[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0

here="$(dirname "${BASH_SOURCE[0]}")"

# フックの入力（1行のJSON）からsession_idを取る。手で流したとき（端末・空の入力）は空になる。
input=""
[ -t 0 ] || IFS= read -r -t 5 input
sid="$(printf '%s' "$input" | sed -n 's/.*"session_id" *: *"\([^"]*\)".*/\1/p')"
marker="/tmp/ridecompass-init-only-${sid}"

if [ "$1" = "setup" ]; then
  [ -n "$sid" ] && touch "$marker"
  bash "$here/setup.sh" >&2
  exit 0
fi

if [ -n "$sid" ] && [ -f "$marker" ]; then
  rm -f "$marker"
  exit 0
fi

. "$here/lib.sh"
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
