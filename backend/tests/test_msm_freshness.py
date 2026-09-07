"""msm_client.pyの鮮度判定（配信が止まったことの検知）のテスト。

配信元が新しいrunを出さなくても同期そのものは成功する（ETagで304になり取得0件になる）。
「取得0件」は正常時とも区別がつかないため、メタ情報の時刻から判定する。
"""

import logging
from datetime import datetime, timedelta

from app.infrastructure.msm_client import JST, freshness_from_meta, warn_if_stale


def _meta(*, run_at: datetime, end_at: datetime) -> dict:
    return {
        "last_run_initialisation_time": int(run_at.timestamp()),
        "data_end_time": int(end_at.timestamp()),
    }


def test_normal_publication_delay_does_not_warn():
    # 実測: 通常の公開遅れは約3.5時間、遅い日で約5時間。ここで発報すると誤報になる。
    now = datetime(2026, 9, 7, 20, 0, tzinfo=JST)
    meta = _meta(run_at=now - timedelta(hours=5), end_at=now + timedelta(hours=34))

    result = freshness_from_meta(meta, now=now)

    assert result is not None
    assert not result.run_is_stale
    assert not result.horizon_is_short
    assert result.is_healthy


def test_two_missed_runs_is_reported_as_stale(caplog):
    # 3時間おきの更新を2本連続で落とした状態。
    now = datetime(2026, 9, 7, 20, 0, tzinfo=JST)
    meta = _meta(run_at=now - timedelta(hours=6, minutes=30), end_at=now + timedelta(hours=30))

    result = freshness_from_meta(meta, now=now)
    with caplog.at_level(logging.WARNING):
        warn_if_stale(result)

    assert result.run_is_stale
    assert not result.is_healthy
    assert "最新runが古いままです" in caplog.text


def test_short_remaining_horizon_is_reported_before_it_breaks(caplog):
    # 予報終端が現在時刻へ追いつくと風グリッドが読めなくなる。その手前で気づけること。
    now = datetime(2026, 9, 7, 20, 0, tzinfo=JST)
    meta = _meta(run_at=now - timedelta(hours=2), end_at=now + timedelta(hours=8))

    result = freshness_from_meta(meta, now=now)
    with caplog.at_level(logging.WARNING):
        warn_if_stale(result)

    assert result.horizon_is_short
    assert "予報が尽きかけています" in caplog.text


def test_unreadable_meta_warns_instead_of_passing_silently(caplog):
    assert freshness_from_meta({}) is None

    with caplog.at_level(logging.WARNING):
        warn_if_stale(None)

    assert "鮮度を判定できません" in caplog.text
