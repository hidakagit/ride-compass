"""台帳の行を閉じる。依頼で足した側の機能。

    python scripts/orchestrate.py ledger close    # 状態が完了の記録に対応する台帳の行を消してコミットする

並行実行の担当はタスクを閉じるとき`Txxx.md`の`状態:`だけを完了にし、台帳
（`docs/improvement-plan.md`）の行は消さない——台帳は全担当が1行ずつ触る共有のファイルで、
別々のブランチが隣り合った行を消すと取り込み（cherry-pick）で衝突する。行は司令塔が取り込みの
後、pushの前にこのコマンドでまとめて消す（規約「監査の結果」）。

今の作業ツリーのHEADの台帳と記録を読み、`状態: 完了`の記録を指す行を消して、台帳だけの
コミットを1つ作る。消す行が無ければ何もしない。台帳に未コミットの変更があれば止まる。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from orchestration.core import PLAN_DOC, cat_files, git, git_out, task_state

#: 台帳の1行と、それが指す記録（台帳からの相対パス）。番号ではなくリンク先で記録を引く
#: （`T317`の2件目は`T317-2.md`を指す）。
PLAN_ENTRY_RE = re.compile(r"^- \[[ x]\] \[(T\d+[a-z0-9-]*)\]\(([^)]+)\)")


def closed_rows(repo: Path) -> tuple[str, list[tuple[str, str]]] | None:
    """HEADの台帳の本文と、状態が完了の記録を指す行（タスク番号, 行）。台帳が無ければNone。"""
    plan = cat_files(repo, [f"HEAD:{PLAN_DOC}"])[f"HEAD:{PLAN_DOC}"]
    if plan is None:
        return None
    base = PLAN_DOC.rsplit("/", 1)[0]
    entries = [(m.group(1), m.group(2), line) for line in plan.splitlines(keepends=True)
               if (m := PLAN_ENTRY_RE.match(line))]
    specs = {target: f"HEAD:{base}/{target}" for _, target, _ in entries}
    texts = cat_files(repo, list(specs.values()))
    return plan, [(task, line) for task, target, line in entries
                  if task_state(texts[specs[target]]) == "完了"]


def cmd_close(repo: Path) -> int:
    dirty = git_out(repo, "status", "--porcelain", "--", PLAN_DOC)
    if dirty is None:
        print(f"gitの状態を読めません: {repo}")
        return 1
    if dirty:
        print(f"{PLAN_DOC}に未コミットの変更があるので止める（取り込みの途中なら、先に取り込みを終える）")
        return 1
    found = closed_rows(repo)
    if found is None:
        print(f"HEADに{PLAN_DOC}が無い")
        return 1
    plan, rows = found
    if not rows:
        print("台帳に、状態が完了の記録を指す行は無い（消すものなし）")
        return 0
    drop = {line for _, line in rows}
    kept = "".join(line for line in plan.splitlines(keepends=True) if line not in drop)
    (repo / PLAN_DOC).write_bytes(kept.encode("utf-8"))
    tasks = [task for task, _ in rows]
    message = (f"台帳から、状態が完了のタスクの行を消す（{'・'.join(tasks)}）\n\n"
               f"python scripts/orchestrate.py ledger close が、HEADの記録で状態が完了の{len(tasks)}件の行を消した。\n")
    r = git(repo, "commit", "-q", "-m", message, "--", PLAN_DOC)
    if r is None or r.returncode != 0:
        print("コミットに失敗した: " + (r.stderr.decode("utf-8", errors="replace").strip() if r else "git未応答"))
        return 1
    print(f"台帳から{len(tasks)}行を消してコミットした: {'・'.join(tasks)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py ledger", description="台帳の行を閉じる")
    parser.add_argument("--repo", default=".", help="台帳を直す作業ツリー（既定: 今のディレクトリ）")
    parser.add_argument("--dir", default=None, help="使わない（全体の引数との互換のため）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("close", help="状態が完了の記録に対応する台帳の行を消してコミットする")
    args = parser.parse_args(argv)
    repo = Path(git_out(Path(args.repo), "rev-parse", "--show-toplevel") or args.repo)
    return cmd_close(repo)
