"""`scripts/new_task.py`が、ダッシュボードで承認された起票案があるときだけ番号を振るか（一時的なgitリポジトリで動かす）。

new_task.py はスクリプトの置き場のリポジトリのorigin/masterへpushするので、スクリプトと道具（`scripts/orchestration/`）を
一時的なリポジトリへ写して動かす。承認は最新のダッシュボードの書き出し（`<ORCH_DIR>/pending-backup/<日付>.json`）から読む。
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
PLAN = "# 台帳\n\n## 節A\n\n- [ ] [T5](records/tasks/T5.md). 既にあるタスク 規模S\n"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.com")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    origin, main, orch = tmp_path / "origin.git", tmp_path / "main", tmp_path / "orch"
    git(tmp_path, "init", "--quiet", "--bare", "-b", "master", str(origin))
    git(tmp_path, "clone", "--quiet", str(origin), str(main))
    git(main, "switch", "--quiet", "-c", "master")
    (main / "docs" / "records" / "tasks").mkdir(parents=True)
    (main / "docs" / "improvement-plan.md").write_text(PLAN, encoding="utf-8")
    (main / "docs" / "records" / "tasks" / "T5.md").write_text("# T5. 既にあるタスク\n\n状態: 未完了\n", encoding="utf-8")
    git(main, "add", "docs")
    git(main, "commit", "--quiet", "-m", "T0: 土台")
    git(main, "push", "--quiet", "origin", "master")
    (main / "scripts").mkdir()
    shutil.copy(SCRIPTS / "new_task.py", main / "scripts" / "new_task.py")
    shutil.copytree(SCRIPTS / "orchestration", main / "scripts" / "orchestration",
                    ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setenv("ORCH_DIR", str(orch))
    return main, orch, origin


def backup(orch: Path, items: dict) -> None:
    (orch / "pending-backup").mkdir(parents=True, exist_ok=True)
    (orch / "pending-backup" / "2026-09-26.json").write_text(
        json.dumps({"saved_at": "2026-09-26T20:00:00+09:00", "items": items}, ensure_ascii=False), encoding="utf-8")


def new_task(main: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(main / "scripts" / "new_task.py"), *args], cwd=main,
                          capture_output=True, text=True, encoding="utf-8", check=False, env=os.environ.copy())


def master_files(origin: Path) -> list[str]:
    return git(origin, "ls-tree", "-r", "--name-only", "master").splitlines()


PROPOSAL = {"kind": "起票案", "task": "", "text": "新しいタスク", "answer": "承認（2026-09-26）"}


def test_approved_proposal_gets_the_next_number(world):
    main, orch, origin = world
    backup(orch, {"proposal-new": PROPOSAL})

    done = new_task(main, "新しいタスク", "--section", "節A", "--size", "S", "--proposal", "proposal-new")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "docs/records/tasks/T6.md" in master_files(origin)
    assert "proposal-new" in done.stdout


@pytest.mark.parametrize("items", [
    {},
    {"proposal-new": {**PROPOSAL, "answer": ""}},
    {"proposal-new": {**PROPOSAL, "answer": "見送り（2026-09-26）"}},
    {"proposal-new": {**PROPOSAL, "kind": "改善案"}},
], ids=["起票案が無い", "答えが無い", "見送り", "起票案ではない"])
def test_number_is_not_given_without_an_approved_proposal(world, items):
    main, orch, origin = world
    backup(orch, items)
    before = master_files(origin)

    done = new_task(main, "新しいタスク", "--section", "節A", "--size", "S", "--proposal", "proposal-new")

    assert done.returncode == 1, done.stdout + done.stderr
    assert "proposal-new" in done.stderr
    assert master_files(origin) == before


def test_number_is_not_given_without_a_dashboard_backup(world):
    main, orch, origin = world
    before = master_files(origin)

    done = new_task(main, "新しいタスク", "--section", "節A", "--size", "S", "--proposal", "proposal-new")

    assert done.returncode == 1
    assert "書き出し" in done.stderr
    assert master_files(origin) == before
