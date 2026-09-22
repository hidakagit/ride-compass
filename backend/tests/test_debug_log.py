"""`infrastructure/debug_log.py`——外部I/Oイベントの抑制付きWARNINGとプロセス内集計。

ここで見ないもの:
- `/api/debug/stats`の応答の形・公開範囲 → `test_debug_stats_route.py`
- 各クライアントがどのカテゴリ名・fieldsを設定するか → そのクライアントのテスト
- ロガー名が`ridecompass.`接頭辞に揃っているか → `tests/structure/test_canonical_definitions.py`

**時刻は差し替えて与える。** 所要時間も抑制窓も`time.monotonic()`だけで決まるため、実時間を
待つと窓の境界（60秒）を跨げない。
"""

import logging

import pytest

from app.infrastructure import debug_log

LOGGER_NAME = "ridecompass.external"


class _Clock:
    def __init__(self) -> None:
        self.seconds = 1000.0

    def monotonic(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(debug_log, "time", fake)
    return fake


@pytest.fixture(autouse=True)
def _clean_counters():
    debug_log.reset_stats()
    yield
    debug_log.reset_stats()


@pytest.fixture
def warnings(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)

    class _Warnings:
        def messages(self) -> list[str]:
            return [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]

    return _Warnings()


def _external(category: str) -> dict:
    return debug_log.get_stats()["external"][category]


def test_errors_carrying_an_http_response_are_labeled_by_status_code():
    class _Response:
        status_code = 503

    class _HttpStatusError(Exception):
        response = _Response()

    assert debug_log.error_type_label(_HttpStatusError()) == "http_503"


def test_other_errors_are_labeled_by_their_class_name():
    class _Unreachable(Exception):
        response = None

    assert debug_log.error_type_label(TimeoutError()) == "TimeoutError"
    assert debug_log.error_type_label(_Unreachable()) == "_Unreachable"


def test_the_label_carries_neither_the_message_nor_the_url():
    """`/api/debug/stats`は常時公開で、例外メッセージにはユーザーの現在地を載せたURLが
    入りうる。ラベルへ混ぜると座標がそのまま外から読める。
    """
    label = debug_log.error_type_label(RuntimeError("GET https://example.test/?lat=35.681236 failed"))

    assert label == "RuntimeError"


def test_coordinates_in_the_always_on_warning_are_coarsened(clock, warnings):
    """常時出るWARNINGは本番のログストリームへ残り続ける。丸めないと、利用者の現在地が
    1m精度でログに溜まる。
    """
    with pytest.raises(ValueError):
        with debug_log.log_external_call(
            "cat",
            lat=35.123456,
            span=(12.3456, 78.9012),
            box=[1.23456],
            meta={"lon": 139.987654},
            zoom=12,
            note="abc",
        ):
            raise ValueError("boom")

    (message,) = warnings.messages()
    assert "35.123456" not in message
    assert "1.23456" not in message
    assert "139.987654" not in message
    assert "35.12" in message
    assert "(12.35, 78.9)" in message
    assert "[1.23]" in message
    assert "139.99" in message
    assert "12" in message
    assert "abc" in message


def test_only_the_first_few_warnings_of_a_category_are_emitted(clock, warnings):
    """外部サービスが落ちている間、1件ずつ出すとログが同じ警告で埋まり、他の障害が読めなくなる。"""
    for i in range(debug_log.WARN_BURST_PER_WINDOW + 3):
        debug_log.log_throttled_warning("cat", "boom %d", i)

    assert len(warnings.messages()) == debug_log.WARN_BURST_PER_WINDOW


def test_the_suppressed_count_is_reported_once_the_window_turns_over(clock, warnings):
    """抑制した件数を出さないと、読み手は「警告が5件で収まった」と読んでしまう。"""
    for i in range(debug_log.WARN_BURST_PER_WINDOW + 3):
        debug_log.log_throttled_warning("cat", "boom %d", i)
    clock.advance(debug_log.WARN_WINDOW_SECONDS)

    debug_log.log_throttled_warning("cat", "boom again")

    emitted = warnings.messages()[debug_log.WARN_BURST_PER_WINDOW :]
    assert "suppressed 3 similar warnings" in emitted[0]
    assert emitted[1] == "boom again"


def test_no_notice_is_emitted_when_the_previous_window_suppressed_nothing(clock, warnings):
    debug_log.log_throttled_warning("cat", "first")
    clock.advance(debug_log.WARN_WINDOW_SECONDS)
    debug_log.log_throttled_warning("cat", "second")

    assert warnings.messages() == ["first", "second"]


def test_each_category_gets_its_own_budget(clock, warnings):
    """1つの外部サービスの障害が、他のサービスの警告まで黙らせてはならない。"""
    for i in range(debug_log.WARN_BURST_PER_WINDOW + 3):
        debug_log.log_throttled_warning("noisy", "boom %d", i)

    debug_log.log_throttled_warning("quiet", "still heard")

    assert "still heard" in warnings.messages()


def test_rate_limit_rejections_are_counted_and_warned(clock, warnings):
    debug_log.record_rate_limit_rejection("cat", "client-a", "120/min")
    debug_log.record_rate_limit_rejection("cat", "client-a", "120/min")

    assert debug_log.get_stats()["rate_limit_rejections"] == {"cat": 2}
    assert "client=client-a limit=120/min" in warnings.messages()[0]


def test_rate_limit_warnings_do_not_spend_the_external_categorys_budget(clock, warnings):
    """同名の外部カテゴリと窓を共有すると、429が続いた瞬間にその外部APIの失敗警告が消える。"""
    for i in range(debug_log.WARN_BURST_PER_WINDOW + 3):
        debug_log.log_throttled_warning("cat", "boom %d", i)

    debug_log.record_rate_limit_rejection("cat", "client-a", "120/min")

    assert any("rejected client=client-a" in m for m in warnings.messages())


def test_a_successful_call_is_counted_without_any_warning(clock, warnings):
    with debug_log.log_external_call("cat", result="ok"):
        pass

    stats = _external("cat")
    assert (stats["calls"], stats["errors"]) == (1, 0)
    assert stats["last_success_at"] is not None
    assert stats["last_error_at"] is None
    assert warnings.messages() == []


def test_an_exception_is_counted_warned_and_re_raised(clock, warnings):
    with pytest.raises(ValueError):
        with debug_log.log_external_call("cat"):
            raise ValueError("boom")

    stats = _external("cat")
    assert (stats["calls"], stats["errors"]) == (1, 1)
    assert stats["error_types"] == {"ValueError": 1}
    assert stats["last_error_type"] == "ValueError"
    assert stats["last_error_at"] is not None
    assert len(warnings.messages()) == 1


def test_a_result_of_error_is_counted_even_though_nothing_was_raised(clock, warnings):
    """例外を握りつぶして既定値を返すクライアントの失敗が、集計から消えてしまわないこと。"""
    with debug_log.log_external_call("cat") as fields:
        fields["result"] = "error"
        fields["error_type"] = "http_500"

    stats = _external("cat")
    assert (stats["errors"], stats["error_types"]) == (1, {"http_500": 1})
    assert len(warnings.messages()) == 1


def test_a_caller_that_already_warned_is_not_warned_again_but_is_still_counted(clock, warnings):
    with debug_log.log_external_call("cat") as fields:
        fields["result"] = "error"
        fields["warned"] = True

    assert _external("cat")["errors"] == 1
    assert warnings.messages() == []


def test_the_callers_own_error_type_survives_the_exception_path(clock, warnings):
    """例外の種別で上書きすると、クライアントが分類した`http_429`等が`HTTPStatusError`一色になる。"""
    with pytest.raises(ValueError):
        with debug_log.log_external_call("cat") as fields:
            fields["error_type"] = "http_429"
            raise ValueError("boom")

    assert _external("cat")["error_types"] == {"http_429": 1}


def test_an_unclassified_failure_is_counted_as_unknown(clock, warnings):
    with debug_log.log_external_call("cat") as fields:
        fields["result"] = "error"

    assert _external("cat")["error_types"] == {"unknown": 1}


def test_the_cache_hit_rate_counts_only_declared_lookups(clock, warnings):
    for cache in ("hit", "hit", "miss", None):
        with debug_log.log_external_call("cat", cache=cache):
            pass
    with debug_log.log_external_call("nolookup"):
        pass

    stats = _external("cat")
    assert (stats["cache_hits"], stats["cache_misses"]) == (2, 1)
    assert stats["cache_hit_rate"] == 0.667
    assert _external("nolookup")["cache_hit_rate"] is None


def test_retries_are_counted_only_when_the_call_actually_retried(clock, warnings):
    """「まだ成功しているが上流が混み始めている」兆候。0回を数えると常時1件に見える。"""
    with debug_log.log_external_call("cat", retries=2):
        pass
    with debug_log.log_external_call("cat", retries=0):
        pass
    with debug_log.log_external_call("cat"):
        pass

    stats = _external("cat")
    assert (stats["retried_calls"], stats["retry_attempts_total"]) == (1, 2)


def test_only_a_stale_cache_fallback_is_counted_as_one(clock, warnings):
    with debug_log.log_external_call("cat", fallback="stale_cache:redis"):
        pass
    with debug_log.log_external_call("cat", fallback="default"):
        pass
    with debug_log.log_external_call("cat", fallback=True):
        pass

    assert _external("cat")["stale_fallback_used"] == 1


def test_durations_accumulate_into_the_total_average_and_peak(clock, warnings):
    with debug_log.log_external_call("cat"):
        clock.advance(0.012)
    with debug_log.log_external_call("cat"):
        clock.advance(0.030)

    stats = _external("cat")
    assert (stats["total_ms"], stats["max_ms"], stats["avg_ms"]) == (42, 30, 21)


def test_categories_come_back_in_name_order(clock, warnings):
    """呼ばれた順のままだと、読み直すたびに同じカテゴリが別の位置へ動く。"""
    for category in ("zz", "aa", "mm"):
        with debug_log.log_external_call(category):
            pass

    assert list(debug_log.get_stats()["external"]) == ["aa", "mm", "zz"]


def test_the_snapshot_does_not_alias_the_running_counters(clock, warnings):
    """応答を組み立てるのはロックの外。内部dictを共有していると、別リクエストの更新が
    反復の最中に割り込む。
    """
    with pytest.raises(ValueError):
        with debug_log.log_external_call("cat"):
            raise ValueError("boom")
    debug_log.record_rate_limit_rejection("cat", "client-a", "120/min")

    snapshot = debug_log.get_stats()
    snapshot["external"]["cat"]["calls"] = 999
    snapshot["external"]["cat"]["error_types"]["ValueError"] = 999
    snapshot["rate_limit_rejections"]["cat"] = 999

    fresh = debug_log.get_stats()
    assert fresh["external"]["cat"]["calls"] == 1
    assert fresh["external"]["cat"]["error_types"] == {"ValueError": 1}
    assert fresh["rate_limit_rejections"] == {"cat": 1}
