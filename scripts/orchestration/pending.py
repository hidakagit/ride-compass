"""仕掛中のダッシュボードの件の読み込みとバックアップ。依頼で足した側の機能。

ダッシュボード（非公開のArtifactのデータベース、collection `pending`）は`ArtifactData`でしか読めず、
このスクリプトからは直接読めない。日次のバックアップと、司令塔の定期確認のたびの書き出しが
`ArtifactData`の`list`に`out_dir`を付けて全件をファイルへ書き出し、そのディレクトリを`--pending`で渡す
（`<out_dir>/pending/<doc_id>.json`が1件。ファイル名が件のdoc_id）。置き場と1件の形の正本は
`docs/conventions/asking-user.md`「仕掛中のダッシュボード」節。核はこのモジュールをimportしない。

    python scripts/orchestrate.py pending-backup --pending <dir>   # 全件を日付のファイルへ書き出す（直近14日を残す。移し忘れを知らせる）
    python scripts/orchestrate.py pending-inbox [--pending <dir>]  # 取り込み待ちの件を、タスクごとの今の持ち主と並べる（既定: 最新のバックアップ）

`check`は最新のバックアップから、取り込み待ちの件を持ち主ごとに要対応として出し、書き出しが確認間隔の2倍より古ければ
それも出す（`inbox_problems`）。書き出しより後に付いた答えは見えないので、司令塔は定期確認のたびに書き出し直す。

## 取り込み待ち

送った件（`sent_at`があり`taken_at`がそれより前か無い）と、答えが出た件（`answer`があり、`taken_at`が無いか`answered_at`より
前）。答えはページの「Claude に反映を頼む」を押されなくても付くので、送ったかだけを見ると答えを見落とす。

## 件の持ち主

件の持ち主は、件を置いたセッションではなく件の`task`（タスク番号）で決まる（`source`は誰が書いたかの記録）。
今の持ち主は読むたびに導く: 状態の表でそのタスクを現在のタスクに持つ担当（稼働中か監査待ち）、無ければ手動中の
タスク（表の`manual`）なら手動のセッション、どちらでもなければ（担当が終わった・セッションが無い・起票案で
番号が無い）今の司令塔。ページに起こされたセッションがどれであっても、この持ち主へ回す。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

from orchestration.core import (
    ACTIVE_STATES,
    TASK_ID_RE,
    TASKS_DIR,
    Context,
    audit_pending,
    cat_files,
    hm,
    in_cloud,
    load_board,
    now,
    parse_time,
    task_state,
)

BACKUP_KEEP_DAYS = 14
#: 送ってからこれだけ経っても取り込まれていない件を、拾われていないとして知らせる。ページの「Claude に反映を
#: 頼む」は起こしたセッションへすぐ届くので、1時間取り込まれなければ、受け取るセッションがいないとみなす。
UNTAKEN_ALERT_MINUTES = 60
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


def answered_untaken(item: dict) -> bool:
    """答えが出て取り込まれていないか: `answer`があり、`taken_at`が無いか`answered_at`より前。"""
    if not answered(item):
        return False
    taken = parse_time(item.get("taken_at"))
    if taken is None:
        return True
    at = parse_time(item.get("answered_at"))
    return at is not None and taken < at


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


def latest_dump(ctx: Context) -> tuple[dt.date, dict[str, dict], dt.datetime | None] | None:
    """最新のバックアップの（日付, 全件, 書き出した時刻）。無い・読めなければNone。"""
    for day, path in reversed(backups(ctx)):
        try:
            with open(path, encoding="utf-8") as f:
                body = json.load(f)
        except (OSError, ValueError):
            continue
        return day, body.get("items") or {}, parse_time(body.get("saved_at"))
    return None


def latest_backup(ctx: Context) -> tuple[dt.date, dict[str, dict]] | None:
    """最新のバックアップの（日付, 全件）。無い・読めなければNone。"""
    latest = latest_dump(ctx)
    return None if latest is None else (latest[0], latest[1])


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


def awaiting_take(item: dict) -> bool:
    """送った・取り込み待ちか: `sent_at`があり、`taken_at`がそれより前か無い。"""
    sent, taken = parse_time(item.get("sent_at")), parse_time(item.get("taken_at"))
    return sent is not None and (taken is None or taken < sent)


def needs_take(item: dict) -> bool:
    """取り込み待ちか（モジュールの冒頭「取り込み待ち」）。"""
    return awaiting_take(item) or answered_untaken(item)


def by_owner(board: dict, items: dict[str, dict]) -> dict[str, list[str]]:
    """取り込み待ちの件を、今の持ち主ごとに「doc_id（タスク）題名」で並べる。"""
    out: dict[str, list[str]] = {}
    for doc_id, item in sorted(items.items()):
        if needs_take(item):
            task = str(item.get("task") or "")
            first = str(item.get("text") or "").splitlines()[0][:60] if item.get("text") else ""
            out.setdefault(owner_of(board, task), []).append(f"{doc_id}（{task or '番号なし'}）{first}")
    return out


def inbox_problems(ctx: Context, board: dict, interval_min: int) -> list[str]:
    """`check`の要対応: 書き出しが無い・古い、取り込み待ちの件（持ち主ごと）。"""
    latest = latest_dump(ctx)
    how = "ArtifactDataのlistにout_dirを付けて書き出し、pending-backup --pending <dir>"
    if latest is None:
        return [f"要対応: ダッシュボードの書き出しが無い（答えの出た問いを拾えない。{how}）"]
    _, items, saved = latest
    out = []
    age = None if saved is None else int((now() - saved).total_seconds() // 60)
    if age is None or age >= 2 * interval_min:
        out.append(f"要対応: ダッシュボードの書き出しが{'いつか不明' if age is None else f'{age}分前'}"
                   f"（それより後の答えは見えない。{how}）")
    for owner, lines in by_owner(board, items).items():
        out.append(f"要対応: 取り込み待ち{len(lines)}件 → {owner}: " + "、".join(lines)
                   + "（渡したら taken_at・taken_note を書く）")
    return out


def owner_of(board: dict, task: str) -> str:
    """件の今の持ち主（モジュールの冒頭「件の持ち主」）。"""
    if not task:
        return "司令塔（起票案）"
    holders = [a for a in board.get("agents") or []
               if a.get("current_task") == task and (a.get("state") in ACTIVE_STATES or audit_pending(a))]
    if holders:
        a = holders[0]
        if in_cloud(a):
            # クラウドのセッションはダッシュボードの答えを取りに来ないので、司令塔が片方向で届ける。
            to = (f"宛先: {a['session']}" if a.get("session")
                  else f"宛先のセッション名が表に無い。board set {a.get('name')} session=<セッション名>")
            return f"担当 {a.get('name')}（{a.get('state')}、クラウド。司令塔がSendMessageで届ける（{to}））"
        return f"担当 {a.get('name')}（{a.get('state')}。司令塔が渡す）"
    if task in [str(t) for t in board.get("manual") or []]:
        return "手動のセッション（始めと区切りに自分のタスクの件を拾う）"
    return "司令塔（持ち主の担当・セッションがいない）"


def untaken(items: dict[str, dict], minutes: int = UNTAKEN_ALERT_MINUTES) -> list[str]:
    """送ってから`minutes`分経っても取り込まれていない件。"""
    at = now()
    out = []
    for doc_id, item in sorted(items.items()):
        sent = parse_time(item.get("sent_at"))
        if awaiting_take(item) and sent is not None and (at - sent).total_seconds() >= minutes * 60:
            out.append(f"{doc_id}: 送ってから{int((at - sent).total_seconds() // 60)}分、取り込まれていない"
                       f"（{hm(sent.astimezone())}に送った。pending-inbox で持ち主を出して回す）")
    return out


def cmd_inbox(ctx: Context, args: argparse.Namespace) -> int:
    """取り込み待ちの件を、タスクごとの今の持ち主と並べる。書き出しを渡さなければ最新のバックアップを読む。"""
    if args.pending:
        items = load_pending(args.pending)
    else:
        latest = latest_backup(ctx)
        if latest is None:
            print("ダッシュボードのバックアップが無い（ArtifactDataのlistにout_dirを付けて書き出し、pending-backup --pending <dir>）")
            return 1
        day, items = latest
        print(f"{day}のバックアップを読んだ（それより後に送られた件は、書き出して pending-backup し直すと見える）")
    owners = by_owner(load_board(ctx), items)
    if not owners:
        print("取り込み待ちの件（送った・答えが出た）は無い")
        return 0
    for owner, lines in owners.items():
        print(f"{owner}: {len(lines)}件")
        for line in lines:
            print(f"  {line}")
    return 1


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
    alerts = [a for a in [backup_alert(ctx)] if a] + left_behind(ctx, items) + untaken(items)
    alerts += [f"{doc_id}: 答えが出て取り込まれていない（pending-inbox で持ち主を出して回す）"
               for doc_id, item in sorted(items.items()) if answered_untaken(item) and not awaiting_take(item)]
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
    p = sub.add_parser("pending-inbox", help="取り込み待ちの件（送った・答えが出た）を、タスクごとの今の持ち主と並べる")
    p.add_argument("--pending", help="ArtifactDataのlistでout_dirに書き出したディレクトリ（既定: 最新のバックアップ）")
    args = parser.parse_args(argv)
    ctx = Context(Path(args.repo), args.dir)
    return cmd_inbox(ctx, args) if args.cmd == "pending-inbox" else cmd_backup(ctx, args)
