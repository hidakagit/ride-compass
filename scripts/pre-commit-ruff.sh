#!/bin/sh
# git pre-commit hook: backendのPython lint（ruff）をステージ済みファイルへ掛ける。
#
# 有効化方法（このリポジトリでは1回だけ手動実行、他のworktree・clone・CI環境には影響しない）:
#   cp scripts/pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# （scripts/pre-commit.shが本チェックと他のチェックを束ねて呼ぶ。）
#
# 設計方針:
# - **ステージ済みの.pyファイルだけを対象にする**。既存の違反で無関係なコミットを止めない
#   （scripts/pre-commit-docs-consistency.shの`--staged`と同じ考え方）。
# - ruffが見つからない環境（.venvがworktreeへ複製されない構成を含む）では警告のみで
#   コミットを止めない（soft-fail）。CLAUDE.md「作業ツリーの安全」の並行セッション前提により、
#   他セッションの環境を壊さないことを優先する。CIが同じチェックをハードに行う。
# - ルールの定義元はbackend/ruff.tomlの1箇所のみ（このスクリプトは選択ルールを持たない）。

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAGED_PY="$(git diff --cached --name-only --diff-filter=ACM | grep -E '^backend/.*\.py$' || true)"
if [ -z "$STAGED_PY" ]; then
    exit 0
fi

VENV_PYTHON="$REPO_ROOT/backend/.venv/Scripts/python.exe"
if [ ! -x "$VENV_PYTHON" ]; then
    VENV_PYTHON="$REPO_ROOT/backend/.venv/bin/python"
fi
if [ ! -x "$VENV_PYTHON" ]; then
    echo "警告: backend/.venv が見つからないためruffチェックをスキップします（CIで検査されます）" >&2
    exit 0
fi
if ! "$VENV_PYTHON" -m ruff --version >/dev/null 2>&1; then
    echo "警告: ruffが未インストールのためチェックをスキップします" >&2
    echo "      有効化するには: backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt" >&2
    exit 0
fi

# ruffはbackend/ruff.tomlを対象ファイルの位置から自動で見つける（backend/へcdして
# リポジトリルートからの相対パスを渡し直す必要はない）。
echo "$STAGED_PY" | while IFS= read -r f; do printf '%s\n' "$f"; done > /tmp/ruff-staged-files.$$
if ! xargs -a /tmp/ruff-staged-files.$$ "$VENV_PYTHON" -m ruff check; then
    rm -f /tmp/ruff-staged-files.$$
    echo "" >&2
    echo "ruffの指摘があります。修正してから再度コミットしてください" >&2
    echo "（自動修正可能なものは: backend/.venv/Scripts/python.exe -m ruff check --fix <対象>）" >&2
    exit 1
fi
rm -f /tmp/ruff-staged-files.$$
