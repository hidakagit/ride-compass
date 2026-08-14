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
