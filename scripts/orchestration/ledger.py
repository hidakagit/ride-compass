"""台帳（`docs/improvement-plan.md`）とタスク記録（`docs/records/tasks/Txxx.md`）の書式の読み書き。

書式の正本はこのモジュールで、台帳・記録を読み書きする道具（核・`queue`・`pending`・`scripts/review_checks.py`・
`scripts/new_task.py`）はここから読む——置き場のパス、台帳の行の形とその行が指す記録、記録の`状態:`の解釈、
状態と台帳の行の食い違い、完了の判定、節への行の挿入、起票の行と記録の雛形。

- **完了は記録の`状態:`だけで決まる**（`DONE`）。台帳の行は記録の状態から導く写しで、取り込みのたびに
  下の`sync`が状態へ合わせる。行が残っているかで完了を割り引かない。
- 台帳の行は、行の番号ではなくリンク先で記録を引く（`T317`の2件目は`T317-2.md`を指す）。

取り込みの後始末（`python scripts/orchestrate.py ledger sync`。作業ツリーの台帳を直し、コミットしない）:
並行実行の担当は台帳の行に触らない——台帳は全担当が1行ずつ触る共有のファイルで、別々のブランチが隣り合った
行を変えると取り込み（cherry-pick）で衝突する。行は司令塔が取り込みのたびにこのコマンドで直し、取り込んだ
そのタスクのコミットへ畳む（規約「監査の結果」）。

- `状態: 完了`の記録を指す行を消す。
- `状態: 未完了`なのに行の無い記録（閉じたタスクの開け直し）は、最後に消されたときの行を、そのときの
  節の末尾へ戻す（行の文面と節はgitの履歴から取る）。戻せなければ、その旨を出して手で足させる。
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from orchestration.gitio import cat_files, git_out

PLAN_DOC = "docs/improvement-plan.md"
TASKS_DIR = "docs/records/tasks"
#: 台帳から見た記録の置き場（台帳の行のリンク先の頭）。
ROW_TARGET_DIR = TASKS_DIR.removeprefix(PLAN_DOC.rsplit("/", 1)[0] + "/") + "/"
TASK_ID = r"T\d+[a-z0-9-]*"
TASK_ID_RE = re.compile(TASK_ID)
#: リポジトリの根から見た記録のパス。
TASK_DOC_RE = re.compile(rf"^{re.escape(TASKS_DIR)}/({TASK_ID})\.md$")
#: 記録のファイル名（日付名の実施記録や索引と区別する）。
TASK_FILE_RE = re.compile(rf"^{TASK_ID}\.md$")
#: 台帳の1行（タスク番号・記録へのリンク先・題名以降）。
LEDGER_ROW_RE = re.compile(rf"^- \[ \] \[({TASK_ID})\]\(([^)]+)\)\.?\s*(.*)$")
ROW_TARGET_RE = re.compile(rf"^{re.escape(ROW_TARGET_DIR)}({TASK_ID})\.md$")
TASK_HEADING_RE = re.compile(rf"^# {TASK_ID}\.\s*(.*)$")
SCALE_LABEL_RE = re.compile(r"規模([SML])(?:〜([SML]))?")
#: 台帳の行で、着手の条件を待っている（ユーザーの判断で先送りした）ことを表す印。
TRIGGER_MARK = "— トリガー:"
STATE_PREFIX = "状態:"
#: `状態:`の2語。作業中の呼び分け（着手中・保留等）は本文へ書き、状態は片付いたかどうかだけを持つ。
DONE, OPEN = "完了", "未完了"

#: 記録の所要の行（規約「完了とpush」の書式）。
EFFORT_PREFIX = "所要（並行実行）"
EFFORT_REAL_RE = re.compile(r"完了[^（(]*[（(]約?(\d+)分")
EFFORT_FRAME_RE = re.compile(r"枠待ち約?(\d+)分")
EFFORT_CI_RE = re.compile(r"CI待ち約?(\d+)分")
EFFORT_SCALE_RE = re.compile(r"規模札([SML])(?:〜([SML]))?")
EFFORT_REASON_RE = re.compile(r"超過[:：]\s*([^、。）\n]+)")

#: 記録の状態と台帳の行の食い違い（`row_mismatch`の値）。
NO_RECORD = "記録が無い"
BAD_STATE = "状態行が「完了」「未完了」で始まっていない"
OPEN_WITHOUT_ROW = "未完了なのに台帳に行が無い"
DONE_WITH_ROW = "完了なのに台帳に行がある"


@dataclass(frozen=True)
class Row:
    #: 行が指す記録の番号（リンク先のファイル名から。記録を指していなければ行の番号）。
    task: str
    #: 台帳からの相対のリンク先。
    target: str
    #: 題名以降（規模札・着手の条件を含む）。
    title: str
    line: str
    #: 1始まりの行番号。
    lineno: int

    @property
    def scale(self) -> str | None:
        """規模札（「S〜M」のような幅は大きい側）。"""
        s = SCALE_LABEL_RE.search(self.title)
        return (s.group(2) or s.group(1)) if s else None


def rows(plan: str | None) -> list[Row]:
    out = []
    for lineno, line in enumerate((plan or "").splitlines(), 1):
        m = LEDGER_ROW_RE.match(line)
        if m:
            target = ROW_TARGET_RE.match(m.group(2))
            out.append(Row(target.group(1) if target else m.group(1), m.group(2), m.group(3).strip(), line, lineno))
    return out


def rows_by_task(plan: str | None) -> dict[str, Row]:
    return {r.task: r for r in rows(plan)}


def record_path(task: str) -> str:
    return f"{TASKS_DIR}/{task}.md"


def row_target(task: str) -> str:
    return f"{ROW_TARGET_DIR}{task}.md"


def task_state(text: str | None) -> str | None:
    """記録の`状態:`（`DONE`・`OPEN`）。記録が無ければNone、状態行が無ければ「状態行なし」、2語で始まらなければ
    その値の頭。"""
    if text is None:
        return None
    line = next((s for s in text.splitlines() if s.startswith(STATE_PREFIX)), None)
    if line is None:
        return "状態行なし"
    value = line[len(STATE_PREFIX):].strip()
    for word in (OPEN, DONE):
        if value.startswith(word):
            return word
    return value[:10]


def record_title(text: str | None) -> str | None:
    """記録の見出しの題名。"""
    m = TASK_HEADING_RE.match(text.splitlines()[0]) if text else None
    return m.group(1) if m else None


def row_mismatch(state: str | None, has_row: bool) -> str | None:
    """記録の状態と台帳の行の食い違い（このモジュールの定数のどれか）。無ければNone。"""
    if state is None:
        return NO_RECORD
    if state not in (DONE, OPEN):
        return BAD_STATE
    if state == OPEN and not has_row:
        return OPEN_WITHOUT_ROW
    if state == DONE and has_row:
        return DONE_WITH_ROW
    return None


def record_files(root: Path) -> list[Path]:
    """作業ツリーの記録（`root`はリポジトリの根）。"""
    return sorted(f for f in (root / TASKS_DIR).glob("*.md") if TASK_FILE_RE.match(f.name))


def plan_at(repo: Path, rev: str) -> str | None:
    return cat_files(repo, [f"{rev}:{PLAN_DOC}"])[f"{rev}:{PLAN_DOC}"]


def records_at(repo: Path, rev: str, tasks: list[str]) -> dict[str, str | None]:
    """`rev`のタスク記録の中身（無ければNone）。1回のgitの呼び出しで読む。"""
    texts = cat_files(repo, [f"{rev}:{record_path(t)}" for t in tasks])
    return {t: texts[f"{rev}:{record_path(t)}"] for t in tasks}


def done_tasks(repo: Path, tasks: list[str], rev: str = "origin/master") -> set[str]:
    """`rev`の記録で完了のもの。"""
    return {t for t, text in records_at(repo, rev, tasks).items() if task_state(text) == DONE}


def parse_effort(task: str, text: str) -> dict:
    """所要の1行を読む。読めない値はNone（「不明」も同じ）。`work`は実時間から枠待ち・CI待ちを引いた作業そのものの時間。"""
    def minutes_of(rx: re.Pattern) -> int | None:
        m = rx.search(text)
        return int(m.group(1)) if m else None

    s = EFFORT_SCALE_RE.search(text)
    real, frame, ci = minutes_of(EFFORT_REAL_RE), minutes_of(EFFORT_FRAME_RE), minutes_of(EFFORT_CI_RE)
    reason = EFFORT_REASON_RE.search(text)
    work = real - frame - ci if real is not None and frame is not None and ci is not None else None
    return {"task": task, "scale": (s.group(2) or s.group(1)) if s else None, "real": real, "work": work,
            "reason": reason.group(1).strip() if reason else None}


def effort_records(repo: Path, rev: str = "origin/master") -> list[dict]:
    """`rev`のタスク記録にある所要の行（1回のgit grepで取る）。"""
    out = git_out(repo, "grep", "--no-color", "-e", f"^{EFFORT_PREFIX}", rev, "--", f"{TASKS_DIR}/*.md") or ""
    records = []
    for line in out.splitlines():
        _, path, text = line.split(":", 2)
        m = TASK_DOC_RE.match(path)
        if m:
            records.append(parse_effort(m.group(1), text))
    return records


def find_section(plan: str, needle: str) -> tuple[int | None, list[str]]:
    """台帳の、needleを含む`## `見出しの行番号（0始まり）。一意でなければNoneと候補を返す。"""
    headings = [(i, line) for i, line in enumerate(plan.splitlines()) if line.startswith("## ")]
    hits = [(i, line) for i, line in headings if needle in line]
    if len(hits) == 1:
        return hits[0][0], []
    return None, [line for _, line in (hits or headings)]


def insert_row(plan: str, heading_index: int, row: str) -> str:
    """台帳の節の最後のタスク行の直後へ行を入れる。タスク行が無ければ見出しの直後へ。"""
    nl = "\r\n" if "\r\n" in plan else "\n"
    lines = plan.split(nl)
    end = next((i for i in range(heading_index + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    items = [i for i in range(heading_index + 1, end) if lines[i].startswith("- [")]
    if items:
        lines.insert(items[-1] + 1, row)
    else:
        lines[heading_index + 1:heading_index + 1] = ["", row]
    return nl.join(lines)


def new_row(task: str, title: str, size: str) -> str:
    """起票の台帳の行。"""
    return f"- [ ] [{task}]({row_target(task)}). {title} 規模{size}"


def new_record(task: str, title: str, day: str, background: str) -> str:
    """起票の記録の雛形。"""
    return (f"# {task}. {title}\n\n{STATE_PREFIX} {OPEN}（{day}起票）\n\n## 背景\n\n"
            + (f"{background.strip()}\n" if background.strip() else ""))


# ---------------------------------------------------------------- 取り込みの後始末（sync）


def removed_row(repo: Path, task: str) -> tuple[str, str] | None:
    """taskの記録を指す行が最後に消される直前の（節の見出し, 行）。履歴に無ければNone。"""
    commit = git_out(repo, "log", "-1", "--format=%H", "-S", f"]({row_target(task)})", "--", PLAN_DOC)
    before = git_out(repo, "show", f"{commit}^:{PLAN_DOC}") if commit else None
    heading = None
    for line in (before or "").splitlines():
        if line.startswith("## "):
            heading = line
        found = rows(line)
        if found and found[0].task == task and heading:
            return heading, line
    return None


def cmd_sync(repo: Path) -> int:
    path = repo / PLAN_DOC
    plan = path.read_bytes().decode("utf-8")
    listed = rows_by_task(plan)
    states = {f.stem: task_state(f.read_text(encoding="utf-8")) for f in record_files(repo)}
    closed = [r for task, r in listed.items() if states.get(task) == DONE]
    drop = {r.line for r in closed}
    new = "".join(line for line in plan.splitlines(keepends=True) if line.rstrip("\r\n") not in drop)
    restored, missing = [], []
    for task, state in states.items():
        if state != OPEN or task in listed:
            continue
        found = removed_row(repo, task)
        index = find_section(new, found[0][3:])[0] if found else None
        if found is None or index is None:
            missing.append(task)
            continue
        new = insert_row(new, index, found[1])
        restored.append(task)
    if new != plan:
        path.write_bytes(new.encode("utf-8"))
    print(f"消した行: {'・'.join(r.task for r in closed) or 'なし'}（状態が完了）")
    print(f"戻した行: {'・'.join(restored) or 'なし'}（状態が未完了で行が無い）")
    for task in missing:
        print(f"! {record_path(task)}: 未完了なのに台帳に行が無く、履歴から行を戻せない。台帳の節の末尾へ手で足す")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py ledger", description="台帳の行を記録の状態へ合わせる")
    parser.add_argument("--repo", default=".", help="台帳を直す作業ツリー（既定: 今のディレクトリ）")
    # 入口（orchestrate.py）は全体の引数をそのまま渡す。台帳は状態の表を読まないので、orchestrationディレクトリは使わない。
    parser.add_argument("--dir", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="状態が完了の行を消し、開け直したタスクの行を戻す（コミットしない）")
    args = parser.parse_args(argv)
    repo = Path(git_out(Path(args.repo), "rev-parse", "--show-toplevel") or args.repo)
    return cmd_sync(repo)
