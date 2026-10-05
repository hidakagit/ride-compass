"""`infrastructure/debug_log.py`——外部I/Oの記録（`log_external_call`・`mark_failed`）、カテゴリごとに抑える警告
（`log_throttled_warning`）、429の記録（`record_rate_limit_rejection`）と、それらの集計（`get_stats`）。

集計と警告の窓はプロセスの寿命の間残るので、テストごとに別のカテゴリ（`cat`）で数える。経過の時間と警告の窓は
`monotonic_clock`で、失敗の時刻は`clock`で進める。
ログは`caplog`で読む。

ここで見ないもの:
- 集計が`/api/debug/stats`の応答へどう出るか → `test_debug_stats_route.py`
- どの呼び出し元がどのカテゴリ・cache・resultを書くか → 呼び出し元のテスト（例: `test_simple_api_client.py`）
"""

import logging

import httpx
import pytest

from app.infrastructure.debug_log import (
    WARN_BURST_PER_WINDOW,
    WARN_WINDOW_SECONDS,
    get_stats,
    log_external_call,
    log_throttled_warning,
    mark_failed,
    record_rate_limit_rejection,
)

FROZEN_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def cat(request) -> str:
    """このテストだけのカテゴリ。前のテストの数・窓と混ざらない名前で始める。"""
    return f"cat:{request.node.name}"


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG, logger="ridecompass.external")
    return caplog


def warnings_of(logs) -> list[str]:
    return [record.getMessage() for record in logs.records if record.levelno == logging.WARNING]


def http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/tile?lat=35.681236&lon=139.767125")
    return httpx.HTTPStatusError("failed", request=request, response=httpx.Response(status_code, request=request))


def call(category: str, elapsed_seconds: float = 0.0, monotonic_clock=None, **result: object) -> None:
    """`category`の呼び出しを1回記録する。`result`は呼び出し元が書き足す結果。"""
    with log_external_call(category) as fields:
        if monotonic_clock is not None:
            monotonic_clock.advance(elapsed_seconds)
        fields.update(result)


class TestCounting:
    def test_a_successful_call_is_counted_with_its_time(self, cat, monotonic_clock):
        call(cat, 0.1, monotonic_clock)
        call(cat, 0.3, monotonic_clock)

        stats = get_stats().external[cat]
        assert (stats.calls, stats.errors) == (2, 0)
        assert (stats.total_ms, stats.max_ms, stats.avg_ms) == (400, 300, 200)
        assert stats.last_error is None

    @pytest.mark.parametrize(
        ("caches", "counted"),
        [(("hit", "hit", "miss"), (2, 1, 0.667)), ((None,), (0, 0, None))],
    )
    def test_the_hit_rate_is_over_the_calls_that_looked_at_a_cache(self, cat, caches, counted):
        for cache in caches:
            call(cat, cache=cache)

        stats = get_stats().external[cat]
        assert (stats.cache_hits, stats.cache_misses, stats.cache_hit_rate) == counted

    def test_categories_are_counted_apart_and_listed_in_name_order(self, cat):
        a, b = f"{cat}/basemap:a", f"{cat}/weather:b"
        call(b)
        call(a)
        call(b)

        external = get_stats().external
        assert [category for category in external if category in (a, b)] == [a, b]
        assert (external[a].calls, external[b].calls) == (1, 2)

    def test_a_snapshot_does_not_move_with_later_calls(self, cat):
        call(cat)
        snapshot = get_stats()

        call(cat, cache="hit")
        record_rate_limit_rejection(cat, "client", "120/min")

        assert snapshot.external[cat].calls == 1
        assert snapshot.external[cat].cache_hits == 0
        assert cat not in snapshot.rate_limit_rejections


class TestFailures:
    def test_an_exception_is_counted_by_its_class_and_raised_again(self, cat, logs, clock):
        with pytest.raises(ValueError):
            with log_external_call(cat):
                raise ValueError("lat=35.681236")

        stats = get_stats().external[cat]
        assert (stats.calls, stats.errors, stats.error_types) == (1, 1, {"ValueError": 1})
        assert (stats.last_error.type, stats.last_error.at) == ("ValueError", FROZEN_AT)
        assert any("error after" in message for message in warnings_of(logs))

    def test_an_http_error_is_counted_by_its_status_without_the_url(self, cat):
        with pytest.raises(httpx.HTTPStatusError):
            with log_external_call(cat):
                raise http_error(429)

        assert get_stats().external[cat].error_types == {"http_429": 1}

    def test_a_failure_caught_by_the_caller_is_counted_and_warned_with_the_exception(self, cat, logs):
        with log_external_call(cat, tile="14/1/2") as fields:
            mark_failed(fields, http_error(503))

        stats = get_stats().external[cat]
        assert (stats.errors, stats.error_types) == (1, {"http_503": 1})
        [warning] = warnings_of(logs)
        assert "failed after" in warning
        assert "14/1/2" in warning
        assert "HTTPStatusError" in warning

    def test_a_result_marked_as_error_without_a_reason_is_counted_as_unknown(self, cat, logs):
        call(cat, result="error")

        assert get_stats().external[cat].error_types == {"unknown": 1}
        assert len(warnings_of(logs)) == 1

    def test_a_later_success_keeps_the_last_error(self, cat, clock):
        call(cat, result="error")
        clock.tick(60)
        call(cat)

        assert get_stats().external[cat].last_error.at == FROZEN_AT


