"""msm_client.pyの鮮度判定（配信が止まったことの検知）のテスト。

配信元が新しいrunを出さなくても同期そのものは成功する（ETagで304になり取得0件になる）。
「取得0件」は正常時とも区別がつかないため、メタ情報の時刻から判定する。
"""

import logging
from datetime import datetime, timedelta

from app.domain.time_zone import JST
from app.infrastructure.msm_client import freshness_from_meta, warn_if_stale

INTERVAL_HOURS = 3


def _meta(
    *, run_at: datetime, end_at: datetime, published_at: datetime | None = None, interval_hours: int = INTERVAL_HOURS
) -> dict:
    meta = {
        "last_run_initialisation_time": int(run_at.timestamp()),
        "data_end_time": int(end_at.timestamp()),
        "update_interval_seconds": interval_hours * 3600,
    }
    if published_at is not None:
        meta["last_run_availability_time"] = int(published_at.timestamp())
    return meta


def test_run_age_just_before_the_next_publication_does_not_warn():
    # run初期時刻からの経過は「更新間隔＋公開遅れ」まで育つ（次のrunが公開されるまで伸び
    # 続ける）。ここで発報すると、配信が正常でも毎サイクルの末尾で赤くなる。
    now = datetime(2026, 9, 13, 19, 33, tzinfo=JST)
    meta = _meta(
        run_at=now - timedelta(hours=7, minutes=36),
        published_at=now - timedelta(hours=4, minutes=6),
        end_at=now + timedelta(hours=32),
    )

    result = freshness_from_meta(meta, now=now)

    assert result is not None
    assert result.run_age_hours > 6
    assert not result.run_is_stale
    assert result.is_healthy


def test_two_missed_publications_is_reported_as_stale(caplog):
    now = datetime(2026, 9, 7, 20, 0, tzinfo=JST)
    meta = _meta(
        run_at=now - timedelta(hours=10),
        published_at=now - timedelta(hours=6, minutes=30),
        end_at=now + timedelta(hours=30),
    )

    result = freshness_from_meta(meta, now=now)
    with caplog.at_level(logging.WARNING):
        warn_if_stale(result)

    assert result.run_is_stale
    assert not result.is_healthy
    assert "新しいrunが公開されていません" in caplog.text


def test_threshold_follows_the_delivered_update_interval():
    # 配信元が更新間隔を変えたら境目も一緒に動く（時間数を手で持たない）。
    now = datetime(2026, 9, 7, 20, 0, tzinfo=JST)
    published_at = now - timedelta(hours=7)
    end_at = now + timedelta(hours=30)

    three_hourly = freshness_from_meta(
        _meta(run_at=published_at, published_at=published_at, end_at=end_at, interval_hours=3), now=now
    )
    six_hourly = freshness_from_meta(
        _meta(run_at=published_at, published_at=published_at, end_at=end_at, interval_hours=6), now=now
    )

    assert three_hourly.run_is_stale
    assert not six_hourly.run_is_stale


def test_missing_publication_time_falls_back_to_the_run_time():
    # 公開時刻を配ってこない配信元では、run初期時刻で代用する（早く発報する側へ倒れる）。
    now = datetime(2026, 9, 7, 20, 0, tzinfo=JST)
    meta = _meta(run_at=now - timedelta(hours=7), end_at=now + timedelta(hours=30))

    result = freshness_from_meta(meta, now=now)

    assert result.last_publish_at == result.last_run_at
    assert result.run_is_stale


def test_short_remaining_horizon_is_reported_before_it_breaks(caplog):
    # 予報終端が現在時刻へ追いつくと風グリッドが読めなくなる。その手前で気づけること。
    now = datetime(2026, 9, 7, 20, 0, tzinfo=JST)
    meta = _meta(run_at=now - timedelta(hours=2), published_at=now - timedelta(hours=2), end_at=now + timedelta(hours=8))

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
