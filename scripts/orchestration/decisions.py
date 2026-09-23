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

#: タスク記録の保留の書き方（規約「ユーザーの判断待ち」節）。保留の単位は、2段目以下の見出しに「保留」を
#: 含む節（次の同じか上の見出しまで）か、保留を宣言する段落（次の見出しか次の保留の段落まで）。
#: 中の番号付きの項目は、その1件の保留の選択肢として扱う。
HEADING_RE = re.compile(r"^(#+)\s")
#: 保留を宣言する段落の書き出し: `**保留（ユーザー判断）**:`・`**保留1:`・`保留:`等。「**保留し続けた場合に
#: 何が起きるか**」（タスクエントリの書き方が求める文）のように、保留が続く語の一部であるものは含めない。
HOLD_PARAGRAPH_RE = re.compile(r"^(?:[-*]\s+)?(?:\*\*保留(?:[（(:：]|\s*\d)|保留[:：])")
#: 決定は、保留の単位の中に、行頭が`**ユーザー決定（日付`の段落として書く。位置から推測して拾わない。
DECISION_RE = re.compile(r"^(?:[-*]\s+)?\*\*ユーザー決定（")
OPEN_ENTRY_RE = re.compile(r"^- \[ \] \[(T\d+[a-z0-9-]*)\]\(")
#: 一覧に出す1件の行数の上限（節全体が単位なので、表や測定値まで含むことがある）。
SHOWN_LINES = 12


def hold_units(text: str) -> list[list[str]]:
    """保留の単位（行の並び）を順に。"""
    lines = text.splitlines()
    units: list[list[str]] = []
    i = 0
    while i < len(lines):
        heading = HEADING_RE.match(lines[i])
        # 1段目の見出しはタスクの題名で、題名に「保留」の語があっても保留の宣言ではない。
        if heading and len(heading.group(1)) >= 2 and "保留" in lines[i]:
            level = len(heading.group(1))
            j = i + 1
            while j < len(lines) and not ((h := HEADING_RE.match(lines[j])) and len(h.group(1)) <= level):
                j += 1
        elif not heading and HOLD_PARAGRAPH_RE.match(lines[i]):
            j = i + 1
            while j < len(lines) and not HEADING_RE.match(lines[j]) and not HOLD_PARAGRAPH_RE.match(lines[j]):
                j += 1
        else:
            i += 1
            continue
        units.append(lines[i:j])
        i = j
    return units


def record_holds(text: str) -> list[str]:
    """タスク記録の未決の保留（保留の単位のうち、決定の段落を持たないもの）。"""
    return ["\n".join(unit).strip() for unit in hold_units(text)
            if not any(DECISION_RE.match(line) for line in unit)]


def collect_record_holds(repo: Path) -> list[tuple[str, str]]:
    """台帳の未完了タスクのうち、記録に未決の保留があるもの。(タスク, 1件の本文)。"""
    plan = cat_files(repo, [f"origin/master:{PLAN_DOC}"])[f"origin/master:{PLAN_DOC}"] or ""
    tasks = [m.group(1) for line in plan.splitlines() if (m := OPEN_ENTRY_RE.match(line))]
    blobs = cat_files(repo, [f"origin/master:{TASKS_DIR}/{t}.md" for t in tasks])
    return [(task, hold) for task in tasks
            for hold in record_holds(blobs[f"origin/master:{TASKS_DIR}/{task}.md"] or "")]



def cmd_list(ctx: Context, args: argparse.Namespace) -> int:
    holds = [(t, h) for t, h in collect_record_holds(ctx.repo) if not args.tasks or t in args.tasks]
    print(f"判断待ち: タスク記録の未決の保留 {len(holds)}件（回答は各保留の中へ、行頭が"
          f"「**ユーザー決定（日付）**:」の段落として書く）")
    for task, hold in holds:
        print(f"\n出所: {task}")
        lines = hold.splitlines()
        for line in lines[:SHOWN_LINES]:
            print(f"  | {line}")
        if len(lines) > SHOWN_LINES:
            print(f"  | …（ほか{len(lines) - SHOWN_LINES}行。全文は{task}.md）")
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
