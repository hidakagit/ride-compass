"""Redis共有クライアント（何をRedisへ置くかは .claude/rules/caching.md）。

すべての用途がTTL付きキャッシュ、またはPostGIS（正本）へ即座にフォールバック可能な
cache-asideのため、Redis接続自体の障害はfail-fastさせない。
"""

import time

import redis.asyncio as redis

from app.config import settings
from app.infrastructure.debug_log import log_throttled_warning

_client: redis.Redis | None = None

# 接続確立・コマンド応答の待ち上限。既定値のままだと疎通不能時の1回の失敗検知に数秒かかる。
# Redisは常に同一ホスト（本番は`--network=host`）にあるため、正常時は決して到達しない
# 短い値へ絞れる。
_CONNECT_TIMEOUT_SECONDS = 0.2
_SOCKET_TIMEOUT_SECONDS = 0.2

CIRCUIT_COOLDOWN_SECONDS = 10.0
_last_failure_at: float | None = None
_CLIENT_CATEGORY = "cache:redis-client"


def get_redis_client_or_none() -> redis.Redis | None:
    """共有クライアント。値は生のバイト列で読み書きし、文字列（JSON等）は使う側がその場でデコードする。
    取得できなければNone（呼び出し元は未キャッシュ扱いで進む）。

    `redis.from_url()`はURLスキーム不正（`settings.redis_url`の設定ミス）等で同期的に
    例外を送出する。呼び出し元のtry/exceptはRedisコマンドの周りにあり、クライアント生成
    自体の例外はその外で起きるため、ここで捕まえないとタイル配信・ルート生成ごと落ちる。
    """
    global _client
    try:
        if _client is None:
            _client = redis.from_url(
                settings.redis_url,
                socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=_SOCKET_TIMEOUT_SECONDS,
                retry_on_timeout=False,
            )
        return _client
    except Exception as exc:  # noqa: BLE001 設定の誤りでも未キャッシュで進む
        record_redis_failure()
        log_throttled_warning(_CLIENT_CATEGORY, "Redisのクライアントを作れません error=%r", exc)
        return None


async def close_redis_client() -> None:
    """プロセス終了時に`process_resources.py: close_process_resources`から呼ぶ。次の取得で作り直す。"""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def redis_available() -> bool:
    """直近のRedis障害からクールダウン期間を過ぎているか（＝呼び出す価値があるか）を返す。"""
    if _last_failure_at is None:
        return True
    return time.monotonic() - _last_failure_at >= CIRCUIT_COOLDOWN_SECONDS


def record_redis_failure() -> None:
    global _last_failure_at
    _last_failure_at = time.monotonic()


def record_redis_success() -> None:
    global _last_failure_at
    _last_failure_at = None
