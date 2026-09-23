"""手動タスクの前提と、振り出し待ちの優先度。依頼で足した側の機能。

核（core.py）の状態の表の読み書きと、正本から導く読み出しを使う。核はこのモジュールをimportしない。

    python scripts/orchestrate.py prereqs <Txxx>                   # 手動タスクの前提と、それぞれが済んだか
    python scripts/orchestrate.py priority <Txxx>... <高|中|低|数>  # 振り出し待ちの優先度を設定する
    python scripts/orchestrate.py priority --prereqs-of <Txxx> <高|中|低|数>  # その手動タスクの前提をまとめて

## 前提の正本

手動タスクの前提（始める前に済ませておくタスク）は、そのタスク自身の記録（origin/masterの
`docs/records/tasks/Txxx.md`）の`## 前提（並行実行）`節に、1行1件の箇条書きで書く（行の最初の
Txxxが前提）。状態の表は、どのタスクが手動中か（`manual`のタスク番号の並び）だけを持つ。
前提が判断待ちかは、前提のタスクの記録に未決の保留があるか（`decisions.record_holds`）で導く。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from orchestration.core import (
    ACTIVE_STATES,
    PLAN_DOC,
    STOPPED_STATES,
    TASK_ID_RE,
    TASKS_DIR,
    Context,
    cat_files,
    done_tasks,
    ledger_ids,
    load_board,
    save_board,
)
from orchestration.decisions import record_holds

#: 優先度の語。振り出し待ちは数の小さい順に取り出す。
PRIORITY_WORDS = {"高": 4, "中": 5, "低": 6}
PREREQ_HEADING = "## 前提（並行実行）"
BULLET_RE = re.compile(r"^\s*[-*]\s+")


def prereqs_of(ctx: Context, task: str) -> list[str] | None:
    """手動タスクの記録の前提の節から、前提のタスク番号を順に。節が無ければNone。"""
    text = cat_files(ctx.repo, [f"origin/master:{TASKS_DIR}/{task}.md"])[f"origin/master:{TASKS_DIR}/{task}.md"]
    lines = (text or "").splitlines()
    if PREREQ_HEADING not in lines:
        return None
    out = []
    for line in lines[lines.index(PREREQ_HEADING) + 1:]:
        if line.startswith("#"):
            break
        if BULLET_RE.match(line) and (m := TASK_ID_RE.search(line)) and m.group(0) not in out:
            out.append(m.group(0))
    return out


def prereq_states(ctx: Context, board: dict, tasks: list[str]) -> dict[str, str]:
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
        elif task in queued:
            out[task] = "振り出し待ち"
        elif any(a.get("state") in STOPPED_STATES for a in holders):
            out[task] = "停止中"
        else:
            out[task] = "未着手"
    return out


def cmd_prereqs(ctx: Context, args: argparse.Namespace) -> int:
    board = load_board(ctx)
    prereqs = prereqs_of(ctx, args.task)
    manual = args.task in (board.get("manual") or [])
    if prereqs is None:
        print(f"{args.task} の記録に「{PREREQ_HEADING}」節が無い（前提は記録へ書く。"
              f"{'手動中' if manual else '手動中としても表に無い'}）")
        return 1
    states = prereq_states(ctx, board, prereqs)
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
        tasks = [*tasks, *(prereqs_of(ctx, args.prereqs_of) or [])]
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
    p = sub.add_parser("priority", help="振り出し待ちの優先度を設定する")
    p.add_argument("items", nargs="+", help="Txxx... と、最後に 高|中|低|数")
    p.add_argument("--prereqs-of", help="この手動タスクの前提をまとめて対象にする")
    args = parser.parse_args(argv)
    ctx = Context(Path(args.repo), args.dir)
    return cmd_prereqs(ctx, args) if args.cmd == "prereqs" else cmd_priority(ctx, args)
