"""Redisへ持つcache-asideの共通骨格（JSONと生のバイト列）。

呼び出し元が持つのはキー設計・TTL・値の意味づけだけで、可用性チェックから
サーキットブレーカーへの記録までをここが引き受ける。
"""

import json
from collections.abc import Callable
from typing import Any

import redis.asyncio as redis

from app.infrastructure.debug_log import log_external_call, mark_failed
from app.infrastructure.redis_client import (
    get_redis_binary_client_or_none,
    get_redis_client_or_none,
    record_redis_failure,
    record_redis_success,
    redis_available,
)


def _client_or_none(connect: Callable[[], redis.Redis | None]) -> redis.Redis | None:
    """サーキットブレーカーが開いている間は接続自体を試さない。"""
    return connect() if redis_available() else None


async def _get(
    key: str,
    connect: Callable[[], redis.Redis | None],
    decode: Callable[[Any], Any | None],
    category: str,
    log_fields: dict[str, Any],
) -> Any | None:
    """`decode`がNoneを返したエントリ（壊れた・形の違う値）は未キャッシュ扱いにし、missとして記録する。"""
    client = _client_or_none(connect)
    if client is None:
        return None
    with log_external_call(category, **log_fields) as fields:
        try:
            raw = await client.get(key)
        except Exception as exc:  # noqa: BLE001 Redis障害は「未キャッシュ」へのfail-open対象
            record_redis_failure()
            mark_failed(fields, exc)
            return None
        record_redis_success()
        fields["result"] = "ok"
        value = None if raw is None else decode(raw)
        fields["cache"] = "hit" if value is not None else "miss"
        return value


async def _set(
    key: str,
    value: str | bytes,
    connect: Callable[[], redis.Redis | None],
    ttl_seconds: int,
    category: str,
    log_fields: dict[str, Any],
) -> None:
    client = _client_or_none(connect)
    if client is None:
        return
    with log_external_call(category, **log_fields) as fields:
        try:
            await client.set(key, value, ex=ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            record_redis_failure()
            mark_failed(fields, exc)
            return
        record_redis_success()
        fields["result"] = "ok"


async def get_json(key: str, *, category: str, **log_fields: Any) -> Any | None:
    """キーに対応するJSONを返す。未保存・Redis障害・壊れたエントリはいずれもNone。

    `category`は`log_external_call`のカテゴリ（`/api/debug/stats`の集計単位）。
    """
    return await _get(key, get_redis_client_or_none, _json_or_none, category, log_fields)


def _json_or_none(raw: str) -> Any | None:
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def set_json(key: str, value: Any, *, ttl_seconds: int, category: str, **log_fields: Any) -> None:
    """値をJSONで保存する。Redis障害時は黙って諦める（呼び出し元は成否を気にしない）。"""
    await _set(key, json.dumps(value), get_redis_client_or_none, ttl_seconds, category, log_fields)


async def get_bytes(
    key: str, *, decode: Callable[[bytes], Any | None], category: str, **log_fields: Any
) -> Any | None:
    """キーに対応するバイト列を文字列へデコードせずに`decode`へ渡し、その結果を返す。
    未保存・Redis障害・`decode`がNoneを返したエントリはいずれもNone。"""
    return await _get(key, get_redis_binary_client_or_none, decode, category, log_fields)


async def set_bytes(key: str, value: bytes, *, ttl_seconds: int, category: str, **log_fields: Any) -> None:
    """バイト列をそのまま保存する。Redis障害時は黙って諦める。"""
    await _set(key, value, get_redis_binary_client_or_none, ttl_seconds, category, log_fields)
