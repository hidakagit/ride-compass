"""担当の所要の行（`所要（並行実行）:`）へ、CI待ちを監査のときにGitHubから取って書き足す（規約
docs/conventions/orchestration.md「完了とpush」の所要の行）。監査（`audit`）が書き足した行を出し、司令塔が
取り込みの枝でcherry-pickの後に`effort-ci`を打ち、書き足しのコミットを作る（`board unpushed`が出す手順に入っている）。

- 完了のコミット（報告のsha）のCIは、担当がコミットした後に結論が出るので担当には書けない。その
  ワークフローの実行の作成から結論まで（全ワークフローのうち最も早い作成〜最も遅い更新）を、行の末尾へ
  `完了のコミットのCI N分（…）`として足す。予算の計算（`core.parse_effort`）は、この分を実時間と
  CI待ちの両方へ足す（完了の時刻の後の時間なので、行の「うち」には入っていない）。
- 担当がCI待ちを数で書けなかったとき（「不明」等）は、依頼の時刻から完了のコミットのCIの作成までに
  作業ブランチ`orch/<名前>`で作られたCIの実行の区間の和で置き換える（CI待ちの定義「pushからCIの
  結論まで」と同じ量）。依頼の時刻が読めなければ置き換えない。数で書かれていれば担当の値を残す。
- GitHubへの問い合わせは、報告のshaの実行（監査が既に持つ）と、置き換えが要るときだけ作業ブランチの
  実行の一覧1回。

    python scripts/orchestrate.py effort-ci <名前> <sha> [--base <基点>]   # 作業ツリーのTxxx.mdへ書いてコミットする
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

from orchestration import core, github

#: 監査が足す欄。`core.EFFORT_CI_RE`（`CI待ちN分`）に拾われない綴りにする。
AFTER_CI_LABEL = "完了のコミットのCI"
AFTER_CI_RE = re.compile(AFTER_CI_LABEL + r"\s*約?(\d+)分")
CI_NUMBER_RE = re.compile(r"CI待ち約?\d+分")
#: 担当が数で書けなかったCI待ち（「CI待ち不明」「CI待ちはこのコミットの後（不明）」等）。
CI_UNKNOWN_RE = re.compile(r"CI待ち(?!約?\d+分)[^、。\n]*")
REQUEST_RE = re.compile(r"依頼 (\d{4}-\d{2}-\d{2}) (\d{1,2}):(\d{2})")
BRANCH_LISTING = 100
#: 所要の行の時刻は日本時間で書く（規約「完了とpush」）。
JST = dt.timezone(dt.timedelta(hours=9))


def _time(value: object) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _minutes(seconds: float) -> int:
    return round(seconds / 60)


def _clock(t: dt.datetime) -> str:
    return t.astimezone(JST).strftime("%H:%M")


def run_span(runs: list[dict]) -> tuple[dt.datetime, dt.datetime] | None:
    """実行の群の（最も早い作成、最も遅い更新＝結論）。未完了・時刻の欠けがあればNone。"""
    if not runs or any(r.get("status") != "completed" for r in runs):
        return None
    starts = [_time(r.get("created_at")) for r in runs]
    ends = [_time(r.get("updated_at")) for r in runs]
    if None in starts or None in ends:
        return None
    return min(starts), max(ends)


def union_seconds(spans: list[tuple[dt.datetime, dt.datetime]]) -> float:
    total, cur_start, cur_end = 0.0, None, None
    for start, end in sorted(spans):
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        total += (cur_end - cur_start).total_seconds()
    return total


def request_time(line: str) -> dt.datetime | None:
    m = REQUEST_RE.search(line)
    if not m:
        return None
    return dt.datetime.strptime(f"{m.group(1)} {int(m.group(2)):02d}:{m.group(3)} +0900", "%Y-%m-%d %H:%M %z")


def before_ci_seconds(branch_runs: list[dict], sha: str, since: dt.datetime, until: dt.datetime) -> float:
    """依頼の時刻から完了のコミットのCIの作成までに作られた、作業ブランチの他のコミットのCIの区間の和。"""
    spans = []
    for run in branch_runs:
        start, end = _time(run.get("created_at")), _time(run.get("updated_at"))
        if run.get("head_sha") == sha or start is None or end is None or run.get("status") != "completed":
            continue
        if since <= start < until:
            spans.append((start, min(end, until)))
    return union_seconds(spans)


def filled_line(line: str, sha_runs: list[dict], branch_runs: list[dict] | None, sha: str) -> tuple[str | None, str]:
    """(書き足した行、理由)。書き足せなければ行はNoneで、理由に何が足りないかを書く。"""
    if AFTER_CI_RE.search(line):
        return None, "既に書き足してある"
    span = run_span(sha_runs)
    if span is None:
        return None, "報告のshaのCIが完了していない（実行が無い・結論待ち）"
    start, end = span
    new = line
    note = ""
    if not CI_NUMBER_RE.search(line) and (unknown := CI_UNKNOWN_RE.search(line)):
        since = request_time(line)
        if since is None:
            note = "（依頼の時刻が読めないので、担当のCI待ちは置き換えない）"
        elif branch_runs is None:
            note = "（作業ブランチの実行を取得できないので、担当のCI待ちは置き換えない）"
        else:
            before = _minutes(before_ci_seconds(branch_runs, sha, since, start))
            new = new[:unknown.start()] + f"CI待ち{before}分" + new[unknown.end():]
    after = _minutes((end - start).total_seconds())
    new = new.rstrip().rstrip("。") + f"。{AFTER_CI_LABEL} {after}分（監査で追記: 作成 {_clock(start)} → 結論 {_clock(end)}）"
    return new, note


def added_effort_lines(repo: Path, base: str, sha: str) -> list[tuple[str, str]]:
    """範囲base..shaで足された・書き換えられた所要の行（(タスク記録のパス, 行)）。"""
    names = core.git_out(repo, "diff", "--name-only", "--no-renames", base, sha, "--", core.TASKS_DIR) or ""
    found = []
    for path in names.split():
        if not core.TASK_DOC_RE.match(path):
            continue
        diff = core.git_out(repo, "diff", "-U0", base, sha, "--", path) or ""
        found += [(path, text[1:]) for text in diff.splitlines()
                  if text.startswith("+" + core.EFFORT_PREFIX)]
    return found


def branch_runs_of(name: str) -> list[dict] | None:
    runs, _ = github.actions_runs(f"branch=orch/{name}&per_page={BRANCH_LISTING}")
    return runs


def proposals(repo: Path, name: str, base: str, sha: str,
              sha_runs: list[dict]) -> list[tuple[str, str, str | None, str]]:
    """(パス, 元の行, 書き足した行またはNone, 理由)。作業ブランチの一覧は置き換えが要るときだけ取る。"""
    lines = added_effort_lines(repo, base, sha)
    need_branch = any(not CI_NUMBER_RE.search(t) and CI_UNKNOWN_RE.search(t) for _, t in lines)
    branch_runs = branch_runs_of(name) if need_branch else []
    return [(path, text, *filled_line(text, sha_runs, branch_runs, sha)) for path, text in lines]


def print_proposals(items: list[tuple[str, str, str | None, str]], name: str, sha: str, base: str) -> None:
    """監査の出力の節。"""
    print("\n所要の行のCI待ち（完了のコミットのCIを書き足す。司令塔が取り込みの枝で書き、取り込みと同じpushに含める）")
    if not items:
        print("  範囲に所要の行の追加が無い（担当が所要の行を残したか、項目2と併せて見る）")
        return
    for path, old, new, note in items:
        if new is None:
            print(f"  {path}: 書き足さない（{note}）")
            continue
        print(f"  {path}{note}\n    - {old}\n    + {new}")
    if any(new for _, _, new, _ in items):
        print(f"  書く: python scripts/orchestrate.py effort-ci {name} {sha[:12]} --base {base[:12]}"
              "  （取り込みの枝でcherry-pickの後に打つ。board unpushed の手順に入っている）")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py effort-ci",
                                     description="所要の行へ完了のコミットのCIを書き足してコミットする")
    parser.add_argument("--repo", default=str(core.REPO_ROOT))
    parser.add_argument("name")
    parser.add_argument("sha")
    parser.add_argument("--base", default="origin/master", help="比較の基点（分岐点を取る）")
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    sha = core.git_out(repo, "rev-parse", "--verify", f"{args.sha}^{{commit}}")
    base = core.git_out(repo, "merge-base", args.base, sha) if sha else None
    if not sha or not base:
        print("コミットか基点が見つかりません")
        return 2
    _, latest = core.ci_verdicts(sha)
    items = proposals(repo, args.name, base, sha, latest)
    # 書き足せない行は飛ばして0で返す（取り込みの手順の連結を、所要の行の書き足しだけで止めない）。
    written: list[str] = []
    for path, old, new, note in items:
        if new is None:
            print(f"{path}: 書き足さない（{note}）")
            continue
        target = repo / path
        text = target.read_text(encoding="utf-8")
        if old not in text:
            print(f"{path}: 作業ツリーのファイルに元の行が無いので書き足さない（取り込みの枝で打つ）")
            continue
        target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")
        written.append(path)
        print(f"{path}: {new}")
    if not written:
        print("書き足した行は無い")
        return 0
    tasks = "・".join(m.group(1) for p in written if (m := core.TASK_DOC_RE.match(p)))
    message = (f"所要の行へ、完了のコミットのCIを書き足す（{tasks}）\n\n"
               f"python scripts/orchestrate.py effort-ci {args.name} {sha[:12]} --base {base[:12]} が、"
               f"GitHubのCIの実行から書き足した。\n")
    r = core.git(repo, "commit", "-q", "-m", message, "--", *written)
    if r is None or r.returncode != 0:
        print("コミットに失敗した: " + (r.stderr.decode("utf-8", errors="replace").strip() if r else "git未応答"))
        return 1
    print(f"{len(written)}件を書き足してコミットした: {tasks}")
    return 0

