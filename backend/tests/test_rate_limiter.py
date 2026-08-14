from collections import defaultdict

import pytest

from app.infrastructure import rate_limiter


@pytest.fixture(autouse=True)
def isolated_hits(monkeypatch):
    # _hitsはプロセス内グローバルな状態のため、テスト間で汚染しないよう毎回差し替える。
    monkeypatch.setattr(rate_limiter, "_hits", defaultdict(list))
    yield


def _set_now(monkeypatch, value: float) -> None:
    monkeypatch.setattr(rate_limiter.time, "monotonic", lambda: value)


def test_allows_requests_up_to_the_limit(monkeypatch):
    _set_now(monkeypatch, 0.0)

    for _ in range(3):
        assert rate_limiter.check_rate_limit("client-a", max_requests=3) is True


def test_rejects_once_the_limit_is_exceeded(monkeypatch):
    _set_now(monkeypatch, 0.0)

    for _ in range(3):
        rate_limiter.check_rate_limit("client-a", max_requests=3)

    assert rate_limiter.check_rate_limit("client-a", max_requests=3) is False


def test_clients_are_tracked_independently(monkeypatch):
    _set_now(monkeypatch, 0.0)

    for _ in range(3):
        rate_limiter.check_rate_limit("client-a", max_requests=3)

    # client-aが上限に達していても、別クライアントは独立してカウントされる。
    assert rate_limiter.check_rate_limit("client-b", max_requests=3) is True


def test_old_hits_outside_the_window_are_forgotten(monkeypatch):
    _set_now(monkeypatch, 0.0)
    for _ in range(3):
        rate_limiter.check_rate_limit("client-a", max_requests=3, window_seconds=60.0)
    assert rate_limiter.check_rate_limit("client-a", max_requests=3, window_seconds=60.0) is False

    # ウィンドウ経過後は古いヒットが切り捨てられ、再度リクエストできる。
    _set_now(monkeypatch, 61.0)
    assert rate_limiter.check_rate_limit("client-a", max_requests=3, window_seconds=60.0) is True


def test_sweep_removes_stale_clients_after_interval(monkeypatch):
    # _hitsはウィンドウ超過分のタイムスタンプを間引くが、キー自体はアクセスが無い限り
    # 残り続ける（一度でもアクセスしたIPが辞書に無期限に溜まるメモリリーク対策の検証）。
    monkeypatch.setattr(rate_limiter, "_last_sweep", 0.0)
    _set_now(monkeypatch, 0.0)
    rate_limiter.check_rate_limit("client-stale", max_requests=3, window_seconds=60.0)

    # _SWEEP_INTERVAL_SECONDS(300秒)未満では、直近ウィンドウ外でもキーはまだ掃除されない。
    _set_now(monkeypatch, 200.0)
    rate_limiter.check_rate_limit("client-other", max_requests=3, window_seconds=60.0)
    assert "client-stale" in rate_limiter._hits

    # _SWEEP_INTERVAL_SECONDS経過後の次回呼び出しで、直近ウィンドウ内にヒットが無いキーが消える。
    _set_now(monkeypatch, 305.0)
    rate_limiter.check_rate_limit("client-other", max_requests=3, window_seconds=60.0)
    assert "client-stale" not in rate_limiter._hits
