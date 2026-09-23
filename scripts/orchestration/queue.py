"""振り出し待ちのタスク単位の扱い・手動タスクの前提・優先度。依頼で足した側の機能。

核（core.py）の状態の表の読み書きを使う。核はこのモジュールをimportしない。

    python scripts/orchestrate.py queue migrate                    # 表を正式な形へ移す（1回。変換前の写しを残す）
    python scripts/orchestrate.py prereqs <Txxx> [--add T.. | --remove T..]  # 手動タスクの前提と、それぞれが済んだか
    python scripts/orchestrate.py priority <Txxx>... <高|中|低|数>    # 振り出し待ちの優先度を設定する
    python scripts/orchestrate.py priority --prereqs-of <Txxx> <高|中|低|数>  # その手動タスクの前提をまとめて

## 正式な形

- 振り出し待ち（`queue`）の1行: `task`（Txxx）・`what`・`priority`（小さいほど先）・`added`・
  `after`（前提のTxxx。1件なら文字列、複数なら配列）・`agent`（再開する担当）・`note`。
- 手動タスク（`manual`）: `{Txxx: {"note": ..., "prereqs": [Txxx...], "waiting_decision": [Txxx...]}}`。
  `prereqs`は始める前に済ませておくタスク、`waiting_decision`はユーザー判断待ちのため前提に
  入れないもの（規約「ユーザーが手動で進めているタスク」）。
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from orchestration.core import (
    ACTIVE_STATES,
    PLAN_DOC,
    STOPPED_STATES,
    TASK_ID_RE,
    Context,
    cat_files,
    done_tasks,
    ledger_ids,
    load_board,
    now,
    queue_tasks,
    save_board,
)

#: 優先度の語。振り出し待ちは数の小さい順に取り出す。
PRIORITY_WORDS = {"高": 4, "中": 5, "低": 6}
#: 手動タスクの前提を自由記述で持っていた旧い形（例: t1001_prereqs_remaining）。
LEGACY_PREREQ_KEY_RE = re.compile(r"^t(\d+[a-z0-9-]*)_prereqs_(remaining|waiting_decision)$")


def task_of(item: dict) -> str | None:
    """振り出し待ちの1行のタスク。`task`が無ければ`what`の先頭のTxxx。"""
    if item.get("task"):
        return str(item["task"])
    m = TASK_ID_RE.match(str(item.get("what", "")))
    return m.group(0) if m else None


def manual_entry(board: dict, task: str) -> dict:
    entry = (board.get("manual") or {}).get(task)
    if isinstance(entry, dict):
        entry.setdefault("prereqs", [])
        entry.setdefault("waiting_decision", [])
        return entry
    return {"note": entry or "", "prereqs": [], "waiting_decision": []}


# ---------------------------------------------------------------- migrate


def cmd_migrate(ctx: Context) -> int:
    board = load_board(ctx)
    backup = ctx.board_path.with_name(f"board.{now():%Y%m%d-%H%M%S}.before-migrate.json")
    shutil.copy2(ctx.board_path, backup)
    changed = []
    for item in board.get("queue") or []:
        task = task_of(item)
        if task and item.get("task") != task:
            item["task"] = task
            changed.append(f"queue: {task} に task を付けた")
    manual = board.setdefault("manual", {})
    for task in list(manual):
        if not isinstance(manual[task], dict):
            manual[task] = manual_entry(board, task)
            changed.append(f"manual: {task} を正式な形にした")
    for key in [k for k in board if LEGACY_PREREQ_KEY_RE.match(k)]:
        m = LEGACY_PREREQ_KEY_RE.match(key)
        task, kind = f"T{m.group(1)}", m.group(2)
        entry = manual.setdefault(task, manual_entry(board, task))
        field = "prereqs" if kind == "remaining" else "waiting_decision"
        values = board.pop(key)
        values = values if isinstance(values, list) else [values]
        entry[field] = list(dict.fromkeys([*entry[field], *map(str, values)]))
        changed.append(f"{key} → manual.{task}.{field}（{len(values)}件）")
    if not changed:
        backup.unlink()
        print("既に正式な形（変更なし）")
        return 0
    save_board(ctx, board)
    print(f"変換前の写し: {backup}")
    for line in changed:
        print(f"  {line}")
    return 0


# ---------------------------------------------------------------- prereqs


def prereq_states(ctx: Context, board: dict, tasks: list[str]) -> dict[str, str]:
    """前提ごとの状態: 完了／稼働中／停止中／判断待ち／振り出し待ち／未着手。"""
    done = done_tasks(ctx, tasks)
    plan = cat_files(ctx.repo, [f"origin/master:{PLAN_DOC}"])[f"origin/master:{PLAN_DOC}"]
    listed = ledger_ids(plan)
    decided_open = {str(d.get("task")) for d in board.get("decisions") or [] if not d.get("answer")}
    queued = {task_of(i) for i in board.get("queue") or []}
    out = {}
    for task in tasks:
        # 完了は記録の状態と台帳の両方で見る（閉じ忘れで台帳に行が残っているものは完了に数えない）。
        if task in done and task not in listed:
            out[task] = "完了"
            continue
        holders = [a for a in board.get("agents") or []
                   if a.get("current_task") == task or task in queue_tasks(a)]
        if any(a.get("state") in ACTIVE_STATES for a in holders):
            out[task] = "稼働中（" + "・".join(str(a.get("name")) for a in holders
                                              if a.get("state") in ACTIVE_STATES) + "）"
        elif task in decided_open:
            out[task] = "判断待ち"
        elif task in queued:
            out[task] = "振り出し待ち"
        elif any(a.get("state") in STOPPED_STATES for a in holders):
            out[task] = "停止中"
        else:
            out[task] = "未着手"
    return out


def cmd_prereqs(ctx: Context, args: argparse.Namespace) -> int:
    board = load_board(ctx)
    entry = manual_entry(board, args.task)
    if args.add or args.remove:
        entry["prereqs"] = [t for t in dict.fromkeys([*entry["prereqs"], *(args.add or [])])
                            if t not in (args.remove or [])]
        board.setdefault("manual", {})[args.task] = entry
        save_board(ctx, board)
    prereqs = entry["prereqs"]
    if not prereqs and args.task not in (board.get("manual") or {}):
        print(f"{args.task} は手動タスクとして表に無い（prereqs {args.task} --add T.. で前提を登録する）")
        return 1
    states = prereq_states(ctx, board, prereqs)
    remaining = [t for t in prereqs if states[t] != "完了"]
    print(f"{args.task} の前提 {len(prereqs)}件・残り{len(remaining)}件")
    for task in prereqs:
        print(f"  {task}: {states[task]}")
    for task in entry["waiting_decision"]:
        print(f"  {task}: 判断待ち（前提に入れない。判断が出たら prereqs --add で加える）")
    if not remaining:
        print(f"→ 前提は残り0件。{args.task} を開始してよい")
    return 0


# ---------------------------------------------------------------- priority


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
        tasks = [*tasks, *manual_entry(board, args.prereqs_of)["prereqs"]]
    if not tasks:
        raise SystemExit("対象のタスクが無い（Txxx を並べるか --prereqs-of Txxx）")
    items = board.get("queue") or []
    missing = []
    for task in dict.fromkeys(tasks):
        hits = [i for i in items if task_of(i) == task]
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
    parser = argparse.ArgumentParser(prog="orchestrate.py", description="振り出し待ち・手動タスクの前提・優先度")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue")
    q.add_argument("op", choices=["migrate"])
    p = sub.add_parser("prereqs", help="手動タスクの前提の一覧と、それぞれが済んだか")
    p.add_argument("task")
    p.add_argument("--add", nargs="+")
    p.add_argument("--remove", nargs="+")
    p = sub.add_parser("priority", help="振り出し待ちの優先度を設定する")
    p.add_argument("items", nargs="+", help="Txxx... と、最後に 高|中|低|数")
    p.add_argument("--prereqs-of", help="この手動タスクの前提をまとめて対象にする")
    args = parser.parse_args(argv)
    ctx = Context(Path(args.repo), args.dir)
    if args.cmd == "queue":
        return cmd_migrate(ctx)
    if args.cmd == "prereqs":
        return cmd_prereqs(ctx, args)
    return cmd_priority(ctx, args)
