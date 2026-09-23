"""台帳の行を記録の状態へ合わせる。取り込みの後始末で使う。

    python scripts/orchestrate.py ledger sync    # 作業ツリーの台帳を直す（コミットしない）

並行実行の担当は台帳（`docs/improvement-plan.md`）の行に触らない——台帳は全担当が1行ずつ触る共有の
ファイルで、別々のブランチが隣り合った行を変えると取り込み（cherry-pick）で衝突する。行は司令塔が
取り込みのたびにこのコマンドで直し、取り込んだそのタスクのコミットへ畳む（規約「監査の結果」）。

- `状態: 完了`の記録を指す行を消す。
- `状態: 未完了`なのに行の無い記録（閉じたタスクの開け直し）は、最後に消されたときの行を、そのときの
  節の末尾へ戻す（行の文面と節はgitの履歴から取る）。戻せなければ、その旨を出して手で足させる。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestration.core import (
    LEDGER_ROW_RE,
    PLAN_DOC,
    TASKS_DIR,
    find_section,
    git_out,
    insert_ledger_row,
    task_state,
)


def removed_row(repo: Path, target: str) -> tuple[str, str] | None:
    """リンク先targetを指す行が最後に消される直前の（節の見出し, 行）。履歴に無ければNone。"""
    commit = git_out(repo, "log", "-1", "--format=%H", "-S", f"]({target})", "--", PLAN_DOC)
    before = git_out(repo, "show", f"{commit}^:{PLAN_DOC}") if commit else None
    heading = None
    for line in (before or "").splitlines():
        if line.startswith("## "):
            heading = line
        m = LEDGER_ROW_RE.match(line)
        if m and m.group(2) == target and heading:
            return heading, line
    return None


def cmd_sync(repo: Path) -> int:
    path = repo / PLAN_DOC
    plan = path.read_bytes().decode("utf-8")
    base = PLAN_DOC.rsplit("/", 1)[0]
    rows = {m.group(2): (m.group(1), line) for line in plan.splitlines() if (m := LEDGER_ROW_RE.match(line))}
    states = {f"{TASKS_DIR.removeprefix(base + '/')}/{f.name}": task_state(f.read_text(encoding="utf-8"))
              for f in sorted((repo / TASKS_DIR).glob("T*.md"))}
    closed = [rows[t] for t in rows if states.get(t) == "完了"]
    drop = {line for _, line in closed}
    new = "".join(line for line in plan.splitlines(keepends=True) if line.rstrip("\r\n") not in drop)
    restored, missing = [], []
    for target, state in states.items():
        if state != "未完了" or target in rows:
            continue
        found = removed_row(repo, target)
        index = find_section(new, found[0][3:])[0] if found else None
        if index is None:
            missing.append(target)
            continue
        new = insert_ledger_row(new, index, found[1])
        restored.append(LEDGER_ROW_RE.match(found[1]).group(1))
    if new != plan:
        path.write_bytes(new.encode("utf-8"))
    print(f"消した行: {'・'.join(t for t, _ in closed) or 'なし'}（状態が完了）")
    print(f"戻した行: {'・'.join(restored) or 'なし'}（状態が未完了で行が無い）")
    for target in missing:
        print(f"! {target}: 未完了なのに台帳に行が無く、履歴から行を戻せない。台帳の節の末尾へ手で足す")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py ledger", description="台帳の行を記録の状態へ合わせる")
    parser.add_argument("--repo", default=".", help="台帳を直す作業ツリー（既定: 今のディレクトリ）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="状態が完了の行を消し、開け直したタスクの行を戻す（コミットしない）")
    args = parser.parse_args(argv)
    repo = Path(git_out(Path(args.repo), "rev-parse", "--show-toplevel") or args.repo)
    return cmd_sync(repo)