class TestLogLines:
    def test_a_success_is_logged_only_at_debug_with_the_coordinates_as_given(self, cat, logs):
        call(cat, lat=35.681236)

        assert warnings_of(logs) == []
        debug = [record.getMessage() for record in logs.records if record.levelno == logging.DEBUG]
        assert any("done in" in message and "35.681236" in message for message in debug)

    def test_a_warning_rounds_every_coordinate_to_two_decimals(self, cat, logs):
        """WARNINGは常時出るので、利用者の現在地を1km程度より細かく残さない。"""
        with log_external_call(
            cat, lat=35.681236, bbox=(139.767125, 35.681236), points=[139.767125], area={"lat": 35.681236}
        ) as fields:
            fields["result"] = "error"

        [warning] = warnings_of(logs)
        assert "35.681236" not in warning
        assert "139.767125" not in warning
        assert "'lat': 35.68" in warning
        assert "(139.77, 35.68)" in warning
        assert "[139.77]" in warning
        assert "{'lat': 35.68}" in warning


class TestWarningThrottle:
    def warn(self, category: str, times: int = 1) -> None:
        for _ in range(times):
            log_throttled_warning(category, "trouble in %s", category)

    def test_warnings_beyond_the_burst_are_held_back_within_a_window(self, cat, logs):
        self.warn(cat, times=WARN_BURST_PER_WINDOW + 3)

        assert warnings_of(logs) == [f"trouble in {cat}"] * WARN_BURST_PER_WINDOW

    @pytest.mark.parametrize(
        ("elapsed", "expected"),
        [
            (WARN_WINDOW_SECONDS - 1, []),
            (
                WARN_WINDOW_SECONDS,
                [f"[{{cat}}] suppressed 3 similar warnings in last {int(WARN_WINDOW_SECONDS)}s", "trouble in {cat}"],
            ),
        ],
    )
    def test_the_next_window_reports_how_many_were_held_back(self, cat, logs, monotonic_clock, elapsed, expected):
        self.warn(cat, times=WARN_BURST_PER_WINDOW + 3)
        logs.clear()

        monotonic_clock.advance(elapsed)
        self.warn(cat)

        assert warnings_of(logs) == [line.format(cat=cat) for line in expected]

    def test_a_new_window_without_anything_held_back_reports_nothing_extra(self, cat, logs, monotonic_clock):
        self.warn(cat)
        logs.clear()

        monotonic_clock.advance(WARN_WINDOW_SECONDS)
        self.warn(cat)

        assert warnings_of(logs) == [f"trouble in {cat}"]

    def test_each_category_has_its_own_window(self, cat, logs):
        self.warn(f"{cat}-a", times=WARN_BURST_PER_WINDOW)
        logs.clear()

        self.warn(f"{cat}-b")

        assert warnings_of(logs) == [f"trouble in {cat}-b"]

    def test_failed_calls_share_the_window_of_their_category(self, cat, logs):
        self.warn(cat, times=WARN_BURST_PER_WINDOW)
        logs.clear()

        call(cat, result="error")

        assert warnings_of(logs) == []
        assert get_stats().external[cat].errors == 1


class TestRateLimitRejections:
    def test_rejections_are_counted_per_category_and_warned_with_the_client_and_limit(self, cat, logs):
        tiles, generate = f"{cat}/tiles", f"{cat}/generate"
        record_rate_limit_rejection(tiles, "203.0.113.5", "120/min")
        record_rate_limit_rejection(tiles, "203.0.113.5", "120/min")
        record_rate_limit_rejection(generate, "203.0.113.6", "concurrent=2")

        rejections = get_stats().rate_limit_rejections
        assert (rejections[tiles], rejections[generate]) == (2, 1)
        assert warnings_of(logs)[0] == f"[ratelimit:{tiles}] rejected client=203.0.113.5 limit=120/min"

    def test_rejection_warnings_are_held_back_apart_from_failures_of_the_same_name(self, cat, logs):
        for _ in range(WARN_BURST_PER_WINDOW):
            call(cat, result="error")
        logs.clear()

        record_rate_limit_rejection(cat, "203.0.113.5", "120/min")

        assert warnings_of(logs) == [f"[ratelimit:{cat}] rejected client=203.0.113.5 limit=120/min"]
