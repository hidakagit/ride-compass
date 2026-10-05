"""`infrastructure/redis_client.py`——Redisの共有クライアントと、サーキットブレーカー。

クライアントはプロセス大域に1つ作られるので、テストごとに閉じる口（`close_redis_client`）で作る前の状態に戻してから始め、同じ口で閉じる。
接続先は`config.py: settings`の`redis_url`を差し替えて与える。Redisの代わりに、接続を受けて何も答えない
手元のソケットを立てる（待ちの上限は、答えない相手にしか現れない）。ブレーカーは
`tests/conftest.py`のautouseが閉じた状態から始め、時計は`clock`で進める。

ここで見ないもの:
- ブレーカーが開いている間にRedisを呼ばずに未キャッシュへ進むこと・失敗と成功を記録する時機・値を文字列へ
  デコードしないこと → `test_redis_json_cache.py`
"""

import asyncio
import logging
import time

import pytest
import redis.exceptions

from app.config import settings
from app.infrastructure import redis_client
from app.infrastructure.redis_client import CIRCUIT_COOLDOWN_SECONDS

@pytest.fixture
async def no_clients_yet():
    await redis_client.close_redis_client()
    yield
    await redis_client.close_redis_client()


@pytest.fixture
async def silent_redis(monkeypatch, no_clients_yet):
    """接続は受けるが、コマンドに何も答えないRedisの宛先。"""
    accepted: list[asyncio.StreamWriter] = []

    async def hold(_reader, writer):
        accepted.append(writer)

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(settings, "redis_url", f"redis://127.0.0.1:{port}/0")
    yield
    for writer in accepted:
        writer.close()
    server.close()
    await server.wait_closed()


def test_after_a_failure_redis_is_skipped_until_the_cooldown_has_passed(clock):
    redis_client.record_redis_failure()
    assert not redis_client.redis_available()

    clock.tick(CIRCUIT_COOLDOWN_SECONDS - 1)
    assert not redis_client.redis_available()

    clock.tick(1)
    assert redis_client.redis_available()


def test_a_success_closes_the_breaker_at_once():
    redis_client.record_redis_failure()

    redis_client.record_redis_success()

    assert redis_client.redis_available()


@pytest.mark.usefixtures("no_clients_yet")
def test_a_malformed_url_gives_no_client_opens_the_breaker_and_warns(monkeypatch, caplog):
    """設定の誤りで落ちず、未キャッシュで進める。誤りは警告で出す——黙って未キャッシュで進むと、どのキャッシュも効かないまま気づけない。"""
    monkeypatch.setattr(settings, "redis_url", "not-a-redis-url")

    with caplog.at_level(logging.WARNING):
        assert redis_client.get_redis_client_or_none() is None

    assert not redis_client.redis_available()
    assert "Redis" in caplog.text


@pytest.mark.usefixtures("silent_redis")
def test_the_client_is_built_once():
    assert redis_client.get_redis_client_or_none() is redis_client.get_redis_client_or_none()


@pytest.mark.usefixtures("silent_redis")
async def test_a_redis_that_does_not_answer_fails_within_a_second():
    """疎通しないRedisで数秒待つと、ルート生成やタイル配信の応答がその分だけ遅れる。"""
    started = time.monotonic()

    with pytest.raises(redis.exceptions.TimeoutError):
        await redis_client.get_redis_client_or_none().ping()

    assert time.monotonic() - started < 1.0
