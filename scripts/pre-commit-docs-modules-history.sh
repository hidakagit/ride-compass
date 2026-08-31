#!/bin/sh
# git pre-commit hook: docs/modules/*.md（モジュール設計書）への経緯記述の混入を検知する。
#
# docs/modules/README.md「記載粒度」節は、このディレクトリの各ファイルへ「今のコードが
# どう動くか」だけを書き、「なぜ今の形になったか」（以前は〜だった／改善計画Txxxで〜に
# 変更した／実機報告・ユーザー指摘の日付付き引用等）は書かないことを定めている。この
# ルールは繰り返し明文化されてきたにもかかわらず、新しいコミットのたびに同種の記述が
# 混入する実績があったため、レビューでの目視確認に頼らず機械的に検知する（2026-08-31）。
#
# 有効化方法（このリポジトリでは1回だけ手動実行、他のworktree・clone・CI環境には影響しない）:
#   cp scripts/pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# （scripts/pre-commit.shが本フックとscripts/pre-commit-api-contract.shの両方を束ねて呼ぶ。
#   本フック単体を直接.git/hooks/pre-commitへcpしても動くが、API契約ドリフト検知を失う。）
#
# 設計方針:
# - ステージ済みのdocs/modules/*.md変更が無ければ即座にスキップする。
# - 全文ではなく「追加された行」（git diff --cached -U0の'+'行）だけを対象にする。
#   既存の（まだ是正していない）違反を巻き込んで無関係なコミットまで止めることを避け、
#   「新しく経緯記述を書き足す」という実際の再発パターンだけを狙って止める。
# - 検知は安価（grepのみ）なため、pre-commit-api-contract.shと異なりsoft-failにしない
#   （venv・npm等の外部依存が無く、失敗時にコミットを通す理由が無い）。

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

CHANGED="$(git diff --cached --name-only -- 'docs/modules/*.md')"
if [ -z "$CHANGED" ]; then
    exit 0
fi

# 禁止パターン（docs/modules/README.md「記載粒度」節の禁止列挙・実例に対応）。
# 「実機/実測で…だったため」系は表現ゆれが大きいため、代表的な言い回しを列挙する。
PATTERN='以前は|従来は|旧「|旧『|改善計画T[0-9]+で|実機報告20|実機フィードバック|実機確認|実機指摘|実測で|判明した|発覚した|指摘を受け|フィードバックを受け|ユーザー指摘20|ユーザー要望20|ユーザー判断'

VIOLATIONS="$(git diff --cached -U0 -- 'docs/modules/*.md' | grep -E '^\+[^+]' | grep -E "$PATTERN" || true)"

if [ -n "$VIOLATIONS" ]; then
    echo "" >&2
    echo "error: docs/modules/*.md への変更に経緯記述（禁止パターン）が含まれています。" >&2
    echo "       docs/modules/README.md「記載粒度」節を参照: 「今のコードがどう動くか」だけを書き、" >&2
    echo "       「なぜ今の形になったか」（以前は/改善計画Txxxで変更した/実機報告2026-08-XX等）は" >&2
    echo "       書かない。必要ならdocs/tasks/Txxx.mdへのリンクを1つ添えるだけにとどめる。" >&2
    echo "       該当行:" >&2
    echo "$VIOLATIONS" | sed 's/^/       /' >&2
    echo "" >&2
    echo "       誤検知の場合（例: 変数名や引用符の都合で偶然一致した等）は、文言を調整して" >&2
    echo "       回避してください。フック自体の一時無効化はgit commit --no-verifyですが、" >&2
    echo "       CLAUDE.mdの方針によりユーザーの明示的な指示が無い限り使わないこと。" >&2
    echo "" >&2
    exit 1
fi

exit 0
