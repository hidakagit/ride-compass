"""仕掛中のダッシュボードの件を、台帳・状態の表と読み合わせる。依頼で足した側の機能。

ダッシュボード（非公開のArtifactのデータベース、collection `pending`）は`ArtifactData`でしか読めず、
このスクリプトからは直接読めない。呼ぶ側（`/dashboard`・`/asks`・`/orchestrate:prereqs`・日次のバックアップ）が
`ArtifactData`の`list`に`out_dir`を付けて全件をファイルへ書き出し、そのディレクトリを`--pending`で渡す
（`<out_dir>/pending/<doc_id>.json`が1件。ファイル名が件のdoc_id）。置き場と1件の形の正本は
`docs/conventions/asking-user.md`「仕掛中のダッシュボード」節。核はこのモジュールをimportしない。

    python scripts/orchestrate.py dashboard --pending <dir>        # 仕掛中のタスクごとの一覧（保存しない）
    python scripts/orchestrate.py pending-backup --pending <dir>   # 全件を日付のファイルへ書き出す（直近14日を残す）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from orchestration.core import (
    ACTIVE_STATES,
    TASK_ID_RE,
    Context,
    audit_pending,
    hm,
    ledger_rows,
    load_board,
    minutes,
    parse_time,
)

#: 人の答えを待つ種類。答え（`answer`）が空なら待っている。
WAITING_KINDS = ("保留", "操作", "改善案", "起票案")
#: 1つのタスクの下に並べる順。件名は見出しになり、この並びには入らない。
KIND_ORDER = ("保留", "操作", "改善案", "前提", "決定")
BACKUP_KEEP_DAYS = 14
BACKUP_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def load_pending(directory: str | Path) -> dict[str, dict]:
    """書き出したダッシュボードの全件 {doc_id: 本体}。`<dir>/pending/*.json`（`out_dir`のまま）か`<dir>/*.json`。"""
    root = Path(directory)
    if (root / "pending").is_dir():
        root = root / "pending"
    if not root.is_dir():
        raise SystemExit(f"ダッシュボードの書き出しが無い: {root}（ArtifactDataのlistにout_dirを付けて書き出す）")
    items = {}
    for path in sorted(root.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            items[path.stem] = json.load(f)
    return items


def answered(item: dict) -> bool:
    return bool(str(item.get("answer") or "").strip())


def prereqs_in(items: dict[str, dict], task: str) -> list[str]:
    """手動タスクの前提（kind `前提`・`task`が手動タスクの件の本文の、最初のタスク番号）を順に。"""
    out = []
    for _, item in sorted(items.items()):
        if item.get("kind") == "前提" and item.get("task") == task:
            m = TASK_ID_RE.search(str(item.get("text") or ""))
            if m and m.group(0) not in out:
                out.append(m.group(0))
    return out


def open_holds(items: dict[str, dict]) -> set[str]:
    """答えの出ていない問い（kind `保留`）を持つタスク。"""
    return {str(i.get("task")) for i in items.values() if i.get("kind") == "保留" and not answered(i)}


def backup_dir(ctx: Context) -> Path:
    return ctx.dir / "pending-backup"


def backups(ctx: Context) -> list[tuple[dt.date, Path]]:
    d = backup_dir(ctx)
    if not d.is_dir():
        return []
    found = []
    for path in d.iterdir():
        if m := BACKUP_NAME_RE.match(path.name):
            found.append((dt.date.fromisoformat(m.group(1)), path))
    return sorted(found)


def backup_count(path: Path) -> int | None:
    try:
        with open(path, encoding="utf-8") as f:
            return len(json.load(f).get("items") or {})
    except (OSError, ValueError):
        return None


def backup_alert(ctx: Context) -> str | None:
    """最新のバックアップが0件で、その前のバックアップに件があったとき（急に0件になった）の知らせ。"""
    found = backups(ctx)
    if len(found) < 2:
        return None
    (prev_day, prev), (last_day, last) = found[-2], found[-1]
    before, now = backup_count(prev), backup_count(last)
    if now == 0 and before:
        return (f"ダッシュボードの件が急に0件になった（{prev_day} {before}件 → {last_day} 0件）。"
                f"消えたのが意図どおりか確かめる。{prev_day}の件は{prev}にある")
    return None


def cmd_backup(ctx: Context, args: argparse.Namespace) -> int:
    items = load_pending(args.pending)
    today = dt.datetime.now().astimezone().date()
    d = backup_dir(ctx)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{today.isoformat()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"saved_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                   "items": items}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    removed = []
    for day, old in backups(ctx):
        if (today - day).days >= BACKUP_KEEP_DAYS:
            old.unlink()
            removed.append(old.name)
    print(f"ダッシュボードの{len(items)}件を{path}へ書き出した"
          + (f"（{BACKUP_KEEP_DAYS}日より前の{'・'.join(removed)}を消した）" if removed else ""))
    if alert := backup_alert(ctx):
        print(f"! {alert}")
        return 1
    return 0


def cmd_dashboard(ctx: Context, args: argparse.Namespace) -> int:
    items = load_pending(args.pending)
    rows = ledger_rows(ctx)
    board_readable = ctx.board_path.exists()
    board = load_board(ctx) if board_readable else {"agents": []}
    now = dt.datetime.now().astimezone()
    workers: dict[str, list[str]] = {}
    for a in board.get("agents") or []:
        task = a.get("current_task")
        if not task or a.get("state") not in ACTIVE_STATES:
            continue
        start = parse_time(a.get("task_first_started")) or parse_time(a.get("started"))
        note = f"{a.get('name')}（{a.get('state')}"
        if start:
            note += f"・着手{hm(start)}から{minutes(now - start)}分"
        if audit_pending(a):
            note += "・監査待ち"
        workers.setdefault(task, []).append(note + "）")
    for task in board.get("manual") or []:
        workers.setdefault(task, []).append("ユーザーが手動で進めている")

    by_task: dict[str, list[tuple[str, dict]]] = {}
    proposals = []
    for doc_id, item in sorted(items.items()):
        task = str(item.get("task") or "")
        if item.get("kind") == "起票案" or not task:
            proposals.append((doc_id, item))
        else:
            by_task.setdefault(task, []).append((doc_id, item))
    tasks = sorted(set(by_task) | set(workers), key=lambda t: (int(m.group(1)) if (m := re.match(r"T(\d+)", t)) else 0, t))

    waiting = sum(1 for i in items.values() if i.get("kind") in WAITING_KINDS and not answered(i))
    done = sum(1 for i in items.values() if i.get("kind") in WAITING_KINDS + ("決定",) and answered(i))
    print(f"仕掛中のタスク {len(tasks)}件・人の手を待っているもの {waiting}件・答えが出て記録へ移す前のもの {done}件"
          f"（ダッシュボード {len(items)}件）")
    if not board_readable:
        print("担当の様子は手元のセッションでだけ出せる（状態の表がこの機械に無い）。ダッシュボードの件と台帳だけを出す")
    if alert := backup_alert(ctx):
        print(f"! {alert}")

    rank = {k: n for n, k in enumerate(KIND_ORDER)}
    for task in tasks:
        entries = by_task.get(task, [])
        subject = next((str(i.get("text")) for _, i in entries if i.get("kind") == "件名"), None)
        row = rows.get(task)
        print(f"\n## {subject or task + '（件名はまだ無い）'}")
        print(f"  台帳: {row['title'] if row else '行が無い'}")
        if board_readable:
            print(f"  進めている: {'・'.join(workers.get(task, [])) or '状態の表に無い'}")
        if not row and not workers.get(task):
            print("  ! 移し忘れ: 台帳に行の無いタスクの件が残っている（開け直すか、答えを記録へ移して消す）")
        for doc_id, item in sorted(entries, key=lambda e: (rank.get(e[1].get("kind"), len(rank)), e[0])):
            kind = item.get("kind")
            if kind == "件名":
                continue
            state = f"答え: {item.get('answer')}" if answered(item) else (
                "待っている" if kind in WAITING_KINDS else "")
            print(f"  - [{kind}] {doc_id}{'  ' + state if state else ''}（{item.get('source') or '書き手不明'}）")
            for line in str(item.get("text") or "").splitlines():
                print(f"      {line}")
    if proposals:
        print("\n## 新しいタスクの案（起票案）")
        for doc_id, item in proposals:
            state = f"答え: {item.get('answer')}" if answered(item) else "待っている"
            print(f"  - [{item.get('kind')}] {doc_id}  {state}（{item.get('source') or '書き手不明'}）")
            for line in str(item.get("text") or "").splitlines():
                print(f"      {line}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py", description="仕掛中のダッシュボードの一覧とバックアップ")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (("dashboard", "仕掛中のタスクごとの一覧（台帳・状態の表と読み合わせる）"),
                            ("pending-backup", "ダッシュボードの全件を日付のファイルへ書き出す")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--pending", required=True, help="ArtifactDataのlistでout_dirに書き出したディレクトリ")
    args = parser.parse_args(argv)
    ctx = Context(Path(args.repo), args.dir)
    return cmd_dashboard(ctx, args) if args.cmd == "dashboard" else cmd_backup(ctx, args)
