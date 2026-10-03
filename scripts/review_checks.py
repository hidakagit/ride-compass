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
  ときに静かにずれる。対象は、その検査が読む対象そのもの（マークダウン全件）
  から自然に決まるものに限る
- **実装そのものを検査対象にしない**（コードの書き方・import規則・型・レイヤーの
  不変条件）。実装側の道具（lint・型検査・テスト）が持つ。検知器が実装の姿を知ろうと
  すると写し（スナップショット・定数表）を抱え、実装が変わった瞬間に黙って死ぬ
- **保存した過去の値と比べない。** それは検査ではなく報告である。必要な過去の値は
  `periodic-review/NNN` タグが指すコミットから導く

## 使い方

    python scripts/review_checks.py docs      # 文書の整合（常に全件）
    python scripts/review_checks.py size      # 規模と前回比
    python scripts/review_checks.py metrics   # 定量メトリクスと総量の前回比
    python scripts/review_checks.py trigger   # 周期レビューの発火判定
    python scripts/review_checks.py leftovers # 撤去・改名の取り残しの候補（master との差分から）
    python scripts/review_checks.py change    # 変更の増減と規模の札（master との差分から）

終了コード: `docs`は違反があれば1。それ以外は表示のみで常に0。

`leftovers`と`change`は検知器ではなく、作業者が自分の差分に対してその場で打つ報告である
（差分の起点を選ぶので、上の設計要件の外にある）。

`size`・`metrics`・`trigger`はプロジェクトの今の姿を HEAD から測るので、HEAD が origin/master より
遅れていれば止まる（`scripts/checkout_freshness.py`）。`docs`は手元の作業ツリーそのものを検査し、
`leftovers`と`change`は origin/master との差分を報告するので、遅れに左右されない。
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
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

CODE_SUFFIXES = (".py", ".ts", ".tsx")
#: 総量の「実装」のうち、製品の挙動を持たない部分。製品の増減が生成物・運用の道具の増減に
#: 埋もれないよう、総量の前回比で分けて出す。道具は運用・計測の道具と、テストの実行の足場
#: （テストのファイル名を持たないE2Eの共通部品・テストランナーの設定）。
GENERATED_PREFIXES = ("frontend/src/types/generated/",)
TOOLING_PREFIXES = ("scripts/", "backend/scripts/", "backend/benchmarks/",
                    "frontend/e2e", "frontend/playwright", "frontend/vitest")

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


def implementation_part(path: str) -> str:
    """実装の内訳（製品・生成物・道具）。"""
    if path.startswith(GENERATED_PREFIXES):
        return "うち生成物"
    if path.startswith(TOOLING_PREFIXES):
        return "うち道具"
    return "うち製品"


def volume_totals(counts: dict[str, int]) -> dict[str, int]:
    totals = {"実装": 0, "うち製品": 0, "うち生成物": 0, "うち道具": 0, "テスト": 0, "文書": 0}
    for f, n in counts.items():
        kind = volume_kind(f)
        totals[kind] += n
        if kind == "実装":
            totals[implementation_part(f)] += n
    return totals


def cmd_size(args: argparse.Namespace) -> int:
    counts = line_counts([f for f in tracked_files()
                          if f.endswith(CODE_SUFFIXES + (".md",))
                          and not f.startswith(FROZEN_PREFIXES)])
    decided = json.loads(read(SIZE_THRESHOLDS)) if SIZE_THRESHOLDS.exists() else {}
    thresholds = decided.get("thresholds", {})
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
    for f in fired:
        if f in on_fire:
            print(f"  - {f} の既定の対応: {on_fire[f]}")
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


# --- 差分の報告（作業者が自分の差分に対して打つ。検査ではない） -----------------

