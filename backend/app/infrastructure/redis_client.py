"""Redis共有クライアント（何をRedisへ置くかは docs/conventions/caching.md）。

すべての用途がTTL付きキャッシュ、またはPostGIS（正本）へ即座にフォールバック可能な
cache-asideのため、Redis接続自体の障害はfail-fastさせない。
"""

import time

import redis.asyncio as redis

from app.config import settings

_client: redis.Redis | None = None

# 接続確立・コマンド応答の待ち上限。既定値のままだと疎通不能時の1回の失敗検知に数秒かかる。
# Redisは常に同一ホスト（本番は`--network=host`）にあるため、正常時は決して到達しない
# 短い値へ絞れる。
_CONNECT_TIMEOUT_SECONDS = 0.2
_SOCKET_TIMEOUT_SECONDS = 0.2

_CIRCUIT_COOLDOWN_SECONDS = 10.0
_last_failure_at: float | None = None


def _get_redis_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            retry_on_timeout=False,
        )
    return _client


def get_redis_client_or_none() -> redis.Redis | None:
    """共有クライアント。取得できなければNone（呼び出し元は未キャッシュ扱いで進む）。

    `redis.from_url()`はURLスキーム不正（`settings.redis_url`の設定ミス）等で同期的に
    例外を送出する。呼び出し元のtry/exceptはRedisコマンドの周りにあり、クライアント生成
    自体の例外はその外で起きるため、ここで捕まえないとタイル配信・ルート生成ごと落ちる。
    """
    try:
        return _get_redis_client()
    except Exception:
        record_redis_failure()
        return None


def redis_available() -> bool:
    """直近のRedis障害からクールダウン期間を過ぎているか（＝呼び出す価値があるか）を返す。"""
    if _last_failure_at is None:
        return True
    return time.monotonic() - _last_failure_at >= _CIRCUIT_COOLDOWN_SECONDS


def record_redis_failure() -> None:
    global _last_failure_at
    _last_failure_at = time.monotonic()


def record_redis_success() -> None:
    global _last_failure_at
    _last_failure_at = None


def reset_circuit_breaker() -> None:
    """テスト用: サーキットブレーカーの状態をクリアする。"""
    global _last_failure_at
    _last_failure_at = None
