#!/bin/sh
# git pre-commit hook: docs/modules・improvement-plan・docs/tasks・history の機械的整合性を
# scripts/review_checks.py docs --staged で検査する（ステージ済み変更に関係する項目のみ）。
#
# 検査項目（consistency.md「設計 ↔ 実装」節の機械的部分）:
# - docs/modules/*.md へ新しく書き足した行の、実在しないファイル名への参照
# - 新規追加した実装ファイル（backend/app・frontend/src）が docs/modules/*.md のどこにも出現しない
# - docs/improvement-plan.md の [x]/[ ] と docs/tasks/Txxx.md「状態:」行の不一致
#   （improvement-plan.md または docs/tasks/ をステージしたときのみ）
# - ステージした .md 内の history/・docs/tasks/ への死んだリンク
# 経緯記述（記載粒度）の検査は scripts/pre-commit-docs-modules-history.sh が先に行う。
#
# 有効化方法（このリポジトリでは1回だけ手動実行、他のworktree・clone・CI環境には影響しない）:
#   cp scripts/pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
#
# 設計方針:
# - 関係するパス（docs/modules・docs/improvement-plan.md・docs/tasks・backend/app・frontend/src・
#   .claude/commands/review）がステージされていなければ即座にスキップする。
# - 既存の（まだ是正していない）違反は対象にしない（追加行・新規ファイルだけを見る）。
# - python が無い環境では警告のみでコミットを止めない（soft-fail）。

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

CHANGED="$(git diff --cached --name-only)"
if ! printf '%s\n' "$CHANGED" | grep -qE '^docs/modules/|^docs/improvement-plan\.md$|^docs/tasks/|^backend/app/|^frontend/src/|^\.claude/commands/review/'; then
    exit 0
fi

PYTHON=""
for cand in "$REPO_ROOT/backend/.venv/Scripts/python.exe" "$REPO_ROOT/backend/.venv/bin/python"; do
    if [ -x "$cand" ]; then PYTHON="$cand"; break; fi
done
if [ -z "$PYTHON" ]; then
    if command -v python >/dev/null 2>&1; then PYTHON=python
    elif command -v python3 >/dev/null 2>&1; then PYTHON=python3
    fi
fi
if [ -z "$PYTHON" ]; then
    echo "warning: pre-commit-docs-consistency: python が見つからないため docs 整合性チェックをスキップします" >&2
    exit 0
fi

if ! "$PYTHON" scripts/review_checks.py docs --staged; then
    echo "" >&2
    echo "error: docs の整合性チェックに失敗しました（上記の違反を是正してから再度コミットしてください）。" >&2
    echo "       全件監査: python scripts/review_checks.py docs" >&2
    exit 1
fi
exit 0
