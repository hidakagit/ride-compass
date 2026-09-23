"""振り出し待ちの優先度と、手動タスクの前提の状態。依頼で足した側の機能。

核（core.py）の状態の表の読み書きと、正本から導く読み出しを使う。核は前提の状態を`check`・`status`で
出すときだけ、このモジュールを遅れてimportする。

    python scripts/orchestrate.py priority <Txxx>... <高|中|低>  # 振り出し待ちの優先度を設定する

## 前提の正本

手動タスクの前提（始める前に済ませておくタスク）は、仕掛中のダッシュボードに1件ずつ置く
（kind `前提`・`task`が手動タスク・本文の最初のタスク番号が前提。`pending.prereqs_in`）。ダッシュボードは
`ArtifactData`でしか読めないので、最新のバックアップ（`pending-backup`の書き出し）から読む。状態の表は、
どのタスクが手動中か（`manual`のタスク番号の並び）だけを持つ。前提が判断待ちかは、ダッシュボードに
答えの出ていない問いがあるかで導く。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from orchestration.core import (
    ACTIVE_STATES,
    PLAN_DOC,
    PRIORITIES,
    STOPPED_STATES,
    Context,
    cat_files,
    done_tasks,
    ledger_ids,
    load_board,
    save_board,
)
from orchestration.pending import latest_backup, open_holds, prereqs_in


def prereq_states(ctx: Context, board: dict, tasks: list[str], held: set[str]) -> dict[str, str]:
    """前提ごとの状態: 完了／稼働中／判断待ち／振り出し待ち／停止中／未着手。"""
    done = done_tasks(ctx, tasks)
    listed = ledger_ids(cat_files(ctx.repo, [f"origin/master:{PLAN_DOC}"])[f"origin/master:{PLAN_DOC}"])
    queued = {str(i.get("task")) for i in board.get("queue") or []}
    out = {}
    for task in tasks:
        # 完了は記録の状態と台帳の両方で見る（閉じ忘れで台帳に行が残っているものは完了に数えない）。
        if task in done and task not in listed:
            out[task] = "完了"
            continue
        holders = [a for a in board.get("agents") or [] if a.get("current_task") == task]
        running = [str(a.get("name")) for a in holders if a.get("state") in ACTIVE_STATES]
        if running:
            out[task] = "稼働中（" + "・".join(running) + "）"
        elif task in held:
            out[task] = "判断待ち（ダッシュボードに答えの出ていない問い）"
        elif task in queued:
            out[task] = "振り出し待ち"
        elif any(a.get("state") in STOPPED_STATES for a in holders):
            out[task] = "停止中"
        else:
            out[task] = "未着手"
    return out


def manual_prereqs(ctx: Context, board: dict) -> tuple[list[str], list[str]]:
    """(手動タスクごとの前提の状態の行, 要対応)。前提が残り0なら、開始してよいと知らせる要対応を出す。"""
    manual = [str(t) for t in board.get("manual") or []]
    if not manual:
        return [], []
    latest = latest_backup(ctx)
    if latest is None:
        return ["手動タスクの前提: ダッシュボードの書き出しが無い（pending-backup で書き出す）"], []
    day, items = latest
    lines, due = [], []
    for task in manual:
        prereqs = prereqs_in(items, task)
        if not prereqs:
            lines.append(f"手動{task}の前提: ダッシュボードに無い（{day}の書き出し）")
            continue
        states = prereq_states(ctx, board, prereqs, open_holds(items))
        remaining = [t for t in prereqs if states[t] != "完了"]
        lines.append(f"手動{task}の前提（{day}の書き出し）: {len(prereqs)}件・残り{len(remaining)}件"
                     + "".join(f"\n  {t}: {states[t]}" for t in remaining))
        if not remaining:
            due.append(f"要対応: 手動{task}の前提が残り0件。開始してよいとユーザーへ知らせ、board run manual から外す")
    return lines, due


def cmd_priority(ctx: Context, args: argparse.Namespace) -> int:
    board = load_board(ctx)
    *tasks, level = args.items
    if level not in PRIORITIES:
        raise SystemExit(f"優先度は {'・'.join(PRIORITIES)}: {level}")
    if not tasks:
        raise SystemExit("対象のタスクが無い（Txxx を並べる）")
    items = board.get("queue") or []
    missing = []
    for task in dict.fromkeys(tasks):
        hits = [i for i in items if i.get("task") == task]
        for item in hits:
            item["priority"] = level
        if hits:
            print(f"  {task}: 優先度 {level}")
        else:
            missing.append(task)
    save_board(ctx, board)
    for task in missing:
        print(f"  {task}: 振り出し待ちに無い（稼働中・完了・未登録。登録は board dispatch push）")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py", description="振り出し待ちの優先度")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=os.environ.get("ORCH_DIR"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("priority", help="振り出し待ちの優先度を設定する")
    p.add_argument("items", nargs="+", help="Txxx... と、最後に 高|中|低")
    args = parser.parse_args(argv)
    return cmd_priority(Context(Path(args.repo), args.dir), args)
