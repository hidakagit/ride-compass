"""debug_log(外部I/Oイベントのログ・集計)の回帰テスト。

docs/logging.mdの方針のうち「失敗はdebug_modeに関わらずWARNINGで常時出る」
「同種WARNINGはカテゴリごとに毎分5件で抑制」「統計(/api/debug/stats用)が集計される」を守る。
"""

import logging

import pytest

from app.infrastructure import debug_log
from app.infrastructure.debug_log import (
    WARN_BURST_PER_WINDOW,
    get_stats,
    log_external_call,
    record_rate_limit_rejection,
    reset_stats,
)


@pytest.fixture(autouse=True)
def _clean_stats():
    reset_stats()
    yield
    reset_stats()


def test_success_is_debug_only(caplog):
    caplog.set_level(logging.DEBUG, logger="ridecompass.external")
    with log_external_call("test:api", key="value") as fields:
        fields["result"] = "ok"

    records = [r for r in caplog.records if r.name == "ridecompass.external"]
    assert all(r.levelno == logging.DEBUG for r in records)


def test_exception_logs_warning_and_counts_error(caplog):
    caplog.set_level(logging.WARNING, logger="ridecompass.external")
    with pytest.raises(ValueError):
        with log_external_call("test:api", lat=35.123456):
            raise ValueError("boom")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    # 常時出るWARNINGでは座標(float)が2桁へ丸められる
    assert "35.12" in warnings[0].getMessage()
    assert "35.123456" not in warnings[0].getMessage()

    stats = get_stats()["external"]["test:api"]
    assert stats["calls"] == 1
    assert stats["errors"] == 1


def test_result_error_field_logs_warning_without_exception(caplog):
    # クライアントの多くは例外を握りつぶしてNoneを返す(fields["result"]="error"を設定する)
    # 設計のため、例外が出ないパスでもWARNINGが出ることを保証する。
    caplog.set_level(logging.WARNING, logger="ridecompass.external")
    with log_external_call("test:api") as fields:
        fields["result"] = "error"

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert get_stats()["external"]["test:api"]["errors"] == 1


def test_cache_hit_rate_aggregation():
    for outcome in ["hit", "hit", "hit", "miss"]:
        with log_external_call("test:cache") as fields:
            fields["cache"] = outcome
            fields["result"] = "ok"

    stats = get_stats()["external"]["test:cache"]
    assert stats["calls"] == 4
    assert stats["cache_hits"] == 3
    assert stats["cache_misses"] == 1
    assert stats["cache_hit_rate"] == 0.75
    assert stats["errors"] == 0
    assert "avg_ms" in stats and "max_ms" in stats


def test_warning_throttled_per_category(caplog):
    caplog.set_level(logging.WARNING, logger="ridecompass.external")
    for _ in range(WARN_BURST_PER_WINDOW + 10):
        with log_external_call("test:flood") as fields:
            fields["result"] = "error"

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == WARN_BURST_PER_WINDOW
    # 抑制はカテゴリ単位: 別カテゴリのWARNINGは抑制されない
    with log_external_call("test:other") as fields:
        fields["result"] = "error"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == WARN_BURST_PER_WINDOW + 1


def test_suppressed_count_reported_on_next_window(caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger="ridecompass.external")
    now = [1000.0]
    monkeypatch.setattr(debug_log.time, "monotonic", lambda: now[0])

    for _ in range(WARN_BURST_PER_WINDOW + 3):
        with log_external_call("test:flood") as fields:
            fields["result"] = "error"

    # 窓が切り替わった最初の警告時に、抑制件数のお知らせが出る
    now[0] += debug_log.WARN_WINDOW_SECONDS + 1
    with log_external_call("test:flood") as fields:
        fields["result"] = "error"

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("suppressed 3 similar warnings" in m for m in messages)


def test_rate_limit_rejection_counted_and_warned(caplog):
    caplog.set_level(logging.WARNING, logger="ridecompass.external")
    record_rate_limit_rejection("generate", "203.0.113.5", "10/min")
    record_rate_limit_rejection("generate", "203.0.113.5", "10/min")

    assert get_stats()["rate_limit_rejections"]["generate"] == 2
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("ratelimit:generate" in m and "203.0.113.5" in m for m in warnings)


def test_reset_stats():
    with log_external_call("test:api") as fields:
        fields["result"] = "ok"
    reset_stats()
    assert get_stats() == {"external": {}, "rate_limit_rejections": {}}
