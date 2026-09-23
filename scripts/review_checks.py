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
    python scripts/review_checks.py metrics   # 定量メトリクスと総量の前回比
    python scripts/review_checks.py trigger   # 周期レビューの発火判定

終了コード: `docs`は違反があれば1。それ以外は表示のみで常に0。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestration.core import LEDGER_ROW_RE, PLAN_DOC
from orchestration.core import TASKS_DIR as TASKS_REL

REPO_ROOT = Path(__file__).resolve().parent.parent
#: 台帳の行を閉じた（消した）状態が揃っているべきブランチ。並行実行の作業ブランチでは、
#: 台帳の行は取り込みの後に司令塔が消す（docs/conventions/orchestration.md「監査の結果」）。
MAIN_BRANCH = "master"
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
TASKS_DIR = REPO_ROOT / TASKS_REL
STATE_RE = re.compile(r"^状態: *(完了|未完了)")
#: タスク記録のファイル名。日付名の実施記録や索引と区別する。
TASK_FILE_RE = re.compile(r"^T\d+[a-z0-9-]*\.md$")

CODE_SUFFIXES = (".py", ".ts", ".tsx")

#: この行数以上のファイルは、個別閾値（size_thresholds.json）を持つまで毎回発火する。
#: 越えた周期だけ鳴らすと、分類で閾値を決めなかったファイルが以後+15%の成長でしか
#: 鳴らなくなり、周期ごとの複利で黙って膨らむ。
LARGE_FILE_LINES = 1000
#: 個別閾値は自動では下がらない。到達率がこれを下回ったら、下げるか外すかを判断する。
THRESHOLD_SLACK_RATIO = 0.5


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
        m = LEDGER_ROW_RE.match(line)
        if not m:
            continue
        target = m.group(2)
        if not (plan.parent / target).exists():
            out.append(f"{PLAN_DOC}:{lineno}: リンク先 {target} が無い")
        elif target in seen:
            out.append(f"{PLAN_DOC}:{lineno}: {target} を {seen[target]}行目も指している")
        else:
            seen[target] = lineno
    return out


