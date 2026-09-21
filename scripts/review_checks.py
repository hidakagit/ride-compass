"""リポジトリの機械的な検査と計測。

## 検知器の設計要件

検知器はプロジェクト全体への一律チェックとして自動実行され、**実行タイミングも走査範囲も
こちらで選べない**。したがって置いてよいのは、**どの文脈でも絶対に正しいと保証できる
事実だけ**である。

この要件から、次が導かれる。

- **走査範囲を絞る仕組みを持たない。** 不変条件なら、全件でも差分でも同じ答えになる。
  「新しく入った分だけを咎める」必要があるなら、それは不変条件ではない
- **許可リストを持たない。** 許可リストは誤検知を認めた印である。「この綴りは外部の
  語彙だから除外する」が必要なら、その検査は事実を見ていない
- **母集団を手で書かない。** 「どのファイルが対象か」を人が列挙すると、実装が動いた
  ときに静かにずれる。対象は、その検査が読む対象そのもの（マークダウン全件・台帳1本）
  から自然に決まるものに限る
- **実装そのものを検査対象にしない**（コードの書き方・import規則・型・レイヤーの
  不変条件）。実装側の道具（lint・型検査・テスト）が持つ。検知器が実装の姿を知ろうと
  すると写し（スナップショット・定数表）を抱え、実装が変わった瞬間に黙って死ぬ
- **保存した過去の値と比べない。** それは検査ではなく報告である。必要な過去の値は
  `periodic-review/NNN` タグが指すコミットから導く

## 使い方

    python scripts/review_checks.py docs      # 文書と台帳の整合（常に全件）
    python scripts/review_checks.py size      # 規模と前回比
    python scripts/review_checks.py metrics   # 定量メトリクス
    python scripts/review_checks.py trigger   # 周期レビューの発火判定

終了コード: `docs`は違反があれば1。それ以外は表示のみで常に0。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN_DOC = "docs/improvement-plan.md"
SIZE_THRESHOLDS = REPO_ROOT / "scripts" / "size_thresholds.json"

#: 記録。**維持しない**（`docs/records/README.md`）。記録時点で嘘が無ければよく、後から
#: 実装と食い違っても欠陥ではないので、整合を求める対象にしない。走査範囲を文脈で絞る
#: のとは別物で、パスで決まる恒久的な分類。実在はするのでリンク先の母集団には入れる。
FROZEN_PREFIXES = ("docs/records/",)

#: 周期レビューを実施した対象コミットへ打つ注釈付きタグ。`NNN`は回数。
#: 日付を名前に使わないのは、同じ日に複数回レビューした実績があり一意にならないため。
REVIEW_TAG_PREFIX = "periodic-review/"
TRIGGER_DAYS = 14
TRIGGER_IMPL_LINES = 20_000

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s#]+)(?:#[^)]*)?\)")
#: 雛形の綴り。「タスク番号1件=1ファイル」等を説明するためのもので、実在しなくてよい。
PLACEHOLDER_RE = re.compile(r"Txxx|YYYY-MM-DD|<[^>]+>")
PLAN_ENTRY_RE = re.compile(r"^- \[[ x]\] \[T\d+[a-z0-9-]*\]\(([^)]+)\)")
TASKS_DIR = REPO_ROOT / "docs" / "records" / "tasks"
STATE_RE = re.compile(r"^状態: *(完了|未完了)")
#: タスク記録のファイル名。日付名の実施記録や索引と区別する。
TASK_FILE_RE = re.compile(r"^T\d+[a-z0-9-]*\.md$")

CODE_SUFFIXES = (".py", ".ts", ".tsx")


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0 and check:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def tracked_files() -> list[str]:
    """追跡下の全ファイル。**「実在するか」の母集団はこちら。**

    走査対象と取り違えると、記録を走査から外したとたんに、そこを指す生きた文書のリンクが
    一斉に「実在しない」へ化ける。
    """
    return [line for line in git("ls-files").splitlines() if line]


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def review_tags() -> list[tuple[str, str, dt.date | None]]:
    """周期レビューのタグを新しい順に (タグ名, コミット, 実施日)。"""
    out = git("for-each-ref", "--sort=-refname",
              "--format=%(refname:short)\t%(creatordate:short)",
              f"refs/tags/{REVIEW_TAG_PREFIX}*", check=False)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or not parts[0]:
            continue
        sha = git("rev-list", "-n", "1", parts[0], check=False).strip()
        if not sha:
            continue
        try:
            day = dt.date.fromisoformat(parts[1])
        except ValueError:
            day = None
        rows.append((parts[0], sha, day))
    return rows


# --- 検知器 -----------------------------------------------------------------

def find_dead_doc_links(md_files: list[str], universe: set[str]) -> list[str]:
    """解決しないリンク。

    リンクは解決するかしないかのどちらかで、いつ誰がどう走査しても答えが変わらない。
    外部URLはこのリポジトリの事実ではないので見ない。雛形の綴りは実在しなくてよい。
    """
    out = []
    for f in md_files:
        path = REPO_ROOT / f
        for lineno, line in enumerate(read(path).splitlines(), 1):
            for target in MARKDOWN_LINK_RE.findall(line):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                if PLACEHOLDER_RE.search(target):
                    continue
                resolved = (path.parent / target).resolve()
                try:
                    rel_path = resolved.relative_to(REPO_ROOT).as_posix()
                except ValueError:
                    continue
                if rel_path in universe or resolved.is_dir():
                    continue
                out.append(f"{f}:{lineno}: {target} が存在しない")
    return out


def find_plan_entry_problems() -> list[str]:
    """台帳のエントリが指す先の不在と、2つのエントリが同じ先を指している箇所。

    **番号ではなくリンク先を見る。** 同じ番号でも別の記録を指しているなら曖昧さは無く
    （`T317` と `T317-2.md` が実例）、逆に番号が違っても同じ先を指していれば、どちらの
    行を読めばよいか決まらない。
    """
    plan = REPO_ROOT / PLAN_DOC
    if not plan.exists():
        return [f"{PLAN_DOC} が無い（台帳が無ければエントリの一意性を検査できない）"]
    seen: dict[str, int] = {}
    out = []
    for lineno, line in enumerate(read(plan).splitlines(), 1):
        m = PLAN_ENTRY_RE.match(line)
        if not m:
            continue
        target = m.group(1)
        if not (plan.parent / target).exists():
            out.append(f"{PLAN_DOC}:{lineno}: リンク先 {target} が無い")
        elif target in seen:
            out.append(f"{PLAN_DOC}:{lineno}: {target} を {seen[target]}行目も指している")
        else:
            seen[target] = lineno
    return out


def find_task_state_problems() -> list[str]:
    """タスク記録の状態表記と、台帳との対応。

    **管理したいのは「片付いたかどうか」だけ**なので、`状態:` は `完了` か `未完了` で
    始まる。着手中・保留・設計確定といった作業中の呼び分けは一時的な話なので本文へ書く。
    2語に決めてあるぶん、次の3つが語彙の推測なしに言える。

    - 表記が2語のどちらでもない → どちらか判定できない
    - `未完了` なのに台帳へ行が無い → 誤ってクローズした（誰も着手しない）
    - `完了` なのに台帳へ行がある → 閉じ忘れ（終わった話が候補に混ざる）
    """
    plan = REPO_ROOT / PLAN_DOC
    listed = {m.group(1) for line in read(plan).splitlines()
              if (m := PLAN_ENTRY_RE.match(line))} if plan.exists() else set()
    out = []
    for f in sorted(f for f in TASKS_DIR.glob("*.md") if TASK_FILE_RE.match(f.name)):
        rel_target = f"records/tasks/{f.name}"
        state = next((l for l in read(f).splitlines() if l.startswith("状態:")), None)
        if state is None or not STATE_RE.match(state):
            out.append(f"{rel_target}: 状態行が「完了」「未完了」で始まっていない"
                       f"（{state or '状態行が無い'}）")
            continue
        done = STATE_RE.match(state).group(1) == "完了"
        if not done and rel_target not in listed:
            out.append(f"{rel_target}: 未完了なのに台帳に行が無い（誤ってクローズした）")
        if done and rel_target in listed:
            out.append(f"{rel_target}: 完了なのに台帳に行がある（閉じ忘れ）")
    return out


def cmd_docs(args: argparse.Namespace) -> int:
    universe = set(tracked_files())
    md_files = [f for f in universe
                if f.endswith(".md") and not f.startswith(FROZEN_PREFIXES)]

    sections = [
        ("dead_doc_links", "文書のリンクが解決しない",
         find_dead_doc_links(sorted(md_files), universe)),
        ("plan_entries", "台帳のエントリが同じ先を指している／リンク先が無い",
         find_plan_entry_problems()),
        ("task_state", "タスク記録の状態表記と、台帳との対応",
         find_task_state_problems()),
    ]

    total = 0
    for key, title, lines in sections:
        print(f"## [{key}] {title}: {len(lines)}件")
        for line in lines:
            print(f"  - {line}")
        total += len(lines)

    print()
    if total:
        print(f"違反 {total}件")
        return 1
    print("違反なし")
    return 0


# --- 計測（検査ではなく報告。前回値は保存せずタグから導く） -----------------

def line_counts(paths: list[str], sha: str | None = None) -> dict[str, int]:
    out = {}
    for path in paths:
        text = git("show", f"{sha}:{path}", check=False) if sha else read(REPO_ROOT / path)
        if text:
            out[path] = len(text.splitlines())
    return out


def cmd_size(args: argparse.Namespace) -> int:
    counts = line_counts([f for f in tracked_files()
                          if f.endswith(CODE_SUFFIXES + (".md",))
                          and not f.startswith(FROZEN_PREFIXES)])
    thresholds = (json.loads(read(SIZE_THRESHOLDS)).get("thresholds", {})
                  if SIZE_THRESHOLDS.exists() else {})
    groups: dict[str, list[str]] = defaultdict(list)
    for f in counts:
        groups["docs" if f.startswith("docs/") else f.split("/")[0]].append(f)
    top: set[str] = set()
    for members in groups.values():
        top.update(sorted(members, key=lambda f: -counts[f])[:args.top])
    watched = sorted(top | set(thresholds), key=lambda f: -counts.get(f, 0))

    tags = review_tags()
    base_tag, base_sha, base_date = tags[0] if tags else (None, None, None)
    prev = line_counts(watched, base_sha) if base_sha else {}

    print(f"## 規模（対象 {git('rev-parse', '--short', 'HEAD').strip()}、"
          f"前回 {base_tag or '記録なし'} / {base_date or '-'}）")
    print("| ファイル | 今回 | 前回 | 増分 | 閾値 | 発火 |")
    print("|---|---:|---:|---:|---:|---|")
    fired = []
    for f in watched:
        cur = counts.get(f)
        if cur is None:
            print(f"| {f} | 削除済み | {prev.get(f, '-')} | - | - | - |")
            continue
        p = prev.get(f)
        reasons = []
        if p is not None and p > 0 and (cur - p) / p >= 0.15:
            reasons.append(f"+{(cur - p) / p * 100:.0f}%")
        if p is not None and p < 1000 <= cur:
            reasons.append("1,000行超過")
        th = thresholds.get(f)
        if th and cur >= th:
            reasons.append(f"閾値{th:,}超過")
        if reasons:
            fired.append(f)
        delta = f"{cur - p:+d}" if p is not None else "新規"
        print(f"| {f} | {cur:,} | {p if p is not None else '-'} | {delta} | {th or '-'} | "
              f"{'・'.join(reasons)} |")
    print()
    print(f"発火 {len(fired)}件: " + (", ".join(fired) if fired else "なし"))
    if not base_sha:
        print("（周期レビューのタグが無いため前回比は出していない）")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    files = tracked_files()
    code = [f for f in files if f.endswith(CODE_SUFFIXES)]
    counts = line_counts(code)
    by_area: dict[str, int] = defaultdict(int)
    for f, n in counts.items():
        by_area[f.split("/")[0]] += n
    tests = [f for f in code if ".test." in f or ".spec." in f or "/tests/" in f]
    docs_lines = sum(len(read(REPO_ROOT / f).splitlines())
                     for f in files if f.endswith(".md") and not f.startswith(FROZEN_PREFIXES))
    records_lines = sum(len(read(REPO_ROOT / f).splitlines())
                        for f in files if f.startswith(FROZEN_PREFIXES))

    tags = review_tags()
    churn = "-"
    if tags:
        stat = git("diff", "--shortstat", f"{tags[0][1]}..HEAD",
                   "--", "backend", "frontend", check=False)
        churn = f"{sum(int(x) for x in re.findall(r'(\d+) (?:insertion|deletion)', stat)):,}行"

    print(f"# 定量メトリクス（{dt.datetime.now(tz=dt.timezone.utc).date().isoformat()}、"
          f"対象 {git('rev-parse', '--short', 'HEAD').strip()}）\n")
    print("| 指標 | 値 |")
    print("|---|---:|")
    for area in sorted(by_area):
        print(f"| コード行数: {area} | {by_area[area]:,} |")
    print(f"| コードファイル数 | {len(counts):,} |")
    print(f"| うちテスト | {len(tests):,} |")
    print(f"| 維持する文書 | {docs_lines:,}行 |")
    print(f"| 記録（維持しない） | {records_lines:,}行 |")
    print(f"| 前回レビュー以降のコード変更 | {churn} |")
    return 0


def cmd_trigger(args: argparse.Namespace) -> int:
    tags = review_tags()
    print("## 周期レビュー トリガー判定")
    if not tags:
        print(f"- 前回レビューのタグ（{REVIEW_TAG_PREFIX}*）が無い")
        print("\n判定: **該当**（前回の記録が無い。実施してタグを打つ）")
        return 0
    name, sha, day = tags[0]
    fired = []
    days = (dt.datetime.now(tz=dt.timezone.utc).date() - day).days if day else None
    print(f"- 前回レビュー: {name} / {day}（{days}日経過、閾値 {TRIGGER_DAYS}日）")
    if days is not None and days >= TRIGGER_DAYS:
        fired.append("日数")
    stat = git("diff", "--shortstat", f"{sha}..HEAD", "--", "backend", "frontend", check=False)
    lines = sum(int(x) for x in re.findall(r"(\d+) (?:insertion|deletion)", stat))
    print(f"- コードの変更行数（{sha[:7]}..HEAD）: {lines:,}行（閾値 {TRIGGER_IMPL_LINES:,}）")
    if lines >= TRIGGER_IMPL_LINES:
        fired.append("変更行数")
    print()
    print("判定: " + (f"**該当（{'・'.join(fired)}）** → /review を実施する" if fired else "未該当"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text, func in (
        ("docs", "文書と台帳の整合（常に全件）", cmd_docs),
        ("metrics", "定量メトリクス", cmd_metrics),
        ("trigger", "周期レビューの発火判定", cmd_trigger),
    ):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)
    p = sub.add_parser("size", help="規模と前回比")
    p.add_argument("--top", type=int, default=5, help="領域ごとに見る上位件数")
    p.set_defaults(func=cmd_size)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
