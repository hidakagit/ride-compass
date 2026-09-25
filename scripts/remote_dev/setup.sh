#!/bin/bash
# クラウドの環境の「セットアップスクリプト」の本体。claude.aiの環境設定の欄には、これを呼ぶ
# 1行だけを書く（手順はdocs/architecture/setup.md「クラウドのセッション」）。
#
# 環境の初回（と、スクリプトの変更時・約7日ごと）にだけ走り、終了時のファイルシステムが以後の
# セッションの出発点になる。起動したプロセスは残らないので、ここでは依存とイメージ、
# 初期化して止めたDBのボリュームをディスクへ置くだけにし、DBの起動はsession_start.shが毎回行う。
# 5分以内に終える必要があり、失敗してもセッションの開始を止めないよう常に0で抜ける
# （足りないものはsession_start.shが補う）。

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
mkdir -p "$RC_CACHE"
started=$SECONDS

started_dockerd=0
docker info >/dev/null 2>&1 || started_dockerd=1

rc_timed backend rc_ensure_backend &
rc_timed frontend rc_ensure_frontend &
rc_timed db rc_prime_db &
wait

# 保存されるファイルシステムを書きかけの状態にしないよう、自分で起動したdockerdは止める。
if [ "$started_dockerd" = 1 ] && [ -f /var/run/docker.pid ]; then
  kill "$(cat /var/run/docker.pid)" 2>/dev/null
  for _ in $(seq 1 40); do [ -f /var/run/docker.pid ] || break; sleep 0.5; done
fi

rc_log "setup: $(rc_summary)合計$((SECONDS - started))s"
exit 0
