"""`get_redis_client_or_none`のfail-open挙動。"""

from app.infrastructure import redis_client


def test_get_redis_client_or_none_returns_client_on_success(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(redis_client, "_get_redis_client", lambda: sentinel)

    assert redis_client.get_redis_client_or_none() is sentinel


def test_get_redis_client_or_none_returns_none_and_records_failure_on_exception(monkeypatch):
    # redis.from_url()自体が同期的に例外を送出しうる（settings.redis_urlの設定ミス等）。
    def _raise():
        raise ValueError("invalid URL scheme")

    monkeypatch.setattr(redis_client, "_get_redis_client", _raise)
    redis_client.reset_circuit_breaker()

    result = redis_client.get_redis_client_or_none()

    assert result is None
    assert redis_client.redis_available() is False  # record_redis_failure()が記録されたことの確認
    redis_client.reset_circuit_breaker()
