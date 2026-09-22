"""`infrastructure/redis_client.py`——共有クライアントと、障害後のクールダウン。

ここで見ないもの:
- cache-asideの骨格（可用性チェック→取得→成否記録）を各所が写経していないこと
  → `tests/structure/test_redis_skeleton.py`
- 障害時に利用側がどう劣化するか → `test_jma_tile_redis_cache.py`等、各利用側

**実Redisへ繋がない。** `redis.from_url()`はクライアントを組み立てるだけで、接続は最初の
コマンドまで張られない。クールダウンの経過は時計を差し替えて進める（待たない）。
"""

import pytest

from app.config import settings
from app.infrastructure import redis_client


class _Clock:
    def __init__(self, now: float):
        self.now = now

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    """モジュールが読む時計。`now`へ代入すると、その時刻から見た判定になる。"""
    fake = _Clock(1000.0)
    monkeypatch.setattr(redis_client, "time", fake)
    return fake


def test_client_is_built_once_per_process(monkeypatch):
    """呼ぶたびに作ると、タイル1枚ごとに接続プールが増える。"""
    monkeypatch.setattr(redis_client, "_client", None)

    client = redis_client.get_redis_client_or_none()
    assert client is not None
    assert redis_client.get_redis_client_or_none() is client


def test_unusable_url_yields_none_instead_of_raising(monkeypatch):
    """設定ミスで送出される例外をここで止める。素通しすると、キャッシュを引こうとした
    タイル配信・ルート生成ごと落ちる（利用側のtry/exceptはコマンドの周りにしか無い）。"""
    monkeypatch.setattr(redis_client, "_client", None)
    monkeypatch.setattr(settings, "redis_url", "not-a-url")

    assert redis_client.get_redis_client_or_none() is None
    assert not redis_client.redis_available()


def test_available_until_a_failure_is_recorded(clock):
    assert redis_client.redis_available()

    redis_client.record_redis_failure()
    assert not redis_client.redis_available()


def test_cooldown_reopens_the_circuit_at_the_boundary(clock):
    """短すぎると障害中のRedisへ毎回取りに行って待ち時間を積む。長すぎると復旧後も
    キャッシュが効かないまま外部APIを叩き続ける。"""
    redis_client.record_redis_failure()
    cooldown = redis_client._CIRCUIT_COOLDOWN_SECONDS

    clock.now += cooldown - 0.1
    assert not redis_client.redis_available()

    clock.now += 0.1
    assert redis_client.redis_available()


def test_success_reopens_the_circuit_without_waiting(clock):
    redis_client.record_redis_failure()
    redis_client.record_redis_success()

    assert redis_client.redis_available()
