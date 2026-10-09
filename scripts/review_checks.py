"""リポジトリの機械的な検査と計測。

検知器（`docs`）を足す条件は .claude/rules/fixing.md「検知器を足す条件は厳しい」が持つ。

## 使い方

    python scripts/review_checks.py docs      # 文書の整合（常に全件）
    python scripts/review_checks.py size      # 規模と前回比
    python scripts/review_checks.py metrics   # 定量メトリクスと総量の前回比
    python scripts/review_checks.py trigger   # 周期レビューの発火判定
    python scripts/review_checks.py change    # 変更の増減と規模の札（master との差分から）

終了コード: `docs`は違反があれば1。それ以外は表示のみで常に0。

`change`は検知器ではなく、作業者が自分の差分に対してその場で打つ報告である
（差分の起点を選ぶので、検知器を足す条件の外にある）。

`size`・`metrics`・`trigger`はプロジェクトの今の姿を HEAD から測るので、HEAD が origin/master より
遅れていれば止まる（`scripts/checkout_freshness.py`）。`docs`は手元の作業ツリーそのものを検査し、
`change`は origin/master との差分を報告するので、遅れに左右されない。
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
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

CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs", ".mts", ".sh", ".bat", ".css")
#: ワークフローの YAML は CI・デプロイ・担当の実行の手順そのものなので、コードとして数える。
WORKFLOW_PREFIXES = (".github/workflows/",)
#: テストのファイル名を持たないテストの足場の置き場（`/tests/`・`/test/`の外にあるもの）。
TEST_PREFIXES = ("frontend/src/testing/", "frontend/src/structure/")
#: 総量の「実装」の内訳は置き場で決める。製品は本番で動くコードの置き場で、ほかの実装は
#: 道具（運用・計測・検査の道具・E2Eの共通部品・テストランナーとビルドの設定・CIのワークフロー・
#: 開発機での起動の道具）。道具の置き場を列挙しないのは、道具が改名・新設されても製品へ
#: 落ちないため。製品の増減が生成物・道具の増減に埋もれないよう、総量の前回比で分けて出す。
#: タスク管理は製品と無関係に作り直されるので、道具の増減に混ぜずに分ける。
#: ここで宣言する置き場は、どれも追跡下のファイルに当たる（`backend/tests/test_review_checks.py`）。
PRODUCT_PREFIXES = ("backend/app/", "frontend/src/")
GENERATED_PREFIXES = ("frontend/src/types/generated/",)
#: タスク管理の置き場の正本は CI 側（`.github/taskflow-paths`。製品の CI はここだけの変更で重い検査を飛ばす）。
TASKFLOW_PREFIXES = tuple(
    line for line in (REPO_ROOT / ".github" / "taskflow-paths").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
)

#: この行数以上のファイルは、個別閾値（size_thresholds.json）を持つまで毎回発火する。
#: 越えた周期だけ鳴らすと、分類で閾値を決めなかったファイルが以後+15%の成長でしか
#: 鳴らなくなり、周期ごとの複利で黙って膨らむ。
LARGE_FILE_LINES = 1000
#: 前回比の発火の増加率（%）。個別閾値の見直しも同じ率を縮む側に当てる。
GROWTH_PERCENT = 15
#: 前回比の発火に要る増分の下限。小さいファイルは数十行の増分でも率が大きく出る。
GROWTH_MIN_LINES = 50
#: 個別閾値の刻み。閾値は今の行数+GROWTH_PERCENTをこの刻みへ切り上げた値に置く。
THRESHOLD_STEP_LINES = 100


def fitted_threshold(lines: int) -> int:
    """今の行数に置く個別閾値。個別閾値は自動では下がらないので、置いた閾値がこれより
    緩くなったら（縮んだ）見直しに出し、下げるか外すかを判断する。"""
    step = THRESHOLD_STEP_LINES
    return -(-lines * (100 + GROWTH_PERCENT) // (100 * step)) * step


def instruction_limit(path: str, limits: dict[str, int]) -> int | None:
    """指示の文書の種類ごとの上限（size_thresholds.json の instruction_limits）。当たらなければ None。"""
    return next((limit for pattern, limit in limits.items() if fnmatch.fnmatchcase(path, pattern)), None)


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


def cmd_docs(args: argparse.Namespace) -> int:
    universe = set(tracked_files())
    md_files = [f for f in universe
                if f.endswith(".md") and not f.startswith(FROZEN_PREFIXES)]

    sections = [
        ("dead_doc_links", "文書のリンクが解決しない",
         find_dead_doc_links(sorted(md_files), universe)),
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
    """行数。`sha`を渡すとそのコミット時点の内容を1本の`git cat-file --batch`で読む。

    バイト列のまま数えるので、UTF-8 でないファイル（Windows のバッチ等）も数える。
    """
    texts: dict[str, bytes] = {}
    if sha is None:
        for path in paths:
            try:
                texts[path] = (REPO_ROOT / path).read_bytes()
            except OSError:
                pass
    else:
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
            texts[path] = out[pos:pos + size]
            pos += size + 1
    return {path: len(text.splitlines()) for path, text in texts.items() if text}


def files_at(sha: str) -> list[str]:
    return [f for f in git("ls-tree", "-r", "-z", "--name-only", sha).split("\0") if f]


def is_test(path: str) -> bool:
    return (".test." in path or ".spec." in path or "/tests/" in path or "/test/" in path
            or path.startswith(TEST_PREFIXES))


def is_code(path: str) -> bool:
    return path.endswith(CODE_SUFFIXES) or path.startswith(WORKFLOW_PREFIXES)


def volume_kind(path: str) -> str | None:
    """総量を数える種別（実装・テスト・維持する文書）。数えないものはNone。"""
    if is_code(path):
        return "テスト" if is_test(path) else "実装"
    if path.endswith(".md") and not path.startswith(FROZEN_PREFIXES):
        return "文書"
    return None


def volume_counts(paths: list[str], sha: str | None = None) -> dict[str, int]:
    return line_counts([f for f in paths if volume_kind(f)], sha)


def implementation_part(path: str) -> str:
    """実装の内訳（製品・生成物・タスク管理・道具）。"""
    if path.startswith(GENERATED_PREFIXES):
        return "うち生成物"
    if path.startswith(TASKFLOW_PREFIXES):
        return "うちタスク管理"
    if path.startswith(PRODUCT_PREFIXES):
        return "うち製品"
    return "うち道具"


def volume_totals(counts: dict[str, int]) -> dict[str, int]:
    totals = {"実装": 0, "うち製品": 0, "うち生成物": 0, "うちタスク管理": 0, "うち道具": 0,
              "テスト": 0, "文書": 0}
    for f, n in counts.items():
        kind = volume_kind(f)
        totals[kind] += n
        if kind == "実装":
            totals[implementation_part(f)] += n
    return totals


def cmd_size(args: argparse.Namespace) -> int:
    counts = volume_counts(tracked_files())
    decided = json.loads(read(SIZE_THRESHOLDS)) if SIZE_THRESHOLDS.exists() else {}
    limits = decided.get("instruction_limits", {})
    # 指示の文書は種類ごとの上限だけで見て、ファイルごとの閾値を持たせない。
    exceptions = sorted(f for f in decided.get("thresholds", {}) if instruction_limit(f, limits) is not None)
    thresholds = {f: n for f, n in decided.get("thresholds", {}).items() if f not in exceptions}
    thresholds.update({f: limit for f in counts if (limit := instruction_limit(f, limits)) is not None})
    on_fire = decided.get("on_fire", {})
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
        if p is not None and p > 0 and (cur - p) * 100 >= GROWTH_PERCENT * p and cur - p >= GROWTH_MIN_LINES:
            reasons.append(f"+{(cur - p) / p * 100:.0f}%")
        if th is None and cur >= LARGE_FILE_LINES:
            reasons.append(f"{LARGE_FILE_LINES:,}行以上・閾値未設定")
        if th and cur >= th:
            reasons.append(f"閾値{th:,}超過")
        if reasons:
            fired.append(f)
        if th and f not in exceptions and instruction_limit(f, limits) is None and th > fitted_threshold(cur):
            slack.append(f"{f}（{th}→{fitted_threshold(cur)}）")
        delta = f"{cur - p:+d}" if p is not None else "新規"
        rate = f"{cur / th:.0%}" if th else "-"
        print(f"| {f} | {cur:,} | {p if p is not None else '-'} | {delta} | {th or '-'} | "
              f"{rate} | {'・'.join(reasons)} |")
    print()
    print(f"発火 {len(fired)}件: " + (", ".join(fired) if fired else "なし"))
    for f in fired:
        if f in on_fire:
            print(f"  - {f} の既定の対応: {on_fire[f]}")
    print(f"閾値の見直し（今の行数+{GROWTH_PERCENT}%を{THRESHOLD_STEP_LINES}行に切り上げた値より緩い・削除済み） "
          f"{len(slack)}件: "
          + (", ".join(slack) if slack else "なし"))
    if exceptions:
        print(f"指示の文書のファイルごとの閾値（無視した。上限は instruction_limits だけ） {len(exceptions)}件: "
              + ", ".join(exceptions))
    if not base_sha:
        print("（周期レビューのタグが無いため前回比は出していない）")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    files = tracked_files()
    volume = volume_counts(files)
    counts = {f: n for f, n in volume.items() if is_code(f)}
    by_area: dict[str, int] = defaultdict(int)
    for f, n in counts.items():
        by_area[f.split("/")[0] if "/" in f else "（ルート）"] += n
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


# --- 差分の報告（作業者が自分の差分に対して打つ。検査ではない） -----------------

#: .claude/skills/file-issue/SKILL.md「規模の札」の閾値（実装＋テストの変更行の上限）。
SIZE_LABELS = ((200, "S"), (1000, "M"))
GENERATED_NAMES = ("package-lock.json",)


def merge_base(base: str, head: str) -> str:
    return git("merge-base", base, head).strip()


def change_kind(path: str) -> str:
    """変更の行数を分ける種別。規模の札は実装とテストだけで決まる。

    実装とテストは総量と同じ分け方（`volume_kind`）で、コードでないファイルは設定。
    """
    if path.startswith(GENERATED_PREFIXES) or path.endswith(GENERATED_NAMES):
        return "生成物"
    if path.endswith(".md"):
        return "文書"
    return volume_kind(path) or "設定"


def cmd_change(args: argparse.Namespace) -> int:
    target = args.head or "HEAD"
    mb = merge_base(args.base, target)
    # -z では、移したファイルの行が「追加\t削除\t」のあと移す前と後のパスを別の欄に持つ。
    fields = git("diff", "-M", "--numstat", "-z", mb, *([args.head] if args.head else [])).split("\0")
    rows = []
    i = 0
    while i < len(fields) - 1:
        plus, minus, path = fields[i].split("\t", 2)
        i += 1
        if not path:
            path = fields[i + 1]
            i += 2
        if plus != "-":
            rows.append((path, int(plus), int(minus)))
    if not args.head:
        for path in git("ls-files", "--others", "--exclude-standard").splitlines():
            rows.append((path, len(read(REPO_ROOT / path).splitlines()), 0))
    totals = {kind: [0, 0] for kind in ("実装", "テスト", "文書", "設定", "生成物")}
    for path, added, deleted in rows:
        totals[change_kind(path)][0] += added
        totals[change_kind(path)][1] += deleted
    measured = sum(totals["実装"]) + sum(totals["テスト"])
    label = next((name for limit, name in SIZE_LABELS if measured <= limit), "L")
    shown = git("rev-parse", "--short", args.head).strip() if args.head else "作業ツリー（未追跡のファイルを含む）"
    print(f"## 変更の増減（{mb[:8]}..{shown}）")
    print("増減: " + "・".join(f"{kind} +{a:,}/−{d:,}" for kind, (a, d) in totals.items()
                             if kind in ("実装", "テスト", "文書") or a or d))
    print(f"規模: {label}（実装＋テスト {measured:,}行。{SIZE_LABELS[0][0]}以下 S・"
          f"{SIZE_LABELS[1][0]}以下 M・超えると L。本番DBへ書くタスクは行数によらず L）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text, func, measures_head in (
        ("docs", "文書の整合（常に全件）", cmd_docs, False),
        ("metrics", "定量メトリクスと総量の前回比", cmd_metrics, True),
        ("trigger", "周期レビューの発火判定", cmd_trigger, True),
    ):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func, measures_head=measures_head)
    p = sub.add_parser("change", help="変更の増減と規模の札")
    p.add_argument("--base", default="origin/master", help="比べる相手（合流点から見る）")
    p.add_argument("--head", help="見る版（省くと作業ツリー）")
    p.set_defaults(func=cmd_change, measures_head=False)
    p = sub.add_parser("size", help="規模と前回比")
    p.add_argument("--top", type=int, default=5, help="領域ごとに見る上位件数")
    p.set_defaults(func=cmd_size, measures_head=True)
    args = parser.parse_args()
    if args.measures_head:
        from checkout_freshness import require_current
        require_current(REPO_ROOT)
    return args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
