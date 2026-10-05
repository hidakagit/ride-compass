"""`infrastructure/redis_client.py`——Redisの共有クライアント（文字列・生のバイト列）と、共有のサーキットブレーカー。

クライアントはプロセス大域に1つずつ作られるので、テストごとに閉じる口（`close_redis_clients`）で作る前の状態に戻してから始め、同じ口で閉じる。
接続先は`config.py: settings`の`redis_url`を差し替えて与える。Redisの代わりに、接続を受けて何も答えない
手元のソケットを立てる（待ちの上限は、答えない相手にしか現れない）。ブレーカーは
`tests/conftest.py`のautouseが閉じた状態から始め、時計は`clock`で進める。

ここで見ないもの:
- ブレーカーが開いている間にRedisを呼ばずに未キャッシュへ進むこと・失敗と成功を記録する時機
  → `test_redis_json_cache.py`（`jma_amedas_store.py`が自前で持つ骨格の分は、そのモジュールの入口のテスト）
"""

import asyncio
import time

import pytest
import redis.exceptions

from app.config import settings
from app.infrastructure import redis_client
from app.infrastructure.redis_client import CIRCUIT_COOLDOWN_SECONDS

CLIENTS = [redis_client.get_redis_client_or_none, redis_client.get_redis_binary_client_or_none]


@pytest.fixture
async def no_clients_yet():
    await redis_client.close_redis_clients()
    yield
    await redis_client.close_redis_clients()


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
@pytest.mark.parametrize("get_client", CLIENTS)
def test_a_malformed_url_gives_no_client_and_opens_the_shared_breaker(monkeypatch, get_client):
    """設定の誤りで落ちず、未キャッシュで進める。"""
    monkeypatch.setattr(settings, "redis_url", "not-a-redis-url")

    assert get_client() is None
    assert not redis_client.redis_available()


@pytest.mark.usefixtures("silent_redis")
def test_each_kind_of_client_is_built_once():
    text_client, binary_client = (get_client() for get_client in CLIENTS)

    assert redis_client.get_redis_client_or_none() is text_client
    assert redis_client.get_redis_binary_client_or_none() is binary_client
    assert text_client is not binary_client


@pytest.mark.usefixtures("silent_redis")
def test_the_text_client_decodes_values_and_the_binary_client_keeps_bytes():
    text_client, binary_client = (get_client() for get_client in CLIENTS)

    assert text_client.get_encoder().decode(b"value") == "value"
    assert binary_client.get_encoder().decode(b"value") == b"value"


@pytest.mark.usefixtures("silent_redis")
@pytest.mark.parametrize("get_client", CLIENTS)
async def test_a_redis_that_does_not_answer_fails_within_a_second(get_client):
    """疎通しないRedisで数秒待つと、ルート生成やタイル配信の応答がその分だけ遅れる。"""
    started = time.monotonic()

    with pytest.raises(redis.exceptions.TimeoutError):
        await get_client().ping()

    assert time.monotonic() - started < 1.0
