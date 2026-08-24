#!/bin/sh
# git pre-commit hook: backend APIモデル変更時のOpenAPI生成物ドリフトを検知する。
#
# 改善計画T279（2026-08-24）: OpenAPI生成物ドリフト（backend/scripts/export_openapi.py→
# frontend/src/types/generated/への再生成漏れ）がT180・T185・T218・fc7bd5a自身（本フック
# 導入の直接原因）と4回再発した。CIのapi-contractジョブは既に存在するが「pushしてから
# 気づく」検知であり、ローカルでのコミット前検知が無かった。
#
# 有効化方法（このリポジトリでは1回だけ手動実行、他のworktree・clone・CI環境には影響しない）:
#   cp scripts/pre-commit-api-contract.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
#
# 設計方針:
# - 高コスト（backend python起動+npm、実測約12秒）なため、ステージ済みファイルが
#   OpenAPI契約に影響しうるパス（backend/app/api/・backend/app/domain/・backend/app/config.py・
#   backend/scripts/export_openapi.py）に該当する場合のみ実行する。docsのみ・frontendのUIのみの
#   コミットでは即座にスキップし、通常のコミット速度を犠牲にしない。
# - venv・npmが見つからない環境（並行セッションのgit worktree等、.venvがworktreeへ複製されない
#   構成を含む）では警告のみでコミットを止めない（soft-fail）。CLAUDE.md「作業ツリーの安全」の
#   並行セッション前提により、他セッションの環境を壊さないことを優先する。
# - 差分が実際に検出された場合のみハードに止める（exit 1）。

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

CHANGED="$(git diff --cached --name-only)"

if ! printf '%s\n' "$CHANGED" | grep -qE '^backend/app/(api|domain)/|^backend/app/config\.py$|^backend/scripts/export_openapi\.py$'; then
    exit 0
fi

VENV_PYTHON="$REPO_ROOT/backend/.venv/Scripts/python.exe"
if [ ! -x "$VENV_PYTHON" ]; then
    VENV_PYTHON="$REPO_ROOT/backend/.venv/bin/python"
fi

if [ ! -x "$VENV_PYTHON" ] || ! command -v npm >/dev/null 2>&1; then
    echo "warning: pre-commit-api-contract: backend/.venvまたはnpmが見つからないためドリフト検知をスキップします" >&2
    echo "         (T279参照。このワークツリーで手動確認する場合: backend/scripts/export_openapi.py → cd frontend && npm run generate:api)" >&2
    exit 0
fi

echo "pre-commit: backend APIモデル変更を検知。OpenAPI生成物ドリフトを確認します (T279)..." >&2

( cd backend && "$VENV_PYTHON" scripts/export_openapi.py >/dev/null 2>&1 )
( cd frontend && npm run generate:api >/dev/null 2>&1 )

if ! git diff --exit-code -- frontend/src/types/generated/ >/dev/null 2>&1; then
    echo "" >&2
    echo "error: OpenAPI生成物にコミット漏れの差分があります (frontend/src/types/generated/)。" >&2
    echo "       backend側のAPIモデル・ルータ・domain定数変更に対し、生成物の再生成・git addが漏れています。" >&2
    echo "       'git diff -- frontend/src/types/generated/' で差分を確認し、git add してから再度コミットしてください。" >&2
    echo "" >&2
    exit 1
fi

echo "pre-commit: OpenAPI生成物ドリフトなし。" >&2
exit 0
