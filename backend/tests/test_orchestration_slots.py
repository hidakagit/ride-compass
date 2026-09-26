"""`scripts/orchestrate.py slot`のスロットを渡し直すときの止まる条件（一時的なgitリポジトリで動かす）。

司令塔は担当のコミットを畳み直した別のコミットとしてmasterへ入れ、作業ブランチを消す。担当の元のコミットは
どのリモートの枝からも届かなくなるが、監査で通したタスクの番号から始まる件名のコミットが監査の後にmasterへ
入っていれば、スロットには失われるものが無い。規約の流れ（振り出し→担当のpush→監査で通す→取り込み→
作業ブランチの削除→次の担当の起動）を、入口のコマンドだけで辿る。
"""

import json
import os
import subprocess
import sys
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
