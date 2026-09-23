"""ユーザーへの確認待ち（判断・実施・改善の承認）。依頼で足した側の機能。

確認待ちの正本は、各タスクの記録（origin/masterの`docs/records/tasks/Txxx.md`）に決まった書き方で
置いたお願い（規約`docs/conventions/orchestration.md`「ユーザーへのお願いは記録に置く」節）。状態の表には
写さない——表と記録の両方に持つと、片方だけが直され、もう片方が古いまま正しそうに残る。ここは
origin/masterの全タスクの記録（台帳に行の無い、閉じたタスクも含む）から、3種類の待ちを集めるだけ。
核はこのモジュールをimportしない。

    python scripts/orchestrate.py asks [Txxx...]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from orchestration.core import (
    PLAN_DOC,
    TASK_DOC_RE,
    TASKS_DIR,
    Context,
    cat_files,
    git_out,
    ledger_ids,
)

HEADING_RE = re.compile(r"^(#+)\s")
#: 保留の宣言の書き出し: 「保留」の語のあとが行末・括弧・コロン・番号のもの（`保留`・`保留（ユーザー判断）`・
#: `保留: …`・`保留1: …`）。「保留した場合の影響」「保留し続けると」「保留理由」のように「保留」が別の語の
#: 一部であるものは、影響や経緯を述べる文で問いの宣言ではないため含めない。
HOLD_HEAD = r"保留(?:$|[（(:：]|\s*\d)"
#: 保留を宣言する見出し（2段目以下。1段目はタスクの題名）。見出しの文が保留の宣言で始まるもの。
HOLD_HEADING_RE = re.compile(r"^#{2,}\s+" + HOLD_HEAD)
#: 保留を宣言する段落（見出しでない行）: `**保留（ユーザー判断）**:`・`**保留1:`・`保留:`等。
HOLD_PARAGRAPH_RE = re.compile(r"^(?:[-*]\s+)?(?:\*\*" + HOLD_HEAD + r"|保留[:：])")
#: 決定は、保留の単位の中に、行頭が`**ユーザー決定（日付`の段落か、1段下の見出し`ユーザー決定（日付`として
#: 書く。行の途中・単位の外（同じ段の別の見出しの節を含む）に書いたものは拾わない（位置から推測しない）。
DECISION_RE = re.compile(r"^(?:(?:[-*]\s+)?\*\*|#{2,}\s+)ユーザー決定（")
#: 実施と改善の承認は見出しだけで宣言する（2段目以下）。済・承認・見送りへ変えた見出しは合わない。
OPERATION_RE = re.compile(r"^#{2,}\s+ユーザー操作（待ち）")
IMPROVEMENT_RE = re.compile(r"^#{2,}\s+改善提案（承認待ち）")

KINDS = (
    ("判断", "保留の単位の中へ、行頭が「**ユーザー決定（日付）**:」の段落を書くと外れる"),
    ("実施", "済んだら見出しを「## ユーザー操作（済 日付）: …」へ変えると外れる"),
    ("改善の承認", "見出しを「## 改善提案（承認 日付）: …」か「（見送り 日付）」へ変えると外れる"),
)
#: 一覧に出す1件の行数の上限（節全体が単位なので、表や測定値まで含むことがある）。
SHOWN_LINES = 12


def section_end(lines: list[str], i: int) -> int:
    """見出しの行iから始まる節の終わり（次の同じか上の見出しの行、無ければ末尾）。"""
    level = len(HEADING_RE.match(lines[i]).group(1))
    j = i + 1
    while j < len(lines) and not ((h := HEADING_RE.match(lines[j])) and len(h.group(1)) <= level):
        j += 1
    return j


def hold_units(text: str) -> list[list[str]]:
    """保留の単位（行の並び）を順に。保留を宣言する見出しの節（次の同じか上の見出しまで）か、
    保留を宣言する段落（次の見出しか次の保留の段落まで）。中の番号付きの項目は、その1件の選択肢。"""
    lines = text.splitlines()
    units: list[list[str]] = []
    i = 0
    while i < len(lines):
        if HOLD_HEADING_RE.match(lines[i]):
            j = section_end(lines, i)
        elif not HEADING_RE.match(lines[i]) and HOLD_PARAGRAPH_RE.match(lines[i]):
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


def headed_sections(text: str, heading_re: re.Pattern[str]) -> list[str]:
    """見出しがheading_reに合う節（次の同じか上の見出しまで）を順に。"""
    lines = text.splitlines()
    return ["\n".join(lines[i:section_end(lines, i)]).strip()
            for i in range(len(lines)) if heading_re.match(lines[i])]


def record_asks(text: str) -> dict[str, list[str]]:
    """タスク記録1件の確認待ちを種類ごとに。"""
    return {"判断": record_holds(text),
            "実施": headed_sections(text, OPERATION_RE),
            "改善の承認": headed_sections(text, IMPROVEMENT_RE)}


def collect_asks(repo: Path, tasks: list[str] | None = None) -> tuple[dict[str, dict[str, list[str]]], set[str]]:
    """origin/masterの全タスク記録（tasksで絞れる）の確認待ち {種類: {タスク: [1件の本文]}} と、台帳の未完了のタスク。"""
    listing = git_out(repo, "ls-tree", "--name-only", "origin/master", f"{TASKS_DIR}/") or ""
    ids = sorted((m.group(1) for path in listing.splitlines() if (m := TASK_DOC_RE.match(path))),
                 key=lambda t: (int(re.match(r"T(\d+)", t).group(1)), t))
    if tasks:
        ids = [t for t in ids if t in tasks]
    specs = [f"origin/master:{TASKS_DIR}/{t}.md" for t in ids] + [f"origin/master:{PLAN_DOC}"]
    blobs = cat_files(repo, specs)
    found: dict[str, dict[str, list[str]]] = {kind: {} for kind, _ in KINDS}
    for task in ids:
        for kind, items in record_asks(blobs[f"origin/master:{TASKS_DIR}/{task}.md"] or "").items():
            if items:
                found[kind][task] = items
    return found, ledger_ids(blobs[f"origin/master:{PLAN_DOC}"])


def cmd_asks(ctx: Context, args: argparse.Namespace) -> int:
    found, open_tasks = collect_asks(ctx.repo, args.tasks)
    total = sum(len(items) for by_task in found.values() for items in by_task.values())
    print(f"確認待ち {total}件（origin/masterのタスク記録から。"
          + "・".join(f"{kind} {sum(len(v) for v in found[kind].values())}件" for kind, _ in KINDS) + "）")
    for kind, how in KINDS:
        by_task = found[kind]
        print(f"\n== {kind} {sum(len(v) for v in by_task.values())}件（{how}）")
        for task, items in by_task.items():
            closed = "" if task in open_tasks else "（閉じたタスク: 台帳に行が無い）"
            print(f"\n出所: {task}{closed} {len(items)}件")
            for n, item in enumerate(items, 1):
                lines = item.splitlines()
                if len(items) > 1:
                    print(f"  [{n}]")
                for line in lines[:SHOWN_LINES]:
                    print(f"  | {line}")
                if len(lines) > SHOWN_LINES:
                    print(f"  | …（ほか{len(lines) - SHOWN_LINES}行。全文は{task}.md）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py asks",
                                     description="ユーザーへの確認待ち（判断・実施・改善の承認）をタスク記録から集める")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=None)
    parser.add_argument("tasks", nargs="*", help="出所を絞るタスク番号")
    args = parser.parse_args(argv)
    return cmd_asks(Context(Path(args.repo), args.dir), args)
