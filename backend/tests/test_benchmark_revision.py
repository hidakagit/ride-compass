"""ベンチマークが「どのコードを測ったか」を残し、古い作業コピーでは止まることの検査。"""

import re
from pathlib import Path

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


def _benchmark_entry_modules() -> list[Path]:
    """単体で実行できる（`__main__`を持つ）ベンチマークのモジュール。"""
    root = Path(__file__).resolve().parents[1] / "benchmarks"
    return sorted(p for p in root.glob("*.py")
                  if 'if __name__ == "__main__":' in p.read_text(encoding="utf-8"))


def test_every_benchmark_entry_states_which_revision_it_measured():
    # 数字はタスクエントリへ「実測」として引用される。どのコードを測ったかが数字と
    # 一緒に出ない実行口が1つでもあると、そこから引かれた数字だけ素性が分からなくなる。
    modules = _benchmark_entry_modules()
    assert modules, "実行口を持つベンチマークが1つも無い（母集団の導出が壊れている）"
    missing = [
        p.name for p in modules
        if not re.search(r"^\s+(?:announce_revision|require_current_revision)\(\)$",
                         p.read_text(encoding="utf-8"), re.M)
    ]
    assert not missing, f"素性を出さない実行口: {missing}"


def test_stale_reason_none_when_remote_unreachable():
    # 配信元を引けないときに止めると、測れるのに測れなくなる。素性はdescribeが残す。
    assert stale_reason(RevisionState(head=SHA, remote_head=None, dirty=False)) is None
    assert stale_reason(RevisionState(head=None, remote_head=None, dirty=False)) is None
