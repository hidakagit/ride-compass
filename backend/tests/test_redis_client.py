"""redis_client.py（改善計画T464: get_redis_client_or_noneのfail-open挙動）のテスト。"""

from app.infrastructure import redis_client


def test_get_redis_client_or_none_returns_client_on_success(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: sentinel)

    assert redis_client.get_redis_client_or_none() is sentinel


# 改善計画T464: redis.from_url()自体が同期的に例外を送出しうるケース（settings.redis_url
# 設定ミス等）に備え、get_redis_client()内部の例外をfail-openで捕捉することの回帰テスト。
def test_get_redis_client_or_none_returns_none_and_records_failure_on_exception(monkeypatch):
    def _raise():
        raise ValueError("invalid URL scheme")

    monkeypatch.setattr(redis_client, "get_redis_client", _raise)
    monkeypatch.setattr(redis_client, "_last_failure_at", None)

    result = redis_client.get_redis_client_or_none()

    assert result is None
    assert redis_client.redis_available() is False  # record_redis_failure()が記録されたことの確認
    redis_client.reset_circuit_breaker()