#: 置き場のリポジトリの名前と、流れが使うラベルの名前を持つ設定。
TASKS_CONFIG = "tools/flow-gate/flow.config.json"
COMMENT_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".sh", ".yml", ".yaml", ".toml")
COMMENT_RE = re.compile(r"^\s*(#(?!!)|//|/\*|\*)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
#: 見出しを語に分ける区切り。文書は見出しを「司令塔と担当」のように一部だけで名指すことが多い。
HEADING_SPLIT_RE = re.compile(r"[（）()・、]|と")
DEFINITION_RES = (
    re.compile(r"^\s*(?:async\s+)?def\s+(\w+)"),
    re.compile(r"^\s*class\s+(\w+)"),
    re.compile(r"^(_*[A-Z][A-Z0-9_]{2,})\s*(?::[^=]*)?="),
    re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?"
               r"(?:function\*?|const|let|var|class|type|interface|enum)\s+(\w+)"),
    re.compile(r"^\s*(?:async\s+)?function\*?\s+(\w+)"),
    re.compile(r"^const\s+([A-Z][A-Z0-9_]{2,})\s*="),
)
LABEL_MENTION_RE = re.compile(r"ラベル\s*[「`]([^」`]+)[」`]")
IDENTIFIER_RE = re.compile(r"^\w+$", re.ASCII)
#: CLAUDE.md「規模の札」の閾値（実装＋テストの変更行の上限）。
SIZE_LABELS = ((200, "S"), (1000, "M"))
GENERATED_NAMES = ("package-lock.json",)


def merge_base(base: str, head: str) -> str:
    return git("merge-base", base, head).strip()


def diff_lines(mb: str, head: str) -> dict[str, tuple[list[str], list[str]]]:
    """ファイルごとの (消した行, 足した行)。記録は維持しないので見ない。"""
    out = git("diff", "-M", "-U0", "--no-color", mb, head, "--", ".", ":(exclude)docs/records")
    files: dict[str, tuple[list[str], list[str]]] = {}
    old = new = None
    for line in out.splitlines():
        if line.startswith("--- "):
            old = line[6:] if line.startswith("--- a/") else None
        elif line.startswith("+++ "):
            new = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith(("-", "+")) and (path := new or old):
            removed, added = files.setdefault(path, ([], []))
            (removed if line[0] == "-" else added).append(line[1:])
    return files


def show(rev: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=str(REPO_ROOT),
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False)
    return result.stdout if result.returncode == 0 else None


def search_key(path: str, surviving: list[str]) -> str:
    """消したパスを探す語。今あるファイルと紛れない一番短い後ろの部分（例: `bin/status.js`）。"""
    parts = path.split("/")
    for i in range(len(parts) - 1, -1, -1):
        suffix = "/".join(parts[i:])
        if not any(f == suffix or f.endswith("/" + suffix) for f in surviving):
            return suffix
    return path


def heading_terms(text: str) -> list[str]:
    terms = [text, re.split(r"[（(]", text)[0].strip()]
    terms += [part.strip() for part in HEADING_SPLIT_RE.split(text)]
    return list(dict.fromkeys(t for t in terms if len(t) >= 2))


