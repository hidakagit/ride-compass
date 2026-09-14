"""ベンチマークが「どのコードを測ったか」を残し、古い作業コピーでは止まることの検査。"""

from benchmarks._revision import RevisionState, describe, stale_reason

SHA = "a" * 40
OTHER = "b" * 40


def test_describe_records_the_measured_commit():
    text = describe(RevisionState(head=SHA, remote_head=SHA, dirty=False))
    assert SHA[:12] in text


def test_describe_flags_uncommitted_changes():
    assert "未コミット" in describe(RevisionState(head=SHA, remote_head=SHA, dirty=True))


def test_stale_reason_none_when_up_to_date():
    assert stale_reason(RevisionState(head=SHA, remote_head=SHA, dirty=False)) is None


def test_stale_reason_names_both_commits_when_behind():
    reason = stale_reason(RevisionState(head=SHA, remote_head=OTHER, dirty=False))
    assert reason is not None
    assert SHA[:12] in reason and OTHER[:12] in reason


def test_stale_reason_none_when_remote_unreachable():
    # 配信元を引けないときに止めると、測れるのに測れなくなる。素性はdescribeが残す。
    assert stale_reason(RevisionState(head=SHA, remote_head=None, dirty=False)) is None
    assert stale_reason(RevisionState(head=None, remote_head=None, dirty=False)) is None
