#!/bin/sh
# git pre-push hook: masterへ出す直前に、masterのCIが赤いままでないかを知らせる。
#
# 有効化方法（このリポジトリでは1回だけ手動実行、他のworktree・clone・CI環境には影響しない）:
#   cp scripts/pre-push.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
#
# 設計方針:
# - **pushを止めない。** 赤の原因が自分の変更とは限らず（他セッションのpushで赤いこともある）、
#   止めると無関係な作業がブロックされる。気づかせるのが目的で、判断は人がする。
# - **コミットではなくpushのタイミングで見る。** 「赤いCIへ新しい変更を積む」のを避けたいので、
#   masterへ出す直前が正しい。毎コミットでネットワークを叩くとコミットが遅くなる。
# - 取得できない・遅い・pythonが無い場合は黙って素通しする（scripts/check_master_ci.pyの
#   docstring参照）。

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

for candidate in python python3 py; do
    if command -v "$candidate" >/dev/null 2>&1; then
        "$candidate" scripts/check_master_ci.py || true
        exit 0
    fi
done
exit 0