def json_keys(value: object, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    keys: set[tuple[str, ...]] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            keys.add(prefix + (k,))
            keys |= json_keys(v, prefix + (k,))
    return keys


def class_attributes(text: str | None) -> dict[str, set[str]]:
    """クラスごとの本体で宣言した属性（設定の項目・モデルのフィールド等）。字下げした行は形だけでは関数の中の変数と見分けられない。"""
    try:
        tree = ast.parse(text or "")
    except SyntaxError:
        return {}
    return {node.name: {target.id for stmt in node.body
                        for target in ([stmt.target] if isinstance(stmt, ast.AnnAssign)
                                       else stmt.targets if isinstance(stmt, ast.Assign) else [])
                        if isinstance(target, ast.Name) and not target.id.startswith("__")}
            for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def removed_names(mb: str, head: str, diff: dict[str, tuple[list[str], list[str]]]
                  ) -> list[tuple[str, str, list[str]]]:
    """消した・名前を変えた名前を (種類, 名前, 探す語) で。"""
    names: list[tuple[str, str, list[str]]] = []
    surviving = files_at(head)
    status = git("diff", "-M", "--name-status", mb, head, "--", ".", ":(exclude)docs/records")
    for line in status.splitlines():
        cols = line.split("\t")
        if cols[0].startswith(("D", "R")):
            names.append(("ファイル", cols[1], [search_key(cols[1], surviving)]))

    head_headings = [m.group(1) for line in git(
        "grep", "-h", "-E", "^#{1,6} ", head, "--", "*.md", ":(exclude)docs/records",
        check=False).splitlines() if (m := HEADING_RE.match(line))]
    added_headings = {m.group(1) for removed, added in diff.values() for line in added
                      if (m := HEADING_RE.match(line))}
    for path, (removed, _) in diff.items():
        if not path.endswith(".md"):
            continue
        for line in removed:
            m = HEADING_RE.match(line)
            if not m or m.group(1) in added_headings:
                continue
            terms = [t for t in heading_terms(m.group(1))
                     if not any(t in h for h in head_headings)]
            if terms:
                names.append(("見出し", f"{path}「{m.group(1)}」", terms))

    for path in diff:
        if not path.endswith(".json") or path.startswith(GENERATED_PREFIXES) \
                or path.endswith(GENERATED_NAMES):
            continue
        try:
            before = json_keys(json.loads(show(mb, path) or "null"))
            after = json_keys(json.loads(show(head, path) or "null"))
        except json.JSONDecodeError:
            continue
        gone = before - after
        for key in sorted(k for k in gone if k[:-1] not in gone):
            names.append(("設定の項目", f"{path}: {'.'.join(key)}", [key[-1]]))

    defined = {path: ({m.group(1) for line in removed for r in DEFINITION_RES if (m := r.match(line))},
                      {m.group(1) for line in added for r in DEFINITION_RES if (m := r.match(line))})
               for path, (removed, added) in diff.items() if path.endswith(CODE_SUFFIXES + (".js", ".mjs"))}
    for path, (removed_defs, added_defs) in defined.items():
        if path.endswith(".py"):
            old_classes, new_classes = class_attributes(show(mb, path)), class_attributes(show(head, path))
            # 消したクラスの属性は、クラスの名前が候補に出るので数えない。
            removed_defs.update(*(attrs - new_classes[name] for name, attrs in old_classes.items()
                                  if name in new_classes))
            added_defs.update(*(attrs - old_classes.get(name, set()) for name, attrs in new_classes.items()))
    added_anywhere = set().union(*(a for _, a in defined.values()))
    candidates = {name: path for path, (r, _) in defined.items() for name in r - added_anywhere}
    # 別のファイルにある同じ名前は別の定義なので、残っているかは消したファイルの今の版だけで見る。
    head_texts = {path: show(head, path) or "" for path in set(candidates.values())}
    for name, path in sorted(candidates.items()):
        if not re.search(rf"\b(?:def|class|function|const|let|var|type|interface|enum)\s+{name}\b"
                         rf"|^{name}\s*[:=]", head_texts[path], re.MULTILINE):
            names.append(("定義", f"{path}: {name}", [name]))
    return names


def grep_terms(head: str, terms: set[str]) -> list[tuple[str, str]]:
    """語を含む行を (場所, 行)。識別子は語の切れ目で、ほかは部分一致で探す。"""
    hits: list[tuple[str, str]] = []
    for words, flags in ((sorted(t for t in terms if IDENTIFIER_RE.match(t)), ["-w"]),
                         (sorted(t for t in terms if not IDENTIFIER_RE.match(t)), [])):
        if not words:
            continue
        args = ["grep", "-n", "-I", "-F", *flags]
        for w in words:
            args += ["-e", w]
        out = git(*args, head, "--", ".", ":(exclude)docs/records", check=False)
        for line in out.splitlines():
            _, path, lineno, text = line.split(":", 3)
            hits.append((f"{path}:{lineno}", text))
    return hits


def read_tasks_repo(repo: str) -> tuple[list[dict] | None, list[dict] | None]:
    """置き場のラベルと開いた issue（本文とコメント）。読めなければ None（`GH_TOKEN`が要る）。"""
    def gh(*args: str) -> list[dict] | None:
        result = subprocess.run(["gh", *args, "-R", repo], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=False)
        return json.loads(result.stdout) if result.returncode == 0 else None
    try:
        return (gh("label", "list", "--json", "name,description", "--limit", "500"),
                gh("issue", "list", "--state", "open", "--json", "number,title,body,comments", "--limit", "500"))
    except (OSError, json.JSONDecodeError):
        return None, None


def term_matches(term: str, text: str) -> bool:
    if IDENTIFIER_RE.match(term):
        return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None
    return term in text


def excerpt(text: str, term: str, width: int = 60) -> str:
    i = max(text.find(term), 0)
    start = max(i - width // 2, 0)
    return ("…" if start else "") + text[start:start + width + len(term)].strip() + \
        ("…" if start + width + len(term) < len(text) else "")


def cmd_leftovers(args: argparse.Namespace) -> int:
    head = git("rev-parse", args.head).strip()
    mb = merge_base(args.base, head)
    diff = diff_lines(mb, head)
    names = removed_names(mb, head, diff)
    terms = {t for _, _, ts in names for t in ts}

    print(f"## 撤去・改名の取り残し（{mb[:8]}..{head[:8]}）")
    print("出たものは候補で、判定ではない。1件ずつ「直した」か「別の意味なので残す」かを決める。\n")
    print(f"### 消した・名前を変えた名前: {len(names)}件")
    for kind, name, ts in names:
        print(f"- {kind} {name}（探した語: {'・'.join(ts)}）")

    found: list[str] = []
    for where, text in grep_terms(head, terms):
        matched = [t for t in sorted(terms, key=len, reverse=True) if term_matches(t, text)]
        if matched:
            found.append(f"{where}: 「{matched[0]}」 {excerpt(text, matched[0])}")

    config_text = show(head, TASKS_CONFIG)
    config = json.loads(config_text) if config_text else {}
    repo = config.get("repository") if isinstance(config, dict) else None
    labels, issues = read_tasks_repo(repo) if repo else (None, None)
    unread = []
    if labels is None:
        unread.append("ラベル")
    if issues is None:
        unread.append("開いた issue")
    for label in labels or []:
        for t in sorted(terms, key=len, reverse=True):
            if term_matches(t, label.get("description") or ""):
                found.append(f"置き場のラベル「{label['name']}」の説明: 「{t}」 "
                             f"{excerpt(label['description'], t)}")
                break
    for issue in issues or []:
        texts = [("本文", issue.get("body"))] + [
            (f"コメント {c.get('url', '')}", c.get("body")) for c in issue.get("comments") or []]
        for where, body in texts:
            for lineno, text in enumerate((body or "").splitlines(), 1):
                matched = [t for t in sorted(terms, key=len, reverse=True) if term_matches(t, text)]
                if matched:
                    found.append(f"置き場 #{issue['number']} の{where} {lineno}行目: 「{matched[0]}」 "
                                 f"{excerpt(text, matched[0])}")

    print(f"\n### 名前が当たった所: {len(found)}件")
    for line in found:
        print(f"- {line}")

    added_text = {line.strip() for _, added in diff.values() for line in added}
    comments = [f"{path}: {line.strip()}" for path, (removed, _) in diff.items()
                if path.endswith(COMMENT_SUFFIXES) and not path.startswith(GENERATED_PREFIXES)
                for line in removed
                if COMMENT_RE.match(line) and line.strip() not in added_text
                and line.strip() not in ("#", "//", "*", "/*", "*/")]
    print(f"\n### 消したコメント行（docs/conventions/comments.md の判定木に通す）: {len(comments)}件")
    for line in comments:
        print(f"- {line}")

    mentioned: dict[str, str] = {}
    def config_labels(value: object, path: str) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k.endswith("Label") and isinstance(v, str):
                    mentioned.setdefault(v, f"{TASKS_CONFIG}: {path}{k}")
                config_labels(v, f"{path}{k}.")
    config_labels(config, "")
    for line in git("grep", "-n", "-E", "ラベル", head, "--", "*.md", ":(exclude)docs/records",
                    check=False).splitlines():
        _, md, at, text = line.split(":", 3)
        for name in LABEL_MENTION_RE.findall(text):
            if not PLACEHOLDER_RE.search(name):
                mentioned.setdefault(name, f"{md}:{at}")
    if labels is not None:
        existing = {label["name"] for label in labels}
        missing = [f"「{name}」（{where}）" for name, where in mentioned.items() if name not in existing]
        print(f"\n### 名指しているのに置き場（{repo}）に無いラベル: {len(missing)}件")
        for line in missing:
            print(f"- {line}")
    if unread:
        print(f"\n（置き場の{'・'.join(unread)}を読めなかった。`GH_TOKEN`に置き場を読めるトークンを渡して打ち直す）")
    return 0


def change_kind(path: str) -> str:
    """変更の行数を分ける種別。規模の札は実装とテストだけで決まる（CLAUDE.md「規模の札」）。"""
    if path.startswith(GENERATED_PREFIXES) or path.endswith(GENERATED_NAMES):
        return "生成物"
    if path.endswith(".md"):
        return "文書"
    if is_test(path):
        return "テスト"
    if path.startswith((".github/", ".claude/")):
        return "設定"
    return "実装"


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
    p = sub.add_parser("leftovers", help="撤去・改名の取り残しの候補")
    p.add_argument("--base", default="origin/master", help="比べる相手（合流点から見る）")
    p.add_argument("--head", default="HEAD", help="見る版")
    p.set_defaults(func=cmd_leftovers, measures_head=False)
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
