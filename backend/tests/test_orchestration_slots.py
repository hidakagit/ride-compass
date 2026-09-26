"""`scripts/orchestrate.py slot`のスロットを渡し直すときの止まる条件（一時的なgitリポジトリで動かす）。

司令塔は担当のコミットを畳み直した別のコミットとしてmasterへ入れ、作業ブランチを消す。担当の元のコミットは
どのリモートの枝からも届かなくなるが、監査で通したタスクの番号から始まる件名のコミットが監査の後にmasterへ
入っていれば、スロットには失われるものが無い。規約の流れ（振り出し→担当のpush→監査で通す→取り込み→
作業ブランチの削除→次の担当の起動）を、入口のコマンドだけで辿る。
フックが起動役（`scripts/orchestration/launch.py`）を通して、本体の古い道具ではなくorigin/masterの版で渡すことも見る。
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parents[2] / "scripts" / "orchestrate.py"


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
    commit(main, "README.md", "土台\n", "T0: 土台")
    git(main, "push", "--quiet", "origin", "master")
    orch.mkdir()
    (orch / "board.json").write_text(json.dumps({"limits": {"concurrent": 1}, "agents": []}), encoding="utf-8")
    return main, orch


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def commit(cwd: Path, name: str, text: str, subject: str) -> str:
    (cwd / name).write_text(text, encoding="utf-8")
    git(cwd, "add", name)
    git(cwd, "commit", "--quiet", "-m", subject)
    return git(cwd, "rev-parse", "HEAD")


def orchestrate(main: Path, orch: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ENTRY), "--repo", str(main), "--dir", str(orch), *args],
                          cwd=main, input=stdin, capture_output=True, text=True, encoding="utf-8", check=False)


def hand_out(main: Path, orch: Path, agent_id: str) -> subprocess.CompletedProcess[str]:
    """WorktreeCreateフックと同じ入口でスロットを渡す。"""
    return orchestrate(main, orch, "slot", "hook-create", stdin=json.dumps({"name": f"agent-{agent_id}"}))


def work_and_pass_audit(main: Path, orch: Path) -> tuple[Path, str]:
    """担当S（T1）がスロットで1コミット作って作業ブランチへpushし、監査で通るまで。スロットと報告のsha。"""
    assert orchestrate(main, orch, "board", "add", "S", "current_task=T1", "id=s1").returncode == 0
    handed = hand_out(main, orch, "s1")
    assert handed.returncode == 0, handed.stderr
    slot = Path(handed.stdout.strip().splitlines()[-1])
    git(slot, "switch", "--quiet", "-c", "orch/S")
    sha = commit(slot, "feature.txt", "担当の成果\n", "T1: 担当の成果")
    git(slot, "push", "--quiet", "origin", f"+{sha}:refs/heads/orch/S")
    assert orchestrate(main, orch, "board", "set", "S", "state=停止済み", f"reported_sha={sha}").returncode == 0
    passed = orchestrate(main, orch, "board", "set", "S", "audit_done=now", "audit_result=通す")
    assert passed.returncode == 0 and "印を外した" in passed.stdout, passed.stdout + passed.stderr
    return slot, sha


def land(main: Path, sha: str) -> None:
    """司令塔の取り込み: 担当のコミットをcherry-pickして畳み直した別のコミットとしてmasterへ入れる。"""
    git(main, "cherry-pick", sha)
    git(main, "commit", "--quiet", "--amend", "-m", "T1: 担当の成果（台帳の行を畳んだ）")
    git(main, "push", "--quiet", "origin", "master")


def delete_work_branch(main: Path) -> None:
    git(main, "push", "--quiet", "origin", "--delete", "orch/S")


def test_slot_whose_only_stray_commits_landed_is_handed_out_again(world):
    main, orch = world
    slot, sha = work_and_pass_audit(main, orch)
    land(main, sha)
    delete_work_branch(main)

    handed = hand_out(main, orch, "next")

    assert handed.returncode == 0, handed.stderr
    assert os.path.samefile(handed.stdout.strip().splitlines()[-1], slot)
    assert git(slot, "rev-parse", "HEAD") == git(main, "rev-parse", "origin/master")


def test_slot_with_an_audited_commit_that_never_reached_master_is_kept(world):
    main, orch = world
    slot, _ = work_and_pass_audit(main, orch)
    delete_work_branch(main)

    handed = hand_out(main, orch, "next")

    assert handed.returncode != 0
    assert "pushしていない成果" in handed.stderr
    assert git(slot, "log", "-1", "--format=%s") == "T1: 担当の成果"


def test_slot_with_a_commit_after_the_landed_one_is_kept(world):
    main, orch = world
    slot, sha = work_and_pass_audit(main, orch)
    commit(slot, "later.txt", "監査の後に積んだ\n", "T1: 監査の後に積んだ")
    land(main, sha)
    delete_work_branch(main)

    handed = hand_out(main, orch, "next")

    assert handed.returncode != 0
    assert "pushしていない成果" in handed.stderr
    assert git(slot, "log", "-1", "--format=%s") == "T1: 監査の後に積んだ"


@pytest.fixture
def npm_world(world, tmp_path, monkeypatch):
    """frontend/package-lock.jsonを持つmasterと、呼ばれた回数を数える偽のnpm（外部のツールなので差し替える）。
    枠は持っている扱いにし（LOCKRUN_HELD）、試験が機械全体の枠を取らない。"""
    main, orch = world
    bin_dir, calls = tmp_path / "bin", tmp_path / "npm_calls.txt"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text('#!/bin/sh\necho "$*" >> "$NPM_CALLS"\nmkdir -p node_modules\n', encoding="utf-8", newline="\n")
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("NPM_CALLS", str(calls))
    monkeypatch.setenv("LOCKRUN_HELD", "heavy")
    commit(main, ".gitignore", "node_modules/\n", "T0: 依存は追わない")
    (main / "frontend").mkdir()
    commit(main, "frontend/package-lock.json", '{"v": 1}\n', "T0: 依存の版1")
    git(main, "push", "--quiet", "origin", "master")

    def npm_calls() -> int:
        return len(calls.read_text(encoding="utf-8").splitlines()) if calls.exists() else 0

    return main, orch, npm_calls


def change_lock_on_master(main: Path) -> None:
    commit(main, "frontend/package-lock.json", '{"v": 2}\n', "T2: 依存の版2")
    git(main, "push", "--quiet", "origin", "master")


def free_slot(main: Path, orch: Path, npm_calls) -> Path:
    """担当Aへ渡して（npm ciが1回走る）印を外し、空いたスロットにする。"""
    handed = hand_out(main, orch, "a")
    assert handed.returncode == 0, handed.stderr
    assert npm_calls() == 1
    assert orchestrate(main, orch, "slot", "release", "1").returncode == 0
    return Path(handed.stdout.strip().splitlines()[-1])


def slot_line(main: Path, orch: Path) -> str:
    return next(x for x in orchestrate(main, orch, "slot", "list").stdout.splitlines() if x.startswith("slot-1:"))


def test_warmed_slot_is_handed_out_without_npm_ci(npm_world):
    main, orch, npm_calls = npm_world
    slot = free_slot(main, orch, npm_calls)
    change_lock_on_master(main)
    assert "依存がorigin/masterと違う" in slot_line(main, orch)

    warmed = orchestrate(main, orch, "slot", "warm")

    assert warmed.returncode == 0, warmed.stderr
    assert npm_calls() == 2
    assert "空き（ロックなし）" in slot_line(main, orch)
    handed = hand_out(main, orch, "b")
    assert handed.returncode == 0, handed.stderr
    assert "npm ciは不要" in handed.stderr
    assert npm_calls() == 2
    assert os.path.samefile(handed.stdout.strip().splitlines()[-1], slot)
    assert git(slot, "rev-parse", "HEAD") == git(main, "rev-parse", "origin/master")


def test_warm_leaves_a_handed_out_slot_alone(npm_world):
    main, orch, npm_calls = npm_world
    handed = hand_out(main, orch, "a")
    slot = Path(handed.stdout.strip().splitlines()[-1])
    before = git(slot, "rev-parse", "HEAD")
    change_lock_on_master(main)

    assert orchestrate(main, orch, "slot", "warm").returncode == 0

    assert npm_calls() == 1
    assert git(slot, "rev-parse", "HEAD") == before
    assert "渡し先 slot agent-a " in slot_line(main, orch)


def test_check_warms_a_cold_free_slot_in_the_background(npm_world):
    main, orch, npm_calls = npm_world
    free_slot(main, orch, npm_calls)
    change_lock_on_master(main)

    checked = orchestrate(main, orch, "check")

    assert "npm ciを裏で起こした" in checked.stdout, checked.stdout + checked.stderr
    deadline = time.monotonic() + 60
    while not ("空き（ロックなし）" in (line := slot_line(main, orch)) and "依存はorigin/masterと同じ" in line):
        assert time.monotonic() < deadline, line + (orch / "warm.log").read_text(encoding="utf-8", errors="replace")
        time.sleep(1)
    assert npm_calls() == 2
    assert "npm ciは不要" in hand_out(main, orch, "b").stderr
    assert "npm ciを裏で起こした" not in orchestrate(main, orch, "check").stdout


def test_mark_left_by_a_dead_warm_is_cleared_when_handing_out(npm_world):
    main, orch, npm_calls = npm_world
    slot = free_slot(main, orch, npm_calls)
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True,
                          check=True).stdout.strip()
    git(main, "worktree", "lock", "--reason", f"slot warm-{dead} 2026-09-26T00:00:00+09:00", str(slot))

    handed = hand_out(main, orch, "b")

    assert handed.returncode == 0, handed.stderr
    assert "温める処理が死んで残った印を外した" in handed.stderr
    assert "渡し先 slot agent-b " in slot_line(main, orch)


@pytest.fixture
def tools_world(world):
    """origin/masterに今の道具（scripts/）を入れ、本体のチェックアウトの道具だけを古くする（渡そうとすると落ちる版）。"""
    main, orch = world
    repo = ENTRY.parents[1]
    for name in git(repo, "ls-files", "--", "scripts").splitlines():
        (main / name).parent.mkdir(parents=True, exist_ok=True)
        (main / name).write_bytes((repo / name).read_bytes())
    git(main, "add", "scripts")
    git(main, "commit", "--quiet", "-m", "T0: 道具")
    git(main, "push", "--quiet", "origin", "master")
    (main / "scripts" / "orchestration" / "slots.py").write_text(
        "import sys\n\n\ndef main(argv):\n    print('本体の古い道具が動いた', file=sys.stderr)\n    return 3\n",
        encoding="utf-8")
    return main, orch


def launch(main: Path, orch: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    """フックの入口と同じく、起動役をorigin/masterから取り出して動かす。"""
    launcher = main.parent / "launch.py"
    launcher.write_text(git(main, "show", "origin/master:scripts/orchestration/launch.py"), encoding="utf-8")
    return subprocess.run([sys.executable, str(launcher), "--project", str(main), "--dir", str(orch), *args],
                          cwd=main, input=stdin, capture_output=True, text=True, encoding="utf-8", check=False)


def exports(main: Path) -> set[str]:
    return {p.name for p in (main / ".git" / "orchestration" / "tools").iterdir()}


def test_worktree_hooks_through_the_launcher_use_the_tools_of_origin_master(tools_world):
    main, orch = tools_world

    handed = launch(main, orch, "slot", "hook-create", stdin=json.dumps({"name": "agent-a"}))

    assert handed.returncode == 0, handed.stderr
    assert "本体の古い道具が動いた" not in handed.stderr
    slot = Path(handed.stdout.strip().splitlines()[-1])
    assert git(slot, "rev-parse", "HEAD") == git(main, "rev-parse", "origin/master")
    assert exports(main) == {git(main, "rev-parse", "origin/master")}
    removed = launch(main, orch, "slot", "hook-remove", stdin=json.dumps({"worktree_path": str(slot)}))
    assert removed.returncode == 0, removed.stderr
    assert "空き（ロックなし）" in slot_line(main, orch)


def test_export_of_an_older_master_is_removed_only_after_it_went_unused(tools_world):
    main, orch = tools_world
    assert launch(main, orch, "slot", "list").returncode == 0
    first = git(main, "rev-parse", "origin/master")
    commit(main, "README.md", "進んだ\n", "T2: masterが進む")
    git(main, "push", "--quiet", "origin", "master")

    assert launch(main, orch, "slot", "list").returncode == 0
    assert exports(main) == {first, git(main, "rev-parse", "origin/master")}

    long_ago = time.time() - 2 * 24 * 3600
    os.utime(main / ".git" / "orchestration" / "tools" / first, (long_ago, long_ago))
    commit(main, "README.md", "さらに進んだ\n", "T3: masterがさらに進む")
    git(main, "push", "--quiet", "origin", "master")
    assert launch(main, orch, "slot", "list").returncode == 0
    assert first not in exports(main)
