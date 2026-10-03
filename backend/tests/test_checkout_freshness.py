"""`scripts/checkout_freshness.py`のテスト。

origin は一時的な bare リポジトリで作り、git は本物を通す。
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "checkout_freshness", Path(__file__).resolve().parents[2] / "scripts" / "checkout_freshness.py"
)
cf = importlib.util.module_from_spec(_SPEC)
sys.modules["checkout_freshness"] = cf
_SPEC.loader.exec_module(cf)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def clones(tmp_path):
    """origin（bare）と、それを取った2つのクローン（work は確かめる側、other は master を進める側）。"""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "master", str(origin))
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    _git(other, "checkout", "-q", "-b", "master")
    _commit(other, "a.txt", "1\n")
    _git(other, "push", "-q", "origin", "master")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    return work, other


def _advance_master(other: Path) -> str:
    sha = _commit(other, "b.txt", "2\n")
    _git(other, "push", "-q", "origin", "master")
    return sha


def test_a_checkout_that_contains_origin_master_is_current(clones):
    work, _ = clones

    assert cf.staleness(work) is None
    assert "なし" in cf.sync(work)


def test_a_branch_on_top_of_the_latest_master_is_current(clones):
    work, other = clones
    _advance_master(other)
    _git(work, "fetch", "-q")
    _git(work, "checkout", "-q", "-b", "feature", "origin/master")
    _commit(work, "c.txt", "3\n")

    assert cf.staleness(work) is None


def test_changes_in_the_working_tree_are_not_counted_as_behind(clones):
    work, _ = clones
    (work / "a.txt").write_text("changed\n", encoding="utf-8")

    assert cf.staleness(work) is None


def test_a_checkout_behind_master_stops_with_the_count_and_the_fast_forward_command(clones):
    work, other = clones
    _advance_master(other)

    message = cf.staleness(work)

    assert "1 コミット遅れ" in message
    assert "merge --ff-only origin/master" in message
    with pytest.raises(SystemExit):
        cf.require_current(work)


def test_sync_fast_forwards_a_clean_master(clones):
    work, other = clones
    head = _advance_master(other)

    assert "1 コミット早送りした" in cf.sync(work)
    assert _git(work, "rev-parse", "HEAD") == head
    assert cf.staleness(work) is None


def test_sync_leaves_a_master_with_changes_untouched(clones):
    work, other = clones
    before = _git(work, "rev-parse", "HEAD")
    _advance_master(other)
    (work / "a.txt").write_text("changed\n", encoding="utf-8")

    line = cf.sync(work)

    assert "1 コミット遅れ" in line
    assert "片付けてから" in line
    assert _git(work, "rev-parse", "HEAD") == before
    assert (work / "a.txt").read_text(encoding="utf-8") == "changed\n"


def test_sync_leaves_another_branch_untouched_and_suggests_a_rebase(clones):
    work, other = clones
    _git(work, "checkout", "-q", "-b", "feature")
    before = _git(work, "rev-parse", "HEAD")
    _advance_master(other)

    line = cf.sync(work)

    assert "1 コミット遅れ" in line
    assert "rebase origin/master" in line
    assert _git(work, "rev-parse", "HEAD") == before
    assert _git(work, "symbolic-ref", "--short", "HEAD") == "feature"


def test_a_checkout_that_cannot_reach_origin_stops_as_unverified(clones):
    work, _ = clones
    _git(work, "remote", "set-url", "origin", str(work.parent / "missing.git"))

    assert "確かめられない" in cf.staleness(work)
    assert "確かめられなかった" in cf.sync(work)
    with pytest.raises(SystemExit):
        cf.require_current(work)
