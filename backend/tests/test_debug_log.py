"""debug_log(外部I/Oイベントのログ・集計)の回帰テスト。

docs/logging.mdの方針のうち「失敗はdebug_modeに関わらずWARNINGで常時出る」
「同種WARNINGはカテゴリごとに毎分5件で抑制」「統計(/api/debug/stats用)が集計される」を守る。
"""

import logging

import httpx
import pytest

from app.infrastructure import debug_log
from app.infrastructure.debug_log import (
    WARN_BURST_PER_WINDOW,
    error_type_label,
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


def test_result_error_with_warned_flag_counts_error_without_duplicate_warning(caplog):
    # 呼び出し元が例外を自前でcatchし、より詳細な文脈付きの独自WARNINGを既に出している場合
    # （region_service.py: get_traffic_stress_breakdown等）、fields["warned"]=Trueを立てると
    # ここでの二重WARNING出力だけ抑制しつつ、/api/debug/statsのerror集計には計上される
    # （改善計画レビュー指摘: 専用フィールド名でresultを避けて集計自体を諦める旧実装の回帰防止）。
    caplog.set_level(logging.WARNING, logger="ridecompass.external")
    with log_external_call("test:api") as fields:
        fields["result"] = "error"
        fields["warned"] = True

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 0
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


def test_error_type_label_uses_http_status_for_httpx_status_error():
    request = httpx.Request("GET", "https://api.open-meteo.com/v1/forecast?latitude=35.6812&longitude=139.7671")
    response = httpx.Response(429, request=request)
    exc = httpx.HTTPStatusError("Too Many Requests", request=request, response=response)

    label = error_type_label(exc)

    assert label == "http_429"
    # クエリパラメータ(座標)がラベルに含まれないこと(/api/debug/statsへ露出するため)
    assert "35.6812" not in label
    assert "139.7671" not in label


def test_error_type_label_uses_class_name_for_non_http_status_errors():
    assert error_type_label(httpx.ConnectTimeout("timed out")) == "ConnectTimeout"
    assert error_type_label(ValueError("bad json")) == "ValueError"


def test_error_types_are_tallied_with_last_error_type_and_timestamp():
    with log_external_call("test:api") as fields:
        fields["result"] = "error"
        fields["error_type"] = "http_429"
    with log_external_call("test:api") as fields:
        fields["result"] = "error"
        fields["error_type"] = "http_429"
    with log_external_call("test:api") as fields:
        fields["result"] = "error"
        fields["error_type"] = "ConnectTimeout"

    stats = get_stats()["external"]["test:api"]
    assert stats["error_types"] == {"http_429": 2, "ConnectTimeout": 1}
    assert stats["last_error_type"] == "ConnectTimeout"
    assert stats["last_error_at"] is not None


def test_error_without_explicit_error_type_falls_back_to_exception_class_name():
    with pytest.raises(ValueError):
        with log_external_call("test:api"):
            raise ValueError("boom")

    stats = get_stats()["external"]["test:api"]
    assert stats["error_types"] == {"ValueError": 1}
    assert stats["last_error_type"] == "ValueError"


def test_last_success_at_is_set_and_left_alone_by_errors():
    with log_external_call("test:api") as fields:
        fields["result"] = "ok"

    stats = get_stats()["external"]["test:api"]
    assert stats["last_success_at"] is not None
    assert stats["last_error_at"] is None


def test_retried_calls_are_tallied_even_when_call_eventually_succeeds():
    with log_external_call("test:api") as fields:
        fields["retries"] = 2
        fields["result"] = "ok"
    with log_external_call("test:api") as fields:
        fields["result"] = "ok"

    stats = get_stats()["external"]["test:api"]
    assert stats["retried_calls"] == 1
    assert stats["retry_attempts_total"] == 2


def test_stale_fallback_used_is_tallied():
    with log_external_call("test:api") as fields:
        fields["result"] = "error"
        fields["error_type"] = "ConnectTimeout"
        fields["fallback"] = "stale_cache"
    with log_external_call("test:api") as fields:
        fields["result"] = "error"
        fields["error_type"] = "ConnectTimeout"
        fields["fallback"] = "stale_cache:3"

    stats = get_stats()["external"]["test:api"]
    assert stats["stale_fallback_used"] == 2


def test_reset_stats():
    with log_external_call("test:api") as fields:
        fields["result"] = "ok"
    reset_stats()
    assert get_stats() == {"external": {}, "rate_limit_rejections": {}}
