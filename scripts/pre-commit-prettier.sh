#!/bin/sh
# git pre-commit hook: frontendの書式（prettier）をステージ済みファイルへ掛ける。
#
# 有効化方法（このリポジトリでは1回だけ手動実行、他のworktree・clone・CI環境には影響しない）:
#   cp scripts/pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# （scripts/pre-commit.shが本チェックと他のチェックを束ねて呼ぶ。）
#
# 設計方針:
# - **ステージ済みのファイルだけを対象にする**。既存の未整形ファイル（導入時点で164件）で
#   無関係なコミットを止めないため。書式は触ったものから順に揃っていく
#   （scripts/pre-commit-ruff.shの「既存の違反で無関係なコミットを止めない」と同じ考え方）。
# - **--check ではなく --write で直してから stage し直す**。書式は人が直す価値のある指摘では
#   なく、機械が決めれば済む。落として書き直させるのは手間だけが増える。
# - prettierが見つからない環境（node_modules未インストール等）では警告のみでコミットを
#   止めない（soft-fail）。CLAUDE.md「作業ツリーの安全」の並行セッション前提により、
#   他セッションの環境を壊さないことを優先する。
# - 設定の正本はfrontend/.prettierrc.jsonの1箇所のみ（このスクリプトは書式の指定を持たない）。

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAGED="$(git diff --cached --name-only --diff-filter=ACM | grep -E '^frontend/src/.*\.(ts|tsx|css)$' || true)"
if [ -z "$STAGED" ]; then
    exit 0
fi

if [ ! -x "frontend/node_modules/.bin/prettier" ] && [ ! -f "frontend/node_modules/.bin/prettier" ]; then
    echo "警告: frontend/node_modules にprettierが見つからないため書式チェックをスキップします" >&2
    echo "      有効化するには: cd frontend && npm install" >&2
    exit 0
fi

# prettierへはfrontend/からの相対パスで渡す（.prettierrc.json・.prettierignoreの探索もそこが基点）。
RELATIVE="$(printf '%s\n' "$STAGED" | sed 's#^frontend/##')"
printf '%s\n' "$RELATIVE" > /tmp/prettier-staged-files.$$
if ! (cd frontend && xargs -a /tmp/prettier-staged-files.$$ ./node_modules/.bin/prettier --write --log-level warn); then
    rm -f /tmp/prettier-staged-files.$$
    echo "" >&2
    echo "prettierの実行に失敗しました（構文エラーの可能性）" >&2
    exit 1
fi
rm -f /tmp/prettier-staged-files.$$

# 整形で中身が変わったぶんをコミットへ含める（変わっていなければ何も起きない）。
printf '%s\n' "$STAGED" | while IFS= read -r f; do
    [ -n "$f" ] && git add "$f"
done