def checked_branch() -> str | None:
    """検査しているコミットのブランチ。CIではワークフローを起動したref、手元では今のブランチ。

    どちらも取れない（プルリクエストの合成コミット・detached HEAD）ならNone。
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        ref = os.environ.get("GITHUB_REF", "")
        return ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else None
    return git("symbolic-ref", "--short", "-q", "HEAD", check=False).strip() or None


def find_task_state_problems(on_main: bool) -> tuple[list[str], list[str]]:
    """タスク記録の状態表記と、台帳との対応。(違反, 参考) を返す。

    **管理したいのは「片付いたかどうか」だけ**なので、`状態:` は `完了` か `未完了` で
    始まる。着手中・保留・設計確定といった作業中の呼び分けは一時的な話なので本文へ書く。
    2語に決めてあるぶん、次の3つが語彙の推測なしに言える。

    - 表記が2語のどちらでもない → どちらか判定できない
    - `未完了` なのに台帳へ行が無い → 誤ってクローズした（誰も着手しない）
    - `完了` なのに台帳へ行がある → 閉じ忘れ（終わった話が候補に混ざる）

    2つ目と3つ目は`MAIN_BRANCH`でだけ違反にし、それ以外のブランチでは参考として出す。台帳は全担当が
    1行ずつ触る共有のファイルで、別々のブランチが隣り合った行を変えると取り込みで衝突するため、
    並行実行の担当は`状態:`だけを変え（閉じる・開け直す）、行は司令塔が取り込みで直す
    （`scripts/orchestrate.py ledger sync`）。masterへ入る時点で行が揃っていることは、
    masterへのpushのCIがこの検査で見る。
    """
    plan = REPO_ROOT / PLAN_DOC
    listed = {m.group(2) for line in read(plan).splitlines()
              if (m := LEDGER_ROW_RE.match(line))} if plan.exists() else set()
    out, notes = [], []
    for f in sorted(f for f in TASKS_DIR.glob("*.md") if TASK_FILE_RE.match(f.name)):
        rel_target = f"records/tasks/{f.name}"
        state = next((l for l in read(f).splitlines() if l.startswith("状態:")), None)
        if state is None or not STATE_RE.match(state):
            out.append(f"{rel_target}: 状態行が「完了」「未完了」で始まっていない"
                       f"（{state or '状態行が無い'}）")
            continue
        done = STATE_RE.match(state).group(1) == "完了"
        if not done and rel_target not in listed:
            (out if on_main else notes).append(f"{rel_target}: 未完了なのに台帳に行が無い（誤ってクローズしたか、開け直した）")
        if done and rel_target in listed:
            (out if on_main else notes).append(f"{rel_target}: 完了なのに台帳に行がある（閉じ忘れ）")
    return out, notes


def cmd_docs(args: argparse.Namespace) -> int:
    universe = set(tracked_files())
    branch = checked_branch()
    state_problems, state_notes = find_task_state_problems(branch == MAIN_BRANCH)
    md_files = [f for f in universe
                if f.endswith(".md") and not f.startswith(FROZEN_PREFIXES)]

    sections = [
        ("dead_doc_links", "文書のリンクが解決しない",
         find_dead_doc_links(sorted(md_files), universe)),
        ("plan_entries", "台帳のエントリが同じ先を指している／リンク先が無い",
         find_plan_entry_problems()),
        ("task_state", "タスク記録の状態表記と、台帳との対応",
         state_problems),
    ]

    total = 0
    for key, title, lines in sections:
        print(f"## [{key}] {title}: {len(lines)}件")
        for line in lines:
            print(f"  - {line}")
        total += len(lines)
    if state_notes:
        print(f"## [参考] 状態と台帳の行の食い違い: {len(state_notes)}件"
              f"（{branch or 'ブランチ不明'}は{MAIN_BRANCH}ではないので違反にしない。"
              f"取り込みで司令塔が ledger sync で直す）")
        for line in state_notes:
            print(f"  - {line}")

    print()
    if total:
        print(f"違反 {total}件")
        return 1
    print("違反なし")
    return 0


# --- 計測（検査ではなく報告。前回値は保存せずタグから導く） -----------------

def line_counts(paths: list[str], sha: str | None = None) -> dict[str, int]:
    """行数。`sha`を渡すとそのコミット時点の内容を1本の`git cat-file --batch`で読む。"""
    if sha is None:
        texts = {path: read(REPO_ROOT / path) for path in paths}
    else:
        texts = {}
        result = subprocess.run(
            ["git", "cat-file", "--batch"], cwd=str(REPO_ROOT), capture_output=True,
            input="".join(f"{sha}:{path}\n" for path in paths).encode("utf-8"), check=False)
        out, pos = result.stdout, 0
        for path in paths:
            end = out.index(b"\n", pos)
            header = out[pos:end]
            pos = end + 1
            if header.endswith(b" missing"):
                continue
            size = int(header.rsplit(b" ", 1)[1])
            try:
                texts[path] = out[pos:pos + size].decode("utf-8")
            except UnicodeDecodeError:
                pass
            pos += size + 1
    return {path: len(text.splitlines()) for path, text in texts.items() if text}


def files_at(sha: str) -> list[str]:
    return [f for f in git("ls-tree", "-r", "-z", "--name-only", sha).split("\0") if f]


def is_test(path: str) -> bool:
    return ".test." in path or ".spec." in path or "/tests/" in path


def volume_kind(path: str) -> str | None:
    """総量を数える種別（実装・テスト・維持する文書）。数えないものはNone。"""
    if path.endswith(CODE_SUFFIXES):
        return "テスト" if is_test(path) else "実装"
    if path.endswith(".md") and not path.startswith(FROZEN_PREFIXES):
        return "文書"
    return None


def volume_counts(paths: list[str], sha: str | None = None) -> dict[str, int]:
    return line_counts([f for f in paths if volume_kind(f)], sha)


def volume_totals(counts: dict[str, int]) -> dict[str, int]:
    totals = {"実装": 0, "テスト": 0, "文書": 0}
    for f, n in counts.items():
        totals[volume_kind(f)] += n
    return totals


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
    large = {f for f, n in counts.items() if n >= LARGE_FILE_LINES}
    watched = sorted(top | large | set(thresholds), key=lambda f: -counts.get(f, 0))

    tags = review_tags()
    base_tag, base_sha, base_date = tags[0] if tags else (None, None, None)
    prev = line_counts(watched, base_sha) if base_sha else {}

    print(f"## 規模（対象 {git('rev-parse', '--short', 'HEAD').strip()}、"
          f"前回 {base_tag or '記録なし'} / {base_date or '-'}）")
    print("| ファイル | 今回 | 前回 | 増分 | 閾値 | 到達率 | 発火 |")
    print("|---|---:|---:|---:|---:|---:|---|")
    fired = []
    slack = []
    for f in watched:
        cur = counts.get(f)
        th = thresholds.get(f)
        if cur is None:
            print(f"| {f} | 削除済み | {prev.get(f, '-')} | - | {th or '-'} | - | - |")
            if th:
                slack.append(f"{f}（削除済み）")
            continue
        p = prev.get(f)
        reasons = []
        if p is not None and p > 0 and (cur - p) / p >= 0.15:
            reasons.append(f"+{(cur - p) / p * 100:.0f}%")
        if th is None and cur >= LARGE_FILE_LINES:
            reasons.append(f"{LARGE_FILE_LINES:,}行以上・閾値未設定")
        if th and cur >= th:
            reasons.append(f"閾値{th:,}超過")
        if reasons:
            fired.append(f)
        if th and cur / th < THRESHOLD_SLACK_RATIO:
            slack.append(f"{f}（{cur / th:.0%}）")
        delta = f"{cur - p:+d}" if p is not None else "新規"
        rate = f"{cur / th:.0%}" if th else "-"
        print(f"| {f} | {cur:,} | {p if p is not None else '-'} | {delta} | {th or '-'} | "
              f"{rate} | {'・'.join(reasons)} |")
    print()
    print(f"発火 {len(fired)}件: " + (", ".join(fired) if fired else "なし"))
    print(f"閾値の見直し（到達率{THRESHOLD_SLACK_RATIO:.0%}未満・削除済み） {len(slack)}件: "
          + (", ".join(slack) if slack else "なし"))
    if not base_sha:
        print("（周期レビューのタグが無いため前回比は出していない）")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    files = tracked_files()
    volume = volume_counts(files)
    counts = {f: n for f, n in volume.items() if f.endswith(CODE_SUFFIXES)}
    by_area: dict[str, int] = defaultdict(int)
    for f, n in counts.items():
        by_area[f.split("/")[0]] += n
    tests = [f for f in counts if is_test(f)]
    current = volume_totals(volume)
    records_lines = sum(len(read(REPO_ROOT / f).splitlines())
                        for f in files if f.startswith(FROZEN_PREFIXES))

    tags = review_tags()
    churn = "-"
    previous = None
    if tags:
        stat = git("diff", "--shortstat", f"{tags[0][1]}..HEAD",
                   "--", "backend", "frontend", check=False)
        churn = f"{sum(int(x) for x in re.findall(r'(\d+) (?:insertion|deletion)', stat)):,}行"
        previous = volume_totals(volume_counts(files_at(tags[0][1]), tags[0][1]))

    print(f"# 定量メトリクス（{dt.datetime.now(tz=dt.timezone.utc).date().isoformat()}、"
          f"対象 {git('rev-parse', '--short', 'HEAD').strip()}）\n")
    print("| 指標 | 値 |")
    print("|---|---:|")
    for area in sorted(by_area):
        print(f"| コード行数: {area} | {by_area[area]:,} |")
    print(f"| コードファイル数 | {len(counts):,} |")
    print(f"| うちテスト | {len(tests):,} |")
    print(f"| 維持する文書 | {current['文書']:,}行 |")
    print(f"| 記録（維持しない） | {records_lines:,}行 |")
    print(f"| 前回レビュー以降のコード変更 | {churn} |")
    print()
    if previous is None:
        print("（周期レビューのタグが無いため総量の前回比は出していない）")
        return 0
    print(f"## 総量の前回比（前回 {tags[0][0]} / {tags[0][2] or '-'}）\n")
    print("| 種別 | 今回 | 前回 | 差 | 増減率 |")
    print("|---|---:|---:|---:|---:|")
    for kind, cur in current.items():
        prev = previous[kind]
        rate = f"{(cur - prev) / prev:+.1%}" if prev else "-"
        print(f"| {kind} | {cur:,} | {prev:,} | {cur - prev:+,} | {rate} |")
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
        ("metrics", "定量メトリクスと総量の前回比", cmd_metrics),
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
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
