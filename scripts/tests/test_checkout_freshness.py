"""`scripts/checkout_freshness.py`のテスト。

origin は一時的な bare リポジトリで作り、git は本物を通す。

ここで見ないもの: 道具の実行口（`main`）と、道具から呼ぶ所（`review_checks.py` 等）の結線。
"""

from pathlib import Path

import pytest

from git_repo import git
from script_module import load_script

cf = load_script("checkout_freshness")


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def clones(tmp_path):
    """origin（bare）と、それを取った2つのクローン（work は確かめる側、other は master を進める側）。"""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "master", str(origin))
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(origin), str(other))
    git(other, "checkout", "-q", "-b", "master")
    _commit(other, "a.txt", "1\n")
    git(other, "push", "-q", "origin", "master")
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(work))
    return work, other


def _advance_master(other: Path) -> str:
    sha = _commit(other, "b.txt", "2\n")
    git(other, "push", "-q", "origin", "master")
    return sha


def test_a_branch_on_top_of_the_latest_master_is_current(clones):
    work, other = clones
    _advance_master(other)
    git(work, "fetch", "-q")
    git(work, "checkout", "-q", "-b", "feature", "origin/master")
    _commit(work, "c.txt", "3\n")

    assert cf.staleness(work) is None


def test_a_checkout_behind_master_reports_the_count_and_the_fast_forward_command(clones):
    work, other = clones
    _advance_master(other)

    message = cf.staleness(work)

    assert "1 コミット遅れ" in message
    assert "merge --ff-only origin/master" in message


def test_require_current_fast_forwards_a_clean_master_and_goes_on(clones):
    work, other = clones
    latest = _advance_master(other)

    cf.require_current(work)

    assert git(work, "rev-parse", "HEAD") == latest


def test_require_current_stops_on_a_master_with_changes(clones):
    work, other = clones
    _advance_master(other)
    (work / "a.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="片付けてから"):
        cf.require_current(work)


def test_require_current_stops_on_another_branch_without_touching_it(clones):
    work, other = clones
    git(work, "checkout", "-q", "-b", "feature")
    before = git(work, "rev-parse", "HEAD")
    _advance_master(other)

    with pytest.raises(SystemExit, match="rebase origin/master"):
        cf.require_current(work)
    assert git(work, "rev-parse", "HEAD") == before


def test_a_checkout_that_cannot_reach_origin_stops_as_unverified(clones):
    work, _ = clones
    git(work, "remote", "set-url", "origin", str(work.parent / "missing.git"))

    assert "確かめられない" in cf.staleness(work)
    with pytest.raises(SystemExit):
        cf.require_current(work)
