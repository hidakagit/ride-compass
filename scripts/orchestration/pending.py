"""仕掛中のダッシュボードの件の読み込みとバックアップ。依頼で足した側の機能。

ダッシュボード（非公開のArtifactのデータベース、collection `pending`）は`ArtifactData`でしか読めず、
このスクリプトからは直接読めない。日次のバックアップ（と、最新の状態で前提を見たいとき）が
`ArtifactData`の`list`に`out_dir`を付けて全件をファイルへ書き出し、そのディレクトリを`--pending`で渡す
（`<out_dir>/pending/<doc_id>.json`が1件。ファイル名が件のdoc_id）。置き場と1件の形の正本は
`docs/conventions/asking-user.md`「仕掛中のダッシュボード」節。核はこのモジュールをimportしない。

    python scripts/orchestrate.py pending-backup --pending <dir>   # 全件を日付のファイルへ書き出す（直近14日を残す。移し忘れを知らせる）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

from orchestration.core import (
    TASK_ID_RE,
    TASKS_DIR,
    Context,
    cat_files,
    task_state,
)

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


def latest_backup(ctx: Context) -> tuple[dt.date, dict[str, dict]] | None:
    """最新のバックアップの（日付, 全件）。無い・読めなければNone。"""
    for day, path in reversed(backups(ctx)):
        try:
            with open(path, encoding="utf-8") as f:
                return day, json.load(f).get("items") or {}
        except (OSError, ValueError):
            continue
    return None


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


def left_behind(ctx: Context, items: dict[str, dict]) -> list[str]:
    """記録へ移し忘れた・消し忘れた件。origin/masterの記録の状態から導く。

    閉じたタスク（記録が完了）に残ってよいのは、答えを待っている問い・お願いだけ。答えが出た件は記録へ移し
    （作業が生まれるなら開け直す）、件名はコミットで、前提は手動タスクが閉じたら消す。"""
    tasks = sorted({str(i.get("task")) for i in items.values() if i.get("task")})
    texts = cat_files(ctx.repo, [f"origin/master:{TASKS_DIR}/{t}.md" for t in tasks])
    states = {t: task_state(texts[f"origin/master:{TASKS_DIR}/{t}.md"]) for t in tasks}
    out = []
    for doc_id, item in sorted(items.items()):
        task, kind = str(item.get("task") or ""), item.get("kind")
        if not task:
            continue
        if states[task] is None:
            out.append(f"{doc_id}: {task}の記録がorigin/masterに無い（台帳にも記録にも無いタスクの件）")
        elif states[task] == "完了" and (kind in ("件名", "前提") or answered(item)):
            what = {"件名": "件名（コミットしたら消す）", "前提": "前提（手動タスクが閉じたら消す）"}.get(
                kind, "答え（作業が生まれるなら開け直し、生まれないなら `記録: 答え …` で記録へ移す）")
            out.append(f"{doc_id}: 閉じた{task}に{what}が残っている")
    return out


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
    alerts = [a for a in [backup_alert(ctx)] if a] + left_behind(ctx, items)
    for alert in alerts:
        print(f"! {alert}")
    return 1 if alerts else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py", description="仕掛中のダッシュボードのバックアップ")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=os.environ.get("ORCH_DIR"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pending-backup", help="ダッシュボードの全件を日付のファイルへ書き出す")
    p.add_argument("--pending", required=True, help="ArtifactDataのlistでout_dirに書き出したディレクトリ")
    args = parser.parse_args(argv)
    ctx = Context(Path(args.repo), args.dir)
    return cmd_backup(ctx, args)
