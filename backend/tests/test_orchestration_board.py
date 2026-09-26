"""`scripts/orchestrate.py`の門（見込み超過の是正済みの印）と振り出し待ち（後始末の印）を、一時的なgitリポジトリで
入口のコマンドから確かめる。

台帳・記録はorigin/masterから読まれるので、一時的なリポジトリのmasterに台帳の行と記録を置いてpushする。状態の表は
`--dir`で一時的なディレクトリへ向け、実物の表に触れない。
"""

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parents[2] / "scripts" / "orchestrate.py"
PLAN = "# 台帳\n\n## 節A\n\n- [ ] [T1](records/tasks/T1.md). 走っているタスク 規模S\n"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ago(minutes: int) -> str:
    return (dt.datetime.now().astimezone() - dt.timedelta(minutes=minutes)).isoformat(timespec="minutes")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """masterに台帳（T1は規模S・未完了）と記録（T2は完了）を置き、回の母集団をT1・T2にした表。
    所要の実績が無いので、規模Sの予算は規模札の定義の60分になる。"""
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.com")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    origin, main, orch = tmp_path / "origin.git", tmp_path / "main", tmp_path / "orch"
    git(tmp_path, "init", "--quiet", "--bare", "-b", "master", str(origin))
    git(tmp_path, "clone", "--quiet", str(origin), str(main))
    git(main, "switch", "--quiet", "-c", "master")
    write(main, "docs/improvement-plan.md", PLAN)
    write(main, "docs/records/tasks/T1.md", "# T1. 走っているタスク\n\n状態: 未完了\n")
    write(main, "docs/records/tasks/T2.md", "# T2. 閉じたタスク\n\n状態: 完了\n")
    git(main, "add", "docs")
    git(main, "commit", "--quiet", "-m", "T0: 土台")
    git(main, "push", "--quiet", "origin", "master")
    orch.mkdir()
    save(orch, {"limits": {"concurrent": 3}, "agents": [],
                "run": {"name": "試験", "population": [{"task": "T1"}, {"task": "T2"}]}})
    return main, orch


def save(orch: Path, board: dict) -> None:
    (orch / "board.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")


def load(orch: Path) -> dict:
    return json.loads((orch / "board.json").read_text(encoding="utf-8"))


def orchestrate(main: Path, orch: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ENTRY), "--repo", str(main), "--dir", str(orch), *args],
                          cwd=main, capture_output=True, text=True, encoding="utf-8", check=False)


def overran(main: Path, orch: Path, **agent) -> None:
    """担当AがT1（規模S、予算60分）を90分前に始めていて、見込みを超えている表。"""
    board = load(orch)
    board["agents"] = [{"name": "A", "state": "稼働", "current_task": "T1", "task_first_started": ago(90), **agent}]
    save(orch, board)


def gate_output(main: Path, orch: Path) -> str:
    gated = orchestrate(main, orch, "gate")
    return gated.stdout + gated.stderr


def test_gate_stays_closed_by_an_overrun_until_it_is_marked_corrected(world):
    main, orch = world
    overran(main, orch)
    assert "見込み超過がある: A: T1の着手から通算90分 / 規模の予算60分" in gate_output(main, orch)

    marked = orchestrate(main, orch, "board", "set", "A", "overrun_ack=now")

    assert marked.returncode == 0, marked.stderr
    assert "見込み超過" not in gate_output(main, orch)


def test_corrected_mark_stops_counting_after_one_more_budget(world):
    main, orch = world
    overran(main, orch, overrun_ack=ago(61))

    assert "見込み超過がある: A: T1" in gate_output(main, orch)


def test_corrected_mark_from_before_the_task_started_does_not_count(world):
    main, orch = world
    overran(main, orch, overrun_ack=ago(95))

    assert "見込み超過がある: A: T1" in gate_output(main, orch)


def test_corrected_mark_is_dropped_when_the_agent_takes_the_next_task(world):
    main, orch = world
    overran(main, orch, overrun_ack=ago(1))

    assert orchestrate(main, orch, "board", "set", "A", "current_task=T3").returncode == 0

    assert "overrun_ack" not in load(orch)["agents"][0]


def test_finished_task_is_popped_from_the_dispatch_queue_only_with_the_cleanup_mark(world):
    main, orch = world
    assert orchestrate(main, orch, "board", "dispatch", "push", "T2").returncode == 0

    plain = orchestrate(main, orch, "board", "dispatch", "pop")

    assert plain.returncode != 0
    assert "取り出した" not in plain.stdout

    assert orchestrate(main, orch, "board", "dispatch", "push", "T2", "cleanup=true").returncode == 0
    listed = orchestrate(main, orch, "board", "dispatch", "list").stdout
    assert "後始末" in listed, listed

    popped = orchestrate(main, orch, "board", "dispatch", "pop")

    assert popped.returncode == 0, popped.stdout + popped.stderr
    assert '"cleanup": true' in popped.stdout
    assert [i.get("cleanup") for i in load(orch)["queue"]] == [None]
