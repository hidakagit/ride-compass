#!/usr/bin/env python3
"""周期レビュー（.claude/commands/review/）の機械的チェックをまとめたスクリプト。

Agent（人力）で行っていた「grep一発で済む」確認をここへ寄せ、レビューの負荷を下げる。
標準ライブラリのみで動く（backend/.venvでもシステムのpythonでもよい）。

サブコマンド:
  docs     docs/modules の死んだ参照・新規ファイルの記載漏れ・記載粒度違反、
           backend/app・frontend/src のソースコードコメントの経緯記述（docs/comments.md、
           --staged/--sinceでは追加行のみ違反として数える。フルスキャンではT567完了までの
           既存分が大量にあるため参考件数のみで違反に数えない）、
           improvement-plan.md の [x]/[ ] と docs/tasks/Txxx.md「状態:」行の照合、
           history/・docs/tasks/ への死んだリンク（consistency.md「設計 ↔ 実装」節の機械的部分）
  size     規模ウォッチ（complexity.md）: 実装ファイル行数の上位と前回比・閾値発火
  metrics  定量メトリクス（metrics.md）: cloc・churn・テスト件数・静的検査・依存関係
  trigger  周期レビューのトリガー判定（README.md「定期的なレビュー」節）

使い方の例:
  python scripts/review_checks.py docs                 # 全件監査（ソースコード経緯コメントは参考件数のみ）
  python scripts/review_checks.py docs --since cab1441 # 記載漏れ・ソースコード経緯コメントをこのref以降の追加分に限定（CI向け）
  python scripts/review_checks.py docs --staged        # pre-commit用（ステージ済み変更に関係する項目のみ）
  python scripts/review_checks.py size                 # 現在値と前回比を表示
  python scripts/review_checks.py size --update        # 表示したうえで前回値ファイルを今回値へ更新
  python scripts/review_checks.py metrics --full       # テスト件数・tsc/eslint・npm auditも計測（数分）
  python scripts/review_checks.py trigger

終了コード: docs は違反があれば1、それ以外は常に0（計測・判定結果の表示のみ）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_DIR = REPO_ROOT / ".claude" / "commands" / "review"
HISTORY_DIR = REVIEW_DIR / "history"
MODULES_DIR = REPO_ROOT / "docs" / "modules"
TASKS_DIR = REPO_ROOT / "docs" / "tasks"
IMPROVEMENT_PLAN = REPO_ROOT / "docs" / "improvement-plan.md"
SIZE_BASELINE = HISTORY_DIR / "size_watch.json"

# --- 共通 -------------------------------------------------------------------

IMPL_INCLUDE_PREFIXES = ("backend/app/", "frontend/src/")
IMPL_EXCLUDE_RE = re.compile(
    r"(\.test\.|\.spec\.|\.bench\.|/types/generated/|\.module\.css$|\.css$|\.d\.ts$"
    r"|/__init__\.py$|/__pycache__/|\.json$|\.yml$|\.yaml$|\.md$|\.snap$)"
)
# 名前だけでは特定できないファイル名は「親ディレクトリ/名前」で照合する
GENERIC_BASENAMES = {
    "page.tsx", "layout.tsx", "route.ts", "index.ts", "index.tsx", "types.ts",
    "utils.ts", "constants.ts", "config.py", "main.py", "models.py", "errors.py",
}
# docs/modules/README.md「記載粒度」節の禁止パターン。
# 唯一の定義元（scripts/pre-commit-docs-modules-history.shは2026-09-03のT561でこの関数を
# 呼ぶだけの薄いラッパへ統合し、shell側に別定義のPATTERNを持たない）。
NARRATIVE_PATTERN = re.compile(
    r"以前は|従来は|旧「|旧『|旧T[0-9]|改善計画T[0-9]+で|T[0-9]{3,4}で|実機報告20|実機フィードバック"
    r"|実機確認|実機指摘|実測で|判明した|発覚した|指摘を受け|フィードバックを受け|ユーザー指摘20"
    r"|ユーザー要望20|ユーザー判断|方式ではなく|へ変更した|に変更した|を導入した"
)
# docs/comments.md「コメント方針」節が禁止するソースコード内の経緯コメント検出用。
# docs/modules向けのNARRATIVE_PATTERNをそのまま流用する（定義元を分けない）。
# コメント行以外（実装コード・文字列リテラル）を誤検出しないよう、行のコメント部分だけを
# 抽出してから照合する（comment_only参照）。
SOURCE_COMMENT_PATHSPECS = ("backend/app/*.py", "frontend/src/*.ts", "frontend/src/*.tsx")


def comment_only(line: str, path: str) -> str:
    """1行のうちコメント部分だけを返す（非コメント行・コメントなしは空文字）。

    diffの追加行1行ずつを独立に見るため、複数行にまたがるブロックコメントの内部行
    （`*`始まりの継続行等）は「行頭が*・/*・*/」という単純な形で判定する——完全な
    構文解析はしない（review_checks.py全体の「grep一発規模の安価なチェック」という
    設計方針に合わせる）。
    """
    stripped = line.strip()
    if path.endswith(".py"):
        idx = line.find("#")
        return line[idx:] if idx != -1 else ""
    # ts/tsx
    if stripped.startswith(("/**", "/*", "*/", "*")):
        return line
    idx = line.find("//")
    return line[idx:] if idx != -1 else ""


def find_source_narrative_violations(source_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    out = []
    for path, lines in source_lines.items():
        for lineno, line in lines:
            text = comment_only(line, path)
            if not text:
                continue
            m = NARRATIVE_PATTERN.search(text)
            if m:
                out.append(f"{path}:{lineno}: 「{m.group(0)}」 {text.strip()[:80]}")
    return out
FILE_TOKEN_RE = re.compile(
    r"`([A-Za-z0-9_./@\-]+\.(?:py|ts|tsx|css|json|yml|yaml|sql|sh|md|js|mjs|toml|txt))`"
)
TASK_LINK_RE = re.compile(r"\[T(\d{3,4})\]\(")
TASK_FILE_MENTION_RE = re.compile(r"\bT(\d{3,4})\.md\b")
HISTORY_REF_RE = re.compile(r"history/(\d{4}-\d{2}-\d{2}_[A-Za-z0-9_\-]+\.md)")
PLAN_LINE_RE = re.compile(r"^- \[( |x)\] \[T(\d{3,4})\]\(tasks/T\d{3,4}\.md\)")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, timeout: int = 600) -> str:
    proc = subprocess.run(
        cmd, cwd=str(cwd or REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, shell=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"コマンド失敗: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout


def git(*args: str, check: bool = True) -> str:
    return run(["git", *args], check=check)


def git_files() -> list[str]:
    return [line for line in git("ls-files").splitlines() if line]


def is_impl_file(path: str) -> bool:
    return (
        path.startswith(IMPL_INCLUDE_PREFIXES)
        and path.endswith((".py", ".ts", ".tsx"))
        and not IMPL_EXCLUDE_RE.search(path)
    )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def count_lines(path: Path) -> int:
    with path.open("rb") as f:
        return sum(1 for _ in f)


def module_docs() -> list[Path]:
    return sorted(p for p in MODULES_DIR.rglob("*.md") if p.name != "README.md")


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


# --- docs -------------------------------------------------------------------

def find_dead_file_refs(doc_lines: dict[str, list[tuple[int, str]]], files: list[str]) -> list[str]:
    """docs/modulesのバッククォート付きファイル名のうち、リポジトリに実在しないもの。"""
    file_set = set(files)
    by_basename: dict[str, set[str]] = defaultdict(set)
    for f in files:
        by_basename[f.rsplit("/", 1)[-1]].add(f)
    out = []
    for doc, lines in doc_lines.items():
        for lineno, line in lines:
            for token in FILE_TOKEN_RE.findall(line):
                if "*" in token or token.startswith(("http", "@")):
                    continue
                name = token.rsplit("/", 1)[-1]
                if "/" in token:
                    exists = token in file_set or any(f.endswith("/" + token) for f in by_basename.get(name, ()))
                else:
                    exists = name in by_basename
                if not exists:
                    out.append(f"{doc}:{lineno}: `{token}` が実在しない")
    return out


def find_narrative_violations(doc_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    out = []
    for doc, lines in doc_lines.items():
        for lineno, line in lines:
            m = NARRATIVE_PATTERN.search(line)
            if m:
                out.append(f"{doc}:{lineno}: 「{m.group(0)}」 {line.strip()[:80]}")
    return out


def count_task_links(doc_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    out = []
    for doc, lines in doc_lines.items():
        for lineno, line in lines:
            for n in TASK_LINK_RE.findall(line):
                out.append(f"{doc}:{lineno}: [T{n}]リンク")
    return out


def find_undocumented_files(candidates: list[str], modules_text: str, all_files: list[str]) -> list[str]:
    """実装ファイルのうち、docs/modules/*.md のどこにもファイル名が出現しないもの。

    汎用的な名前（page.tsx・route.ts・config.py 等）はリポジトリ内で一意なら名前だけで、
    複数あれば「親ディレクトリ/名前」で照合する。
    """
    basename_count: dict[str, int] = defaultdict(int)
    for f in all_files:
        if is_impl_file(f):
            basename_count[f.rsplit("/", 1)[-1]] += 1
    out = []
    for path in sorted(candidates):
        if not is_impl_file(path):
            continue
        name = path.rsplit("/", 1)[-1]
        needles = [name]
        if name in GENERIC_BASENAMES and basename_count.get(name, 0) > 1:
            parent = path.rsplit("/", 2)[-2] if path.count("/") >= 2 else ""
            needles = [f"{parent}/{name}"]
        if not any(n in modules_text for n in needles):
            out.append(f"{path}: 「{needles[0]}」が docs/modules/*.md のどこにも出現しない")
    return out


# 「見送り」「保留」はトリガー待ちで improvement-plan 側も [ ] のままにする運用（例: T422）のため open 扱い
OPEN_STATUS_WORDS = ("未着手", "着手中", "進行中", "保留", "見送り", "調査中", "中断", "作業中")
CLOSED_STATUS_WORDS = ("完了", "撤回", "取り下げ", "却下", "廃止")
# 「存在しないこと自体」を記録している参照（T356: 2026-08-26のcomplexityレビュー結果が保存されなかった件）
KNOWN_MISSING_HISTORY = {"2026-08-26_complexity.md"}


def task_status_kind(task_path: Path) -> str | None:
    """docs/tasks/Txxx.md の「状態:」行を done / open / None（行なし）に分類する。"""
    for line in read_text(task_path).splitlines():
        if line.startswith("状態:"):
            body = line[len("状態:"):].strip()
            head = re.split(r"[（(]", body, maxsplit=1)[0]
            if any(w in head for w in OPEN_STATUS_WORDS):
                return "open"
            if any(w in body for w in CLOSED_STATUS_WORDS) and "未完了" not in head:
                return "done"
            return "open"
    return None


def check_plan_vs_tasks() -> tuple[list[str], list[str]]:
    violations, infos = [], []
    for lineno, line in enumerate(read_text(IMPROVEMENT_PLAN).splitlines(), 1):
        m = PLAN_LINE_RE.match(line)
        if not m:
            continue
        checked, num = m.group(1) == "x", m.group(2)
        task_path = TASKS_DIR / f"T{num}.md"
        if not task_path.exists():
            violations.append(f"docs/improvement-plan.md:{lineno}: docs/tasks/T{num}.md が存在しない")
            continue
        kind = task_status_kind(task_path)
        if kind is None:
            infos.append(f"docs/tasks/T{num}.md: 「状態:」行なし（照合不能）")
        elif checked and kind == "open":
            violations.append(f"docs/improvement-plan.md:{lineno}: T{num} は [x] だが docs/tasks/T{num}.md の「状態:」行は未完了のまま")
        elif not checked and kind == "done":
            violations.append(f"docs/improvement-plan.md:{lineno}: T{num} は [ ] だが docs/tasks/T{num}.md の「状態:」行は完了")
    return violations, infos


def check_dead_doc_links(md_files: list[str]) -> list[str]:
    out = []
    existing_history = {p.name for p in HISTORY_DIR.glob("*.md")}
    existing_tasks = {p.name for p in TASKS_DIR.glob("*.md")}
    for f in md_files:
        p = REPO_ROOT / f
        # history/ 配下は当時の記録（書き換えない）のため対象外
        if not p.exists() or f.startswith(".claude/commands/review/history/"):
            continue
        for lineno, line in enumerate(read_text(p).splitlines(), 1):
            for name in HISTORY_REF_RE.findall(line):
                if name not in existing_history and name not in KNOWN_MISSING_HISTORY:
                    out.append(f"{f}:{lineno}: history/{name} が存在しない")
            for n in TASK_FILE_MENTION_RE.findall(line):
                if f"T{n}.md" not in existing_tasks:
                    out.append(f"{f}:{lineno}: docs/tasks/T{n}.md が存在しない")
    return out


def diff_added_lines(pathspec: str, base_ref: str | None = None) -> dict[str, list[tuple[int, str]]]:
    """追加行を {ファイル: [(行番号, 行)]} で返す。

    base_ref省略時は `git diff --cached`（pre-commit用、ステージ済み変更）。
    base_ref指定時は `git diff base_ref..HEAD`（CI用、そのref以降にHEADへ積まれた変更）。
    """
    diff_args = ["diff", "--cached", "-U0"] if base_ref is None else ["diff", f"{base_ref}..HEAD", "-U0"]
    out: dict[str, list[tuple[int, str]]] = defaultdict(list)
    current, lineno = None, 0
    for line in git(*diff_args, "--", pathspec).splitlines():
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/")
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++") and current:
            out[current].append((lineno, line[1:]))
            lineno += 1
    return out


def gather_added_source_lines(base_ref: str | None) -> dict[str, list[tuple[int, str]]]:
    """SOURCE_COMMENT_PATHSPECS全体の追加行を集め、is_impl_file（テスト等を除外）で絞る。"""
    out: dict[str, list[tuple[int, str]]] = {}
    for spec in SOURCE_COMMENT_PATHSPECS:
        for path, lines in diff_added_lines(spec, base_ref).items():
            if is_impl_file(path):
                out[path] = lines
    return out


def cmd_docs(args: argparse.Namespace) -> int:
    files = git_files()
    all_docs = module_docs()
    modules_text = "\n".join(read_text(p) for p in all_docs)
    sections: list[tuple[str, list[str], bool]] = []  # (見出し, 行, 違反として数えるか)

    if args.staged:
        staged = [l for l in git("diff", "--cached", "--name-only").splitlines() if l]
        doc_lines = diff_added_lines("docs/modules/*.md")
        doc_lines = {k: v for k, v in doc_lines.items() if not k.endswith("README.md")}
        added = [l for l in git("diff", "--cached", "--name-only", "--diff-filter=A").splitlines() if l]
        sections.append(("docs/modules の死んだ参照（ステージ済み追加行）", find_dead_file_refs(doc_lines, files + added), True))
        sections.append(("docs/modules の記載粒度違反（ステージ済み追加行）", find_narrative_violations(doc_lines), True))
        source_lines = gather_added_source_lines(None)
        sections.append(("ソースコードの経緯コメント（ステージ済み追加行、docs/comments.md参照）",
                         find_source_narrative_violations(source_lines), True))
        sections.append(("新規実装ファイルの docs/modules 記載漏れ（ステージ済み新規ファイル）",
                         find_undocumented_files(added, modules_text, files + added), True))
        if any(s == "docs/improvement-plan.md" or s.startswith("docs/tasks/") for s in staged):
            v, _ = check_plan_vs_tasks()
            sections.append(("improvement-plan.md [x]/[ ] と docs/tasks「状態:」の不一致", v, True))
        md_staged = [s for s in staged if s.endswith(".md")]
        sections.append(("history/・docs/tasks への死んだリンク（ステージ済み.md）", check_dead_doc_links(md_staged), True))
    else:
        doc_lines = {rel(p): list(enumerate(read_text(p).splitlines(), 1)) for p in all_docs}
        sections.append(("docs/modules の死んだ参照（全件）", find_dead_file_refs(doc_lines, files), True))
        sections.append(("docs/modules の記載粒度違反（全件）", find_narrative_violations(doc_lines), True))
        sections.append(("docs/modules の Txxx リンク（参考、README「記載粒度」節は1リンクまで許可）",
                         count_task_links(doc_lines), False))
        if args.since:
            added = [l for l in git("diff", "--diff-filter=A", "--name-only", f"{args.since}..HEAD").splitlines() if l]
            title = f"新規実装ファイルの docs/modules 記載漏れ（{args.since} 以降の新規ファイル）"
            # ソースコードの経緯コメントはT567（既存分の一掃）完了までフルスキャンだと大量に
            # 残るため、--sinceで新規追加分だけに絞れる場合のみ違反件数（exit code）に含める
            # （CI向け。undocumented-filesの--sinceスコープ限定と同じ考え方）。
            source_title = f"ソースコードの経緯コメント（{args.since} 以降の追加行、docs/comments.md参照）"
            sections.append((source_title, find_source_narrative_violations(gather_added_source_lines(args.since)), True))
        else:
            added = files
            title = "実装ファイルの docs/modules 記載漏れ（全件）"
            all_source_lines = {
                rel(p): list(enumerate(read_text(p).splitlines(), 1))
                for p in (REPO_ROOT / f for f in files if is_impl_file(f))
                if p.exists()
            }
            sections.append(("ソースコードの経緯コメント（参考、全件。新規分の強制は--staged/--since参照）",
                             find_source_narrative_violations(all_source_lines), False))
        sections.append((title, find_undocumented_files(added, modules_text, files), True))
        v, infos = check_plan_vs_tasks()
        sections.append(("improvement-plan.md [x]/[ ] と docs/tasks「状態:」の不一致", v, True))
        sections.append(("docs/tasks の「状態:」行なし（参考）", infos, False))
        md_files = [f for f in files if f.endswith(".md") and (f.startswith((".claude/", "docs/")) or f == "CLAUDE.md")]
        sections.append(("history/・docs/tasks への死んだリンク（.claude・docs 全件）", check_dead_doc_links(md_files), True))

    total = 0
    for title, lines, counts in sections:
        mark = f"{len(lines)}件" if lines else "0件"
        print(f"## {title}: {mark}")
        for l in lines:
            print(f"  - {l}")
        if counts:
            total += len(lines)
    print()
    if total:
        print(f"違反 {total}件（docs/modules/README.md「記載粒度」節・consistency.md「設計 ↔ 実装」節を参照して是正）")
        return 1
    print("違反なし")
    return 0


# --- size -------------------------------------------------------------------

def cmd_size(args: argparse.Namespace) -> int:
    files = git_files()
    counts = {f: count_lines(REPO_ROOT / f) for f in files if is_impl_file(f) and (REPO_ROOT / f).exists()}
    arch = "docs/architecture.md"
    if (REPO_ROOT / arch).exists():
        counts[arch] = count_lines(REPO_ROOT / arch)
    baseline = json.loads(read_text(SIZE_BASELINE)) if SIZE_BASELINE.exists() else {}
    prev: dict[str, int] = baseline.get("files", {})
    thresholds: dict[str, int] = baseline.get("thresholds", {})
    top_n = args.top
    groups = {
        "backend": sorted((f for f in counts if f.startswith("backend/")), key=lambda f: -counts[f])[:top_n],
        "frontend": sorted((f for f in counts if f.startswith("frontend/")), key=lambda f: -counts[f])[:top_n],
        "docs": [arch] if arch in counts else [],
    }
    watched = sorted(set(sum(groups.values(), [])) | set(thresholds) | set(prev), key=lambda f: -counts.get(f, 0))
    prev_top = set(baseline.get("top", []))
    cur_top = set(sum(groups.values(), []))

    print(f"## 規模ウォッチ表（対象 {git('rev-parse', '--short', 'HEAD').strip()}、"
          f"前回 {baseline.get('commit', '記録なし')} / {baseline.get('date', '-')}）")
    print("| ファイル | 今回 | 前回 | 増分 | 閾値 | 発火 |")
    print("|---|---:|---:|---:|---:|---|")
    fired = []
    for f in watched:
        cur = counts.get(f)
        if cur is None:
            print(f"| {f} | 削除済み | {prev.get(f, '-')} | - | - | - |")
            continue
        p = prev.get(f)
        delta = f"{cur - p:+d}" if p is not None else "新規"
        reasons = []
        if p is not None and p > 0 and (cur - p) / p >= 0.15:
            reasons.append(f"+{(cur - p) / p * 100:.0f}%")
        if p is not None and p < 1000 <= cur:
            reasons.append("1,000行超過")
        if f in cur_top and f not in prev_top and prev_top:
            reasons.append("上位に新規登場")
        th = thresholds.get(f)
        if th and cur >= th:
            reasons.append(f"Keep List閾値{th:,}超過")
        if reasons:
            fired.append(f)
        print(f"| {f} | {cur:,} | {p if p is not None else '-'} | {delta} | {th if th else '-'} | {'・'.join(reasons)} |")
    print()
    print(f"発火 {len(fired)}件: " + (", ".join(fired) if fired else "なし")
          + "（発火したファイルは complexity.md「規模ウォッチ」節に従い KEEP/分割/閾値付きKEEP へ分類する）")

    if args.update:
        new = {
            "date": dt.date.today().isoformat(),
            "commit": git("rev-parse", "--short", "HEAD").strip(),
            "top": sorted(cur_top),
            "files": {f: counts[f] for f in watched if f in counts},
            "thresholds": thresholds,
        }
        SIZE_BASELINE.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"前回値ファイルを更新: {rel(SIZE_BASELINE)}")
    return 0


# --- metrics ----------------------------------------------------------------

def venv_python() -> str | None:
    for cand in (REPO_ROOT / "backend/.venv/Scripts/python.exe", REPO_ROOT / "backend/.venv/bin/python"):
        if cand.exists():
            return str(cand)
    return None


def npx() -> str | None:
    return shutil.which("npx.cmd") or shutil.which("npx")


def latest_history_date(kind: str | None = None) -> dt.date | None:
    dates = []
    for p in HISTORY_DIR.glob("*.md"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})_([A-Za-z0-9\-]+)\.md$", p.name)
        if m and (kind is None or m.group(2) == kind):
            dates.append(dt.date.fromisoformat(m.group(1)))
    return max(dates) if dates else None


def cmd_metrics(args: argparse.Namespace) -> int:
    since = args.since or (latest_history_date("metrics") or latest_history_date())
    print(f"# 定量メトリクス（{dt.date.today().isoformat()}、対象 {git('rev-parse', '--short', 'HEAD').strip()}、"
          f"churn起点 {since}）\n")

    # 1. 規模
    print("## 1. 規模")
    impl = {f: count_lines(REPO_ROOT / f) for f in git_files() if is_impl_file(f) and (REPO_ROOT / f).exists()}
    tests = {
        f: count_lines(REPO_ROOT / f) for f in git_files()
        if (REPO_ROOT / f).exists() and (
            f.startswith("backend/tests/") and f.endswith(".py")
            or (f.startswith(("frontend/src/", "frontend/e2e/")) and re.search(r"\.(test|spec)\.tsx?$", f))
        )
    }
    b_impl = sum(v for f, v in impl.items() if f.startswith("backend/"))
    f_impl = sum(v for f, v in impl.items() if f.startswith("frontend/"))
    b_test = sum(v for f, v in tests.items() if f.startswith("backend/"))
    f_test = sum(v for f, v in tests.items() if f.startswith("frontend/"))
    print(f"- 実装本体（行、空行・コメント込み）: backend/app {b_impl:,}・frontend/src {f_impl:,}・合計 {b_impl + f_impl:,}")
    print(f"- テスト（行）: backend/tests {b_test:,}・frontend {f_test:,}・合計 {b_test + f_test:,}")
    print(f"- 実装本体:テスト比 = 1 : {(b_test + f_test) / max(1, b_impl + f_impl):.2f}")
    print(f"- ファイル数: 実装 backend {sum(f.startswith('backend/') for f in impl)}・frontend "
          f"{sum(f.startswith('frontend/') for f in impl)}／テスト backend "
          f"{sum(f.startswith('backend/') for f in tests)}・frontend {sum(f.startswith('frontend/') for f in tests)}")
    if args.full and npx():
        print("- cloc:")
        out = run([npx(), "--yes", "cloc", ".", "--quiet",
                   "--exclude-dir=node_modules,.venv,venv,.next,dist,build,.git,coverage,.pytest_cache,__pycache__,.turbo,htmlcov",
                   "--exclude-ext=json,lock,svg,png,jpg,jpeg,ico,pbf,mbtiles,parquet"], check=False)
        print("```\n" + out.strip() + "\n```")

    # 2. churn
    print("\n## 2. 変更頻度（churn）")
    log = git("log", f"--since={since}", "--name-only", "--pretty=format:")
    commits = git("log", f"--since={since}", "--oneline").count("\n")
    names = [l for l in log.splitlines() if l]
    freq = defaultdict(int)
    for n in names:
        freq[n] += 1
    print(f"- コミット数: {commits}／変更ファイル数（ユニーク）: {len(freq)}")
    print("- 上位10: " + "、".join(f"`{f}` {c}" for f, c in sorted(freq.items(), key=lambda x: -x[1])[:10]))

    # 3〜5（重い項目は --full のみ）
    if args.full:
        print("\n## 3. テスト規模")
        py = venv_python()
        if py:
            out = run([py, "-m", "pytest", "-q", "-m", "not postgis", "--collect-only"], cwd=REPO_ROOT / "backend", check=False)
            tail = [l for l in out.splitlines() if "selected" in l or "deselected" in l or "tests collected" in l]
            print("- backend pytest --collect-only: " + (tail[-1] if tail else out.strip().splitlines()[-1:] or "取得失敗"))
        if npx() and (REPO_ROOT / "frontend/node_modules").exists():
            out = run([npx(), "vitest", "list"], cwd=REPO_ROOT / "frontend", check=False)
            print(f"- frontend vitest list: {sum(1 for l in out.splitlines() if l.strip())}件")
        print("\n## 4. 静的検査")
        if npx() and (REPO_ROOT / "frontend/node_modules").exists():
            out = run([npx(), "tsc", "--noEmit"], cwd=REPO_ROOT / "frontend", check=False)
            print(f"- tsc --noEmit: {sum(1 for l in out.splitlines() if 'error TS' in l)}エラー")
            out = run([npx(), "eslint", "."], cwd=REPO_ROOT / "frontend", check=False)
            summary = [l for l in out.splitlines() if "problem" in l]
            print(f"- eslint: {summary[-1].strip() if summary else '0 problems'}")
        print("\n## 5. 依存関係")
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if npm:
            out = run([npm, "audit", "--json"], cwd=REPO_ROOT / "frontend", check=False)
            try:
                v = json.loads(out)["metadata"]["vulnerabilities"]
                print(f"- npm audit: critical {v.get('critical', 0)} / high {v.get('high', 0)} / "
                      f"moderate {v.get('moderate', 0)} / low {v.get('low', 0)}")
            except (ValueError, KeyError):
                print("- npm audit: 取得失敗")
    else:
        print("\n（テスト件数・tsc/eslint・npm audit は --full で計測）")
    return 0


# --- trigger ----------------------------------------------------------------

TRIGGER_DAYS = 14
TRIGGER_IMPL_LINES = 20_000


def latest_target_commit() -> tuple[str | None, str | None]:
    """history/ の直近 all/consistency/overall ファイルから対象コミットSHAを取る。"""
    cands = []
    for p in HISTORY_DIR.glob("*.md"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})_(all|consistency|overall)\.md$", p.name)
        if m:
            cands.append((m.group(1), p))
    for _, p in sorted(cands, reverse=True):
        for line in read_text(p).splitlines()[:40]:
            if "対象コミット" in line:
                m = re.search(r"`([0-9a-f]{7,40})`", line)
                if m:
                    return m.group(1), p.name
    return None, None


def cmd_trigger(args: argparse.Namespace) -> int:
    today = dt.date.today()
    last = latest_history_date()
    days = (today - last).days if last else None
    sha, src = latest_target_commit()
    lines = None
    if sha and git("cat-file", "-t", sha, check=False).strip() == "commit":
        stat = git("diff", "--shortstat", f"{sha}..HEAD", "--",
                   "backend/app", "frontend/src", ":!frontend/src/**/*.test.*", ":!frontend/src/**/*.spec.*",
                   ":!frontend/src/types/generated", check=False)
        nums = [int(x) for x in re.findall(r"(\d+) (?:insertion|deletion)", stat)]
        lines = sum(nums)
    fired = []
    print("## 周期レビュー トリガー判定")
    print(f"- 前回レビュー（history/ 最新日付）: {last}（{days}日経過、閾値 {TRIGGER_DAYS}日）")
    if days is not None and days >= TRIGGER_DAYS:
        fired.append("日数")
    if lines is not None:
        print(f"- 実装コード（テスト・生成物除く）の変更行数（{sha[:7]}..HEAD、{src} の対象コミット起点）: "
              f"{lines:,}行（閾値 {TRIGGER_IMPL_LINES:,}）")
        if lines >= TRIGGER_IMPL_LINES:
            fired.append("変更行数")
    else:
        print("- 変更行数: 直近レビューの対象コミットを特定できず未計測")
    print("- 分割元タスク（複数のTxxxへ分割する規模Lのタスク）の完了直後かは自動判定できない。該当すれば量に関係なく実施する")
    print()
    print("判定: " + (f"**該当（{'・'.join(fired)}）** → /review:all（最低限 /review:consistency）を実施する" if fired
                   else "未該当"))
    return 0


# --- main -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("docs", help="docs/modules・improvement-plan・history の機械的整合性チェック")
    p.add_argument("--since", help="記載漏れ・ソースコード経緯コメントのチェックをこのref以降の追加分へ限定する")
    p.add_argument("--staged", action="store_true", help="pre-commit用: ステージ済み変更に関係する項目のみ")
    p.set_defaults(func=cmd_docs)
    p = sub.add_parser("size", help="規模ウォッチ（complexity.md）")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--update", action="store_true", help="前回値ファイル（history/size_watch.json）を今回値で更新する")
    p.set_defaults(func=cmd_size)
    p = sub.add_parser("metrics", help="定量メトリクス（metrics.md）")
    p.add_argument("--since", help="churnの起点日（既定: history/ の直近metricsファイル日付）")
    p.add_argument("--full", action="store_true", help="テスト件数・tsc/eslint・npm audit も計測する（数分）")
    p.set_defaults(func=cmd_metrics)
    p = sub.add_parser("trigger", help="周期レビューのトリガー判定")
    p.set_defaults(func=cmd_trigger)
    args = parser.parse_args(argv)
    os.chdir(REPO_ROOT)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
