"""ベンチマークが「どのコードを測ったか」を残し、古い作業コピーでは止まることの検査（`benchmarks/revision.py`）。

ここで見ないもの: gitから状態を読む結線（`read_revision_state`）と、それを出して止める実行口
（`announce_revision`・`require_current_revision`）は手元の作業コピーと配信元を読むので通さない。
どの実行口も素性を出すことは`tests/structure/test_benchmark_revision_announced.py`が見る。
"""

import pytest

from benchmarks.revision import RevisionState, describe, stale_reason

SHA = "a" * 40
OTHER = "b" * 40


def test_describe_records_the_measured_commit_and_uncommitted_changes():
    text = describe(RevisionState(head=SHA, remote_head=SHA, dirty=True))
    assert SHA[:12] in text
    assert "未コミット" in text


# 配信元を引けないときに止めると、測れるのに測れなくなる。素性はdescribeが残す。
@pytest.mark.parametrize(("head", "remote_head"), [(SHA, SHA), (SHA, None), (None, None)])
def test_stale_reason_none_when_up_to_date_or_remote_unreachable(head, remote_head):
    assert stale_reason(RevisionState(head=head, remote_head=remote_head, dirty=False)) is None


def test_stale_reason_names_both_commits_when_behind():
    reason = stale_reason(RevisionState(head=SHA, remote_head=OTHER, dirty=False))
    assert reason is not None
    assert SHA[:12] in reason and OTHER[:12] in reason
