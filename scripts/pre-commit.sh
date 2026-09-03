#!/bin/sh
# git pre-commit hook（束ね役）: scripts/配下の個別チェックを順に呼ぶ。
#
# 有効化方法（このリポジトリでは1回だけ手動実行、他のworktree・clone・CI環境には影響しない）:
#   cp scripts/pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
#
# 個別チェックを直接.git/hooks/pre-commitへcpすることもできるが、その場合は他方の
# チェックを失う。新しいチェックを追加するときはこのファイルへ1行足すだけでよい。
#
# 実行順序（重要）: 安価なチェック（grepのみ）を先に、高価なチェック（backend python
# 起動+npm、実測約12秒）を後に置く。逆順だと、backend/app変更とdocs/modules違反が
# 同じコミットに混在した場合、「経緯記述を直して再コミット」のたびに無関係な高価な
# チェックまで毎回やり直しになる。安価な方を先に通しておけば、そのイテレーション中は
# 高価なチェックへ到達しない。

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

sh scripts/pre-commit-docs-modules-history.sh
sh scripts/pre-commit-docs-consistency.sh
sh scripts/pre-commit-api-contract.sh
