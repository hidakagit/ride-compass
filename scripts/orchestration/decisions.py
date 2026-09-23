"""ユーザーの判断待ち。依頼で足した側の機能。

判断の問いと回答の正本は、各タスクの記録（origin/masterの`docs/records/tasks/Txxx.md`）の保留節と、
そこへ書く「ユーザー決定」。状態の表には写さない——表と記録の両方に持つと、片方だけが直され、
もう片方が古いまま正しそうに残る。ここは台帳の未完了タスクの記録から、未決の保留を集めるだけ。
核はこのモジュールをimportしない。

    python scripts/orchestrate.py decision list [Txxx...]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from orchestration.core import PLAN_DOC, TASKS_DIR, Context, cat_files

#: タスク記録の保留の書き方（見出しに「保留」を含む節・「保留:」で始まる段落）。
HEADING_RE = re.compile(r"^(#+)\s")
HOLD_HEADING_RE = re.compile(r"^(#+)\s.*保留")
HOLD_ITEM_RE = re.compile(r"^(\d+\.\s|\*\*保留\s*\d)")
HOLD_LINE_RE = re.compile(r"^(?:[-*]\s+)?\**保留[:：]")
DECIDED_RE = re.compile(r"ユーザー決定")
OPEN_ENTRY_RE = re.compile(r"^- \[ \] \[(T\d+[a-z0-9-]*)\]\(")


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



def cmd_list(ctx: Context, args: argparse.Namespace) -> int:
    holds = [(t, h) for t, h in collect_record_holds(ctx.repo) if not args.tasks or t in args.tasks]
    print(f"判断待ち: タスク記録の未決の保留 {len(holds)}件（回答は各タスクの記録の保留へ「ユーザー決定（日付）」として書く）")
    for task, hold in holds:
        print(f"\n出所: {task}")
        for line in hold.splitlines():
            print(f"  | {line}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py decision", description="ユーザーへの判断待ち")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=None)
    ops = parser.add_subparsers(dest="op", required=True)
    r = ops.add_parser("list", help="台帳の未完了タスクの記録から、未決の保留を集める")
    r.add_argument("tasks", nargs="*", help="出所を絞るタスク番号")
    args = parser.parse_args(argv)
    return cmd_list(Context(Path(args.repo), args.dir), args)
