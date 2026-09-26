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


def slot(main: Path, n: int, owner: str) -> Path:
    """スロットnを作り、渡した印（`slot <渡し先> <時刻>`）を付ける。"""
    path = main / ".claude" / "worktrees" / f"slot-{n}"
    git(main, "worktree", "add", "--quiet", "-B", f"slot-{n}", str(path), "origin/master")
    git(main, "worktree", "lock", "--reason", f"slot {owner} {ago(1)}", str(path))
    return path


def lock_reason(main: Path, path: Path) -> str | None:
    for block in git(main, "worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines())
        if Path(fields.get("worktree", "")).resolve() == path.resolve():
            return fields.get("locked")
    raise AssertionError(f"作業ツリーに無い: {path}")


def test_sha_made_only_of_digits_is_kept_as_written(world):
    main, orch = world
    assert orchestrate(main, orch, "board", "add", "A", "current_task=T1").returncode == 0

    done = orchestrate(main, orch, "board", "set", "A", "state=停止済み", "reported_sha=447131473413", "audit_base=12e45678")

    assert done.returncode == 0, done.stderr
    agent = load(orch)["agents"][0]
    assert (agent["reported_sha"], agent["audit_base"]) == ("447131473413", "12e45678")


def test_audit_log_mistake_is_fixed_only_with_a_commit_that_exists(world):
    main, orch = world
    board = load(orch)
    board["agents"] = [{"name": "A", "state": "停止済み", "audit_log": [
        {"task": "T1", "reported_sha": "1234567", "audit_base": "78964a5bxxxx", "audit_result": "通す"}]}]
    save(orch, board)
    real = git(main, "rev-parse", "--short=12", "HEAD")

    bogus = orchestrate(main, orch, "board", "audit-fix", "A", "1", "audit_base=78964a5bffff")
    fixed = orchestrate(main, orch, "board", "audit-fix", "A", "1", f"audit_base={real}")

    assert bogus.returncode != 0 and "引けない" in bogus.stderr, bogus.stdout + bogus.stderr
    assert fixed.returncode == 0, fixed.stderr
    assert load(orch)["agents"][0]["audit_log"][0]["audit_base"] == real
    assert "1. " in orchestrate(main, orch, "board", "audit-fix", "A").stdout


def test_passing_the_audit_before_the_report_still_stops_the_agent_and_frees_its_slot(world):
    main, orch = world
    path = slot(main, 1, "agent-a1")
    assert orchestrate(main, orch, "board", "add", "A", "current_task=T1", "id=a1").returncode == 0

    passed = orchestrate(main, orch, "board", "set", "A", "audit_done=now", "audit_result=通す")

    assert passed.returncode == 0, passed.stderr
    assert load(orch)["agents"][0]["state"] == "停止済み"
    assert lock_reason(main, path) is None, passed.stdout


def test_gate_stays_open_for_an_audit_wait_until_no_slot_is_left(world):
    main, orch = world
    board = load(orch)
    board["limits"] = {"concurrent": 2}
    board["agents"] = [{"name": "B", "id": "b1", "state": "停止済み", "current_task": "T1", "reported_sha": "1234567"}]
    save(orch, board)
    slot(main, 1, "agent-b1")

    one_free = gate_output(main, orch)

    assert "監査待ち" not in one_free and "空いているスロットが無い" not in one_free, one_free

    board["agents"].append({"name": "C", "id": "c1", "state": "停止済み", "current_task": "T1", "reported_sha": "1234567"})
    save(orch, board)
    slot(main, 2, "agent-c1")

    assert "空いているスロットが無い: slot-1（監査待ち B）、slot-2（監査待ち C）" in gate_output(main, orch)


def test_idle_slot_with_waiting_dispatch_is_raised_after_five_minutes_even_with_the_gate_closed(world):
    main, orch = world
    assert orchestrate(main, orch, "board", "dispatch", "push", "T1").returncode == 0

    first = orchestrate(main, orch, "check", "--record")

    assert "続いている" not in first.stdout, first.stdout
    assert int((orch / "next_check").read_text()) <= dt.datetime.now().timestamp() + 5 * 60 + 5
    board = load(orch)
    assert board["idle_since"]
    board["idle_since"] = ago(6)
    save(orch, board)
    (orch / "STOP").write_text("", encoding="utf-8")

    later = orchestrate(main, orch, "check").stdout

    assert "稼働が上限未満（0本 / 上限3本）で振り出し待ち1件がある状態が" in later, later
    assert "6分続いている（門: " in later and "停止ファイル" in later


def test_check_says_which_dashboard_dump_it_read_and_when_that_is_stale(world):
    main, orch = world
    backup = orch / "pending-backup"
    backup.mkdir()
    item = {"task": "T1", "kind": "保留", "text": "コメントで答えた問い",
            "comments": [{"text": "半分だけ残す", "at": ago(200)}]}

    def check_with_dump(minutes: int) -> str:
        day = dt.date.today().isoformat()
        (backup / f"{day}.json").write_text(json.dumps({"saved_at": ago(minutes), "items": {"T1-q": item}},
                                                       ensure_ascii=False), encoding="utf-8")
        return orchestrate(main, orch, "check").stdout

    fresh, stale = check_with_dump(1), check_with_dump(120)

    assert "確認中1件 → " in fresh and "（1分前）の書き出し）" in fresh, fresh
    assert "古い" not in fresh
    assert "（120分前）の書き出し。古いので書き出し直してから扱う" in stale, stale
    assert "既に消えているかもしれない" in stale


def test_rules_prints_the_block_of_the_convention_with_the_agent_name(world):
    main, orch = world
    convention = Path(__file__).resolve().parents[2] / "docs" / "conventions" / "orchestration.md"
    write(main, "docs/conventions/orchestration.md", convention.read_text(encoding="utf-8"))
    git(main, "add", "docs")
    git(main, "commit", "--quiet", "-m", "T0: 規約")
    git(main, "push", "--quiet", "origin", "master")

    rules = orchestrate(main, orch, "rules", "K-x")

    assert rules.returncode == 0, rules.stderr
    lines = rules.stdout.splitlines()
    assert 1 <= len(lines) <= 10 and all(line.startswith("- ") for line in lines), rules.stdout
    assert "orch/K-x" in rules.stdout and "<名前>" not in rules.stdout
