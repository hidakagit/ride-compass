"""仕掛中のダッシュボードの件の読み込みとバックアップ。依頼で足した側の機能。

ダッシュボード（非公開のArtifactのデータベース、collection `pending`）は`ArtifactData`でしか読めず、
このスクリプトからは直接読めない。日次のバックアップと、司令塔の定期確認のたびの書き出しが
`ArtifactData`の`list`に`out_dir`を付けて全件をファイルへ書き出し、そのディレクトリを`--pending`で渡す
（`<out_dir>/pending/<doc_id>.json`が1件。ファイル名が件のdoc_id）。置き場と1件の形の正本は
`docs/conventions/asking-user.md`「仕掛中のダッシュボード」節。核はこのモジュールをimportしない。

    python scripts/orchestrate.py pending-backup --pending <dir>   # 全件を日付のファイルへ書き出す（直近14日を残す。移し忘れを知らせる）
    python scripts/orchestrate.py pending-inbox [--pending <dir>]  # 確認中・取り込み待ちの件を、タスクごとの今の持ち主と並べる（既定: 最新のバックアップ）
    python scripts/orchestrate.py pending-waiting [--pending <dir>]  # タブごとの件数と、回答待ちの件（下の「タブの定義」）

`check`は最新のバックアップから、確認中と取り込み待ちの件を持ち主ごとに要対応として出し、どの時刻の書き出しから
読んだかを添える。書き出しが確認間隔の2倍より古ければ、その件がダッシュボードから既に消えているかもしれないと
言う（`inbox_problems`）。書き出しより後に付いた答えは見えないので、司令塔は定期確認のたびに書き出し直す。

## タブの定義

件の振り分けはダッシュボードのページのタブと同じ定義で導く（ページのソースの`inIntake`・`isStaged`・`inCheck`・`stageOf`。
件名と前提はどのタブにも数えない。1件は次の順で最初に当たったタブにだけ入る——`stage_of`）:

- **確認中**（`in_check`）: コメントが残っている件。ただし答えが付いていて、その答えもコメントも取り込み済み
  （`taken_at`が答え・コメントの新しい方より後）の件は除く（記録待ちの流れに乗っている）。コメントは**選択肢以外の回答**
  （問いへの別の答え・質問・直してほしい点）であって、選択肢の答えではない——書いた側が読んで件を書き直し、`comments`を外す。
- **取り込み待ち**（`needs_take`）: 答えかコメントが付いていて、`taken_at`が無いか、答え・コメントの新しい方より前の件。
  `決定`はClaudeが書いた件なので、コメントだけで入る。答えはページの「Claude に反映を頼む」を押されなくても付くので、
  送ったか（`sent_at`）では決めない——問いを置く側が誤って`sent_at`を書いても、答えの無い件は入らない。
  そのうち送った後に答え・コメントが変わっていない件が**送った・取り込み待ち**（`awaiting_take`）、残りが**反映待ち**（`staged`）。
- **回答待ち**（`waiting_answer`）: 答えを待つ種類（保留・操作・改善案・起票案）で、答えが無い件（`answer`の項目が無い件も含む）。
- **記録待ち**（`waiting_record`）: 上のどれでもなく、決定・答え・コメントのどれかがある件。

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
    PRIORITIES,
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
#: ユーザーの答えを待つ種類（ページの「回答待ち」タブに入る種類）。
WAITING_KINDS = ("保留", "操作", "改善案", "起票案")
#: ページのタブの名前（`stage_of`の値）。
ANSWER, CHECK, INTAKE, RECORD = "回答待ち", "確認中", "取り込み待ち", "記録待ち"
#: 確認中の件の扱い方。コメントを選択肢の答えとして取り込まない。
CHECK_HOW = "コメントは選択肢以外の回答。選択肢の答えとして取り込まず、読んで件を書き直し comments を外す"


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


def epoch(value: object) -> float:
    """時刻の文字列を比べられる数へ。無い・読めなければ0（ページの比べ方と同じ）。"""
    t = parse_time(value)
    return t.timestamp() if t else 0.0


def comments_of(item: dict) -> list[dict]:
    raw = item.get("comments")
    return [c for c in raw if isinstance(c, dict) and str(c.get("text") or "").strip()] if isinstance(raw, list) else []


def last_comment(item: dict) -> float:
    raw = item.get("comments")
    return max([0.0] + [epoch(c.get("at")) for c in raw if isinstance(c, dict)]) if isinstance(raw, list) else 0.0


def last_user(item: dict) -> float:
    """ユーザーが最後に手を入れた時刻（答え・コメントの新しい方）。"""
    return max(epoch(item.get("answered_at")), last_comment(item))


def is_item(item: dict) -> bool:
    """タブに数える件か（件名と前提は数えない）。"""
    return item.get("kind") not in ("件名", "前提")


def needs_take(item: dict) -> bool:
    """取り込み待ちか（モジュールの冒頭「取り込み待ち」）。"""
    if not is_item(item):
        return False
    decided = item.get("kind") == "決定"
    if not (comments_of(item) if decided else answered(item) or comments_of(item)):
        return False
    taken = epoch(item.get("taken_at"))
    return not taken or taken < (last_comment(item) if decided else last_user(item))


def staged(item: dict) -> bool:
    """反映待ちか: 取り込み待ちのうち、ユーザーがまだ「Claude に反映を頼む」で送っていない件。"""
    return needs_take(item) and ((answered(item) and not item.get("sent_at"))
                                 or (last_user(item) > 0 and last_user(item) > epoch(item.get("sent_at"))))


def awaiting_take(item: dict) -> bool:
    """送った・取り込み待ちか: 取り込み待ちのうち、送った後に答え・コメントが変わっていない件。"""
    return needs_take(item) and not staged(item)


def in_check(item: dict) -> bool:
    """確認中か（モジュールの冒頭「確認中」）。答えもコメントも取り込み済みの件は記録待ちに回す。"""
    return (is_item(item) and bool(comments_of(item))
            and not (item.get("kind") != "決定" and answered(item) and not needs_take(item)))


def stage_of(item: dict) -> str | None:
    """件が入るタブ（ページの`stageOf`と同じ順）。どれにも当たらない件（件名・前提を含む）はNone。"""
    if not is_item(item):
        return None
    if in_check(item):
        return CHECK
    if needs_take(item):
        return INTAKE
    if item.get("kind") in WAITING_KINDS and not answered(item):
        return ANSWER
    if item.get("kind") == "決定" or answered(item) or comments_of(item):
        return RECORD
    return None


def waiting_answer(item: dict) -> bool:
    """回答待ちか: 答えを待つ種類（保留・操作・改善案・起票案）で、答えもコメントもまだ無い件。"""
    return stage_of(item) == ANSWER


def waiting_record(item: dict) -> bool:
    """記録待ちか: 確認中・取り込み待ち・回答待ちのどれでもなく、決定・答え・コメントのどれかがある件。"""
    return stage_of(item) == RECORD


def priority_of(item: dict) -> str:
    value = str(item.get("priority") or "").strip()
    return value if value in PRIORITIES else "中"


def by_owner(board: dict, items: dict[str, dict], stage: str) -> dict[str, list[str]]:
    """確認中か取り込み待ち（`stage`）の件を、今の持ち主ごとに「doc_id（タスク）題名」で並べる。"""
    out: dict[str, list[str]] = {}
    for doc_id, item in sorted(items.items()):
        if stage_of(item) == stage:
            task = str(item.get("task") or "")
            first = str(item.get("text") or "").splitlines()[0][:60] if item.get("text") else ""
            out.setdefault(owner_of(board, task), []).append(f"{doc_id}（{task or '番号なし'}）{first}")
    return out


#: 確認中・取り込み待ちの件を渡した後にすること。
AFTER = {CHECK: CHECK_HOW, INTAKE: "渡したら taken_at・taken_note を書く"}


def inbox_problems(ctx: Context, board: dict, interval_min: int) -> list[str]:
    """`check`の要対応: 書き出しが無い・古い、確認中と取り込み待ちの件（持ち主ごと。どの書き出しから読んだかを添える）。"""
    latest = latest_dump(ctx)
    how = "ArtifactDataのlistにout_dirを付けて書き出し、pending-backup --pending <dir>"
    if latest is None:
        return [f"要対応: ダッシュボードの書き出しが無い（答えの出た問いを拾えない。{how}）"]
    _, items, saved = latest
    out = []
    age = None if saved is None else int((now() - saved).total_seconds() // 60)
    stale = age is None or age >= 2 * interval_min
    when = "いつか不明" if saved is None else f"{hm(saved.astimezone())}（{age}分前）"
    if stale:
        out.append(f"要対応: ダッシュボードの書き出しが{when}"
                   f"（それより後の答えは見えず、下の件はダッシュボードから既に消えているかもしれない。{how}）")
    source = f"{when}の書き出し" + ("。古いので書き出し直してから扱う" if stale else "")
    for stage in (CHECK, INTAKE):
        for owner, lines in by_owner(board, items, stage).items():
            out.append(f"要対応: {stage}{len(lines)}件 → {owner}: " + "、".join(lines)
                       + f"（{AFTER[stage]}。{source}）")
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
    """確認中・取り込み待ちの件を、タスクごとの今の持ち主と並べる。書き出しを渡さなければ最新のバックアップを読む。"""
    if args.pending:
        items = load_pending(args.pending)
    else:
        latest = latest_backup(ctx)
        if latest is None:
            print("ダッシュボードのバックアップが無い（ArtifactDataのlistにout_dirを付けて書き出し、pending-backup --pending <dir>）")
            return 1
        day, items = latest
        print(f"{day}のバックアップを読んだ（それより後に送られた件は、書き出して pending-backup し直すと見える）")
    board = load_board(ctx)
    found = False
    for stage in (CHECK, INTAKE):
        for owner, lines in by_owner(board, items, stage).items():
            found = True
            print(f"{stage} {owner}: {len(lines)}件（{AFTER[stage]}）")
            for line in lines:
                print(f"  {line}")
    if not found:
        print("確認中・取り込み待ちの件（コメント・答えが出た）は無い")
    return 1 if found else 0


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
    alerts += [f"{doc_id}: 答え・コメントが付いて取り込まれていない（pending-inbox で持ち主を出して回す）"
               for doc_id, item in sorted(items.items()) if staged(item)]
    for alert in alerts:
        print(f"! {alert}")
    return 1 if alerts else 0


def cmd_waiting(ctx: Context, args: argparse.Namespace) -> int:
    """タブごとの件数と、回答待ちの件を優先度（高・中・低）の順に並べる。手で条件を組んで数えない
    （`answer`の項目が無い件を拾い損ねる）。"""
    if args.pending:
        items = load_pending(args.pending)
    else:
        latest = latest_backup(ctx)
        if latest is None:
            print("ダッシュボードのバックアップが無い（ArtifactDataのlistにout_dirを付けて書き出し、pending-backup --pending <dir>）")
            return 1
        day, items = latest
        print(f"{day}のバックアップを読んだ（それより後の答えは、書き出して pending-backup し直すと見える）")
    stages = {doc_id: stage_of(item) for doc_id, item in items.items()}
    waiting = [(doc_id, item) for doc_id, item in sorted(items.items()) if stages[doc_id] == ANSWER]
    checking = [(doc_id, item) for doc_id, item in sorted(items.items()) if stages[doc_id] == CHECK]
    intake = [item for doc_id, item in items.items() if stages[doc_id] == INTAKE]
    by_priority = {p: [(d, i) for d, i in waiting if priority_of(i) == p] for p in PRIORITIES}
    print(f"回答待ち{len(waiting)}件（" + "・".join(f"{p}{len(v)}" for p, v in by_priority.items()) + "）"
          f"／確認中{len(checking)}件"
          f"／取り込み待ち{len(intake)}件（反映待ち{sum(staged(i) for i in intake)}・送った{sum(awaiting_take(i) for i in intake)}）"
          f"／記録待ち{sum(stage == RECORD for stage in stages.values())}件")

    def line(doc_id: str, item: dict) -> str:
        first = str(item.get("text") or "").splitlines()[0][:60] if item.get("text") else ""
        return f"{doc_id}（{item.get('task') or '番号なし'}・{item.get('kind')}）{first}"

    for p, entries in by_priority.items():
        for doc_id, item in entries:
            why = str(item.get("priority_reason") or "").strip()
            print(f"  [{p}] {line(doc_id, item)}" + (f"  — {why}" if why else ""))
    for doc_id, item in checking:
        print(f"  [確認中] {line(doc_id, item)}  — {CHECK_HOW}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py", description="仕掛中のダッシュボードのバックアップ")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=os.environ.get("ORCH_DIR"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pending-backup", help="ダッシュボードの全件を日付のファイルへ書き出す")
    p.add_argument("--pending", required=True, help="ArtifactDataのlistでout_dirに書き出したディレクトリ")
    p = sub.add_parser("pending-inbox", help="確認中・取り込み待ちの件（コメント・答えが出た）を、タスクごとの今の持ち主と並べる")
    p.add_argument("--pending", help="ArtifactDataのlistでout_dirに書き出したディレクトリ（既定: 最新のバックアップ）")
    p = sub.add_parser("pending-waiting", help="タブごとの件数と、回答待ちの件を優先度の順に・確認中の件を並べる")
    p.add_argument("--pending", help="ArtifactDataのlistでout_dirに書き出したディレクトリ（既定: 最新のバックアップ）")
    args = parser.parse_args(argv)
    ctx = Context(Path(args.repo), args.dir)
    handler = {"pending-inbox": cmd_inbox, "pending-waiting": cmd_waiting, "pending-backup": cmd_backup}[args.cmd]
    return handler(ctx, args)
