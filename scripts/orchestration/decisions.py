"""ユーザーの判断待ち（状態の表のdecisionsと、タスク記録の保留）。依頼で足した側の機能で、未完成。

核（core.py）の状態の表の読み書きを使う。核はこのモジュールをimportしない。

    python scripts/orchestrate.py decision add --task T1234 --background ... --question ... --blocking ... --option ... --option ...
    python scripts/orchestrate.py decision answer D-001 A
    python scripts/orchestrate.py decision list [--all] [--no-records] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from orchestration.core import (
    PLAN_DOC,
    TASKS_DIR,
    Context,
    cat_files,
    hm,
    iso,
    load_board,
    minutes,
    now,
    parse_time,
    save_board,
)

#: タスク記録の保留の書き方（見出しに「保留」を含む節・「保留:」で始まる段落）。
HEADING_RE = re.compile(r"^(#+)\s")
HOLD_HEADING_RE = re.compile(r"^(#+)\s.*保留")
HOLD_ITEM_RE = re.compile(r"^(\d+\.\s|\*\*保留\s*\d)")
HOLD_LINE_RE = re.compile(r"^(?:[-*]\s+)?\**保留[:：]")
DECIDED_RE = re.compile(r"ユーザー決定")
OPEN_ENTRY_RE = re.compile(r"^- \[ \] \[(T\d+[a-z0-9-]*)\]\(")


def options_of(decision: dict) -> list[dict]:
    """選択肢を[{label, text}]へそろえる。手書きの「A …/B …」の1文字列も読む。"""
    raw = decision.get("options")
    if isinstance(raw, str):
        raw = re.split(r"\s*/\s*(?=[A-Z][ 　:：])", raw)
    out = []
    for n, item in enumerate(raw or []):
        if isinstance(item, dict):
            out.append(item)
            continue
        m = re.match(r"([A-Z])[ 　:：]\s*(.*)", str(item), re.DOTALL)
        out.append({"label": m.group(1), "text": m.group(2)} if m
                   else {"label": chr(ord("A") + n), "text": str(item)})
    return out


def split_hold_items(block: list[str]) -> list[str]:
    """保留の節を1件ずつへ分ける。番号付きの項目は字下げが続く間、「**保留N」の段落は次の項目まで。"""
    starts = [k for k, line in enumerate(block) if HOLD_ITEM_RE.match(line)]
    if not starts:
        text = "\n".join(block).strip()
        return [text] if text else []
    preamble = "\n".join(block[:starts[0]]).strip()
    items = []
    for n, s in enumerate(starts):
        seg = block[s:starts[n + 1] if n + 1 < len(starts) else len(block)]
        if re.match(r"^\d+\.\s", seg[0]):
            end = next((k for k in range(1, len(seg)) if seg[k] and not seg[k].startswith((" ", "\t"))), len(seg))
            seg = seg[:end]
        items.append(("\n".join(seg).strip(), preamble))
    return [f"{text}\n（節の前置き: {pre}）" if pre else text for text, pre in items]


def record_holds(text: str) -> list[str]:
    """タスク記録の保留（見出しに「保留」を含む節の各項目と、「保留:」で始まる段落）。"""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = HOLD_HEADING_RE.match(lines[i])
        if m:
            level = len(m.group(1))
            j = i + 1
            while j < len(lines) and not ((h := HEADING_RE.match(lines[j])) and len(h.group(1)) <= level):
                j += 1
            out += split_hold_items(lines[i + 1:j])
            i = j
        elif HOLD_LINE_RE.match(lines[i]):
            j = i + 1
            while j < len(lines) and lines[j].strip() and not HEADING_RE.match(lines[j]):
                j += 1
            out.append("\n".join(lines[i:j]).strip())
            i = j
        else:
            i += 1
    return [h for h in out if not DECIDED_RE.search(h.split("\n（節の前置き")[0])]


def collect_record_holds(repo: Path) -> list[tuple[str, str]]:
    """台帳の未完了タスクのうち、記録に未決の保留があるもの。(タスク, 1件の本文)。"""
    plan = cat_files(repo, [f"origin/master:{PLAN_DOC}"])[f"origin/master:{PLAN_DOC}"] or ""
    tasks = [m.group(1) for line in plan.splitlines() if (m := OPEN_ENTRY_RE.match(line))]
    blobs = cat_files(repo, [f"origin/master:{TASKS_DIR}/{t}.md" for t in tasks])
    return [(task, hold) for task in tasks
            for hold in record_holds(blobs[f"origin/master:{TASKS_DIR}/{task}.md"] or "")]


def cmd_decision(ctx: Context, args: argparse.Namespace) -> int:
    board = load_board(ctx)
    at = now()
    items: list[dict] = board.setdefault("decisions", [])
    if args.op == "add":
        if not 2 <= len(args.option) <= 4:
            raise SystemExit("選択肢は2〜4個（選択式の質問の上限）。推奨を先頭に書く")
        number = max((int(m.group(1)) for d in items if (m := re.match(r"D-(\d+)$", str(d.get("id", ""))))),
                     default=0) + 1
        item = {"id": f"D-{number:03d}", "task": args.task, "background": args.background,
                "question": args.question, "blocking": args.blocking,
                "options": [{"label": chr(ord("A") + n), "text": text} for n, text in enumerate(args.option)],
                "recommended": "A", "created": iso(at), "answer": None, "answered_at": None}
        items.append(item)
        save_board(ctx, board)
        print(f"{item['id']} を追加した")
        return 0
    if args.op == "answer":
        item = next((d for d in items if d.get("id") == args.id), None)
        if item is None:
            raise SystemExit(f"判断待ちに無い: {args.id}")
        labels = [o.get("label") for o in options_of(item)]
        if args.answer not in labels:
            print(f"注: {args.answer} は選択肢（{'・'.join(map(str, labels))}）に無いため、自由回答として記録する")
        item["answer"] = args.answer if not args.note else f"{args.answer}（{args.note}）"
        item["answered_at"] = iso(at)
        save_board(ctx, board)
        print(f"{args.id}: {item['answer']} を記録した。{item.get('task')} の記録への反映を司令塔のキューへ積む"
              f"（board todo push \"{item.get('task')}へ{args.id}の決定を反映\" --priority 5）")
        return 0

    open_items = [d for d in items if args.all or not d.get("answer")]
    if args.json:
        # 選択式の質問（AskUserQuestion）へそのまま写せる形。1回に4問まで。
        # 背景を知らない人がその1問だけで判断できるよう、背景を問いの前に置き、番号は参照として末尾へ。
        questions = [{
            "header": d["id"],
            "question": f"{d.get('background') or ''}\n{d.get('question')}（参照: {d.get('task')}）".strip(),
            "options": [{"label": o["label"] + ("（推奨）" if o["label"] == d.get("recommended")
                                                and "推奨" not in o["text"] else ""),
                         "description": o["text"]} for o in options_of(d)],
        } for d in open_items if not d.get("answer")]
        print(json.dumps([questions[i:i + 4] for i in range(0, len(questions), 4)], ensure_ascii=False, indent=1))
        return 0

    holds = [] if args.no_records else collect_record_holds(ctx.repo)
    print(f"判断待ち: 状態の表 {len(open_items)}件・タスク記録の保留 {len(holds)}件"
          f"（選択式の質問は1回に4問まで。記録の保留は decision add で形を整えてから出す）")
    for d in open_items:
        created = parse_time(d.get("created"))
        age = f"、{minutes(at - created) // 60}時間{minutes(at - created) % 60}分経過" if created else ""
        print(f"\n{d.get('id')}  作成{hm(created)}{age}")
        print(f"  背景: {d.get('background') or '（未記入。背景を知らない人が判断できない）'}")
        print(f"  問い: {d.get('question')}")
        for o in options_of(d):
            mark = "（推奨）" if o["label"] == d.get("recommended") and "推奨" not in o["text"] else ""
            print(f"  {o['label']}{mark}: {o['text']}")
        print(f"  止まっているもの: {d.get('blocking') or '-'}")
        if d.get("answer"):
            print(f"  回答: {d['answer']}（{hm(parse_time(d.get('answered_at')))}）")
        else:
            print(f"  回答の書き方: 「{d.get('id')} {d.get('recommended')}」")
        print(f"  出所: {d.get('task')}")
    for task, hold in holds:
        print(f"\n記録の保留  出所: {task}")
        for line in hold.splitlines():
            print(f"  | {line}")
    return 0



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py decision", description="ユーザーへの判断待ち")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=None)
    ops = parser.add_subparsers(dest="op", required=True)
    r = ops.add_parser("add")
    r.add_argument("--task", required=True, help="参照として末尾に添えるタスク番号")
    r.add_argument("--background", required=True,
                   help="何の画面・機能の話か（利用者から見える言葉で）・いまどうなっているか・なぜ決める必要があるか")
    r.add_argument("--question", required=True, help="1行の問い")
    r.add_argument("--blocking", required=True, help="止まっているもの")
    r.add_argument("--option", action="append", required=True,
                   help="選択肢（2〜4個。推奨を先頭に、理由と利用者に何が起きるかを添えて）。繰り返し指定する")
    r = ops.add_parser("answer")
    r.add_argument("id")
    r.add_argument("answer")
    r.add_argument("--note")
    r = ops.add_parser("list")
    r.add_argument("--all", action="store_true", help="回答済みも出す")
    r.add_argument("--no-records", action="store_true", help="タスク記録の保留を集めない")
    r.add_argument("--json", action="store_true", help="状態の表の未回答を、選択式の質問へ写す形で（4問ずつ）")

    args = parser.parse_args(argv)
    return cmd_decision(Context(Path(args.repo), args.dir), args)
