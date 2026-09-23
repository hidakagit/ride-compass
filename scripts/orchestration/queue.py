"""手動タスクの前提と、振り出し待ちの優先度。依頼で足した側の機能。

核（core.py）の状態の表の読み書きと、正本から導く読み出しを使う。核はこのモジュールをimportしない。

    python scripts/orchestrate.py prereqs <Txxx> --pending <dir>   # 手動タスクの前提と、それぞれが済んだか
    python scripts/orchestrate.py priority <Txxx>... <高|中|低|数>  # 振り出し待ちの優先度を設定する
    python scripts/orchestrate.py priority --prereqs-of <Txxx> --pending <dir> <高|中|低|数>  # 手動タスクの前提をまとめて

## 前提の正本

手動タスクの前提（始める前に済ませておくタスク）は、仕掛中のダッシュボードに1件ずつ置く
（kind `前提`・`task`が手動タスク・本文の最初のタスク番号が前提。`pending.prereqs_in`）。ダッシュボードは
`ArtifactData`でしか読めないので、呼ぶ側が書き出したディレクトリを`--pending`で渡す（`pending.py`の冒頭）。
状態の表は、どのタスクが手動中か（`manual`のタスク番号の並び）だけを持つ。前提が判断待ちかは、前提のタスクの
記録に未決の保留があるか（`asks.record_holds`）と、ダッシュボードに答えの出ていない問いがあるかで導く。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestration.asks import record_holds
from orchestration.core import (
    ACTIVE_STATES,
    PLAN_DOC,
    STOPPED_STATES,
    TASKS_DIR,
    Context,
    cat_files,
    done_tasks,
    ledger_ids,
    load_board,
    save_board,
)
from orchestration.pending import load_pending, open_holds, prereqs_in

#: 優先度の語。振り出し待ちは数の小さい順に取り出す。
PRIORITY_WORDS = {"高": 4, "中": 5, "低": 6}
def prereq_states(ctx: Context, board: dict, tasks: list[str], held: set[str]) -> dict[str, str]:
    """前提ごとの状態: 完了／稼働中／判断待ち／振り出し待ち／停止中／未着手。"""
    done = done_tasks(ctx, tasks)
    specs = [f"origin/master:{PLAN_DOC}"] + [f"origin/master:{TASKS_DIR}/{t}.md" for t in tasks]
    blobs = cat_files(ctx.repo, specs)
    listed = ledger_ids(blobs[f"origin/master:{PLAN_DOC}"])
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
        elif record_holds(blobs[f"origin/master:{TASKS_DIR}/{task}.md"] or ""):
            out[task] = "判断待ち（記録に未決の保留）"
        elif task in held:
            out[task] = "判断待ち（ダッシュボードに答えの出ていない問い）"
        elif task in queued:
            out[task] = "振り出し待ち"
        elif any(a.get("state") in STOPPED_STATES for a in holders):
            out[task] = "停止中"
        else:
            out[task] = "未着手"
    return out


def cmd_prereqs(ctx: Context, args: argparse.Namespace) -> int:
    board = load_board(ctx)
    items = load_pending(args.pending)
    prereqs = prereqs_in(items, args.task)
    manual = args.task in (board.get("manual") or [])
    if not prereqs:
        print(f"{args.task} の前提がダッシュボードに無い（kind `前提`・task {args.task} の件で置く。"
              f"{'手動中' if manual else '手動中としても表に無い'}）")
        return 1
    states = prereq_states(ctx, board, prereqs, open_holds(items))
    remaining = [t for t in prereqs if states[t] != "完了"]
    print(f"{args.task} の前提 {len(prereqs)}件・残り{len(remaining)}件"
          f"{'' if manual else '（表の手動中に無い）'}")
    for task in prereqs:
        print(f"  {task}: {states[task]}")
    if not remaining:
        print(f"→ 前提は残り0件。{args.task} を開始してよい")
    return 0


def cmd_priority(ctx: Context, args: argparse.Namespace) -> int:
    board = load_board(ctx)
    *tasks, level = args.items
    if level in PRIORITY_WORDS:
        priority = PRIORITY_WORDS[level]
    elif level.isdigit():
        priority = int(level)
    else:
        raise SystemExit(f"優先度は 高・中・低 か数: {level}")
    if args.prereqs_of:
        if not args.pending:
            raise SystemExit("--prereqs-of には --pending（ダッシュボードの書き出し）が要る")
        tasks = [*tasks, *prereqs_in(load_pending(args.pending), args.prereqs_of)]
    if not tasks:
        raise SystemExit("対象のタスクが無い（Txxx を並べるか --prereqs-of Txxx）")
    items = board.get("queue") or []
    missing = []
    for task in dict.fromkeys(tasks):
        hits = [i for i in items if i.get("task") == task]
        for item in hits:
            item["priority"] = priority
        if hits:
            print(f"  {task}: 優先度 {priority}（{level}）")
        else:
            missing.append(task)
    save_board(ctx, board)
    for task in missing:
        print(f"  {task}: 振り出し待ちに無い（稼働中・完了・未登録。登録は board dispatch push）")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py", description="手動タスクの前提・振り出し待ちの優先度")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prereqs", help="手動タスクの前提の一覧と、それぞれが済んだか")
    p.add_argument("task")
    p.add_argument("--pending", required=True, help="ArtifactDataのlistでout_dirに書き出したディレクトリ")
    p = sub.add_parser("priority", help="振り出し待ちの優先度を設定する")
    p.add_argument("items", nargs="+", help="Txxx... と、最後に 高|中|低|数")
    p.add_argument("--prereqs-of", help="この手動タスクの前提をまとめて対象にする")
    p.add_argument("--pending", help="--prereqs-of のときの、ダッシュボードの書き出し")
    args = parser.parse_args(argv)
    ctx = Context(Path(args.repo), args.dir)
    return cmd_prereqs(ctx, args) if args.cmd == "prereqs" else cmd_priority(ctx, args)
