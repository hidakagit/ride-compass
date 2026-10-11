"""Redisへ持つcache-asideの共通骨格（JSON・生のバイト列・Hash）。

呼び出し元が持つのはキー設計・TTL・値の意味づけだけで、可用性の確認・クライアント取得・
`log_external_call`での計測・失敗を未キャッシュ扱いにする・サーキットブレーカーへの記録をここが引き受ける。
値がバイナリなら`get_bytes`/`set_bytes`を使う（base64にしてJSONへ包まない）。キーごとの項目をまとめて書くなら、
Hashの`get_hash`/`set_hashes`（pipelineで1往復）を使う。

    value = await get_json(key, category="cache:xxx")            # ミスはNone・障害はUNAVAILABLE
    await set_json(key, payload, ttl_seconds=TTL, category="cache:xxx")
"""

import json
from collections.abc import Awaitable, Callable, Mapping
from enum import Enum
from typing import Any, Literal, cast

import redis.asyncio as redis

from app.infrastructure.debug_log import log_external_call, mark_failed
from app.infrastructure.redis_client import (
    get_redis_client_or_none,
    record_redis_failure,
    record_redis_success,
    redis_available,
)


class Unavailable(Enum):
    """読みの口が返す「取れない」（冷却中・接続を作れない・コマンドの失敗）。保存なし（None）とは分ける——
    保存なしなら取り直して書けばよいが、取れない間に取り直すと、上流へ同じ問い合わせを繰り返す。"""

    UNAVAILABLE = "unavailable"


UNAVAILABLE: Literal[Unavailable.UNAVAILABLE] = Unavailable.UNAVAILABLE


def _client_or_none() -> redis.Redis | None:
    """サーキットブレーカーが開いている間は接続自体を試さない。"""
    return get_redis_client_or_none() if redis_available() else None


async def _get(
    read: Callable[[redis.Redis], Awaitable[Any]],
    decode: Callable[[Any], Any | None],
    category: str,
    log_fields: dict[str, Any],
) -> Any | None | Unavailable:
    """`read`は保存が無ければNoneを返す。`decode`がNoneを返したエントリ（壊れた・形の違う値）は未キャッシュ扱いにし、
    missとして記録する。"""
    client = _client_or_none()
    if client is None:
        return UNAVAILABLE
    with log_external_call(category, **log_fields) as fields:
        try:
            raw = await read(client)
        except Exception as exc:  # noqa: BLE001 Redis障害は「取れない」へのfail-open対象
            record_redis_failure()
            mark_failed(fields, exc)
            return UNAVAILABLE
        record_redis_success()
        fields["result"] = "ok"
        value = None if raw is None else decode(raw)
        fields["cache"] = "hit" if value is not None else "miss"
        return value


async def _set(
    write: Callable[[redis.Redis], Awaitable[Any]],
    category: str,
    log_fields: dict[str, Any],
) -> None:
    client = _client_or_none()
    if client is None:
        return
    with log_external_call(category, **log_fields) as fields:
        try:
            await write(client)
        except Exception as exc:  # noqa: BLE001
            record_redis_failure()
            mark_failed(fields, exc)
            return
        record_redis_success()
        fields["result"] = "ok"


async def get_json(key: str, *, category: str, **log_fields: Any) -> Any | None | Unavailable:
    """キーに対応するJSONを返す。未保存・壊れたエントリはNone、Redisを呼べない・失敗したときは`UNAVAILABLE`。

    `category`は`log_external_call`のカテゴリ（`/api/debug/stats`の集計単位）。
    """
    return await get_bytes(key, decode=_json_or_none, category=category, **log_fields)


def _json_or_none(raw: bytes) -> Any | None:
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def set_json(key: str, value: Any, *, ttl_seconds: int, category: str, **log_fields: Any) -> None:
    """値をJSONで保存する。Redis障害時は黙って諦める（呼び出し元は成否を気にしない）。"""
    await set_bytes(key, json.dumps(value).encode(), ttl_seconds=ttl_seconds, category=category, **log_fields)


async def get_bytes(
    key: str, *, decode: Callable[[bytes], Any | None], category: str, **log_fields: Any
) -> Any | None | Unavailable:
    """キーに対応するバイト列を文字列へデコードせずに`decode`へ渡し、その結果を返す。
    未保存・`decode`がNoneを返したエントリはNone、Redisを呼べない・失敗したときは`UNAVAILABLE`。"""
    return await _get(lambda client: client.get(key), decode, category, log_fields)


async def set_bytes(key: str, value: bytes, *, ttl_seconds: int, category: str, **log_fields: Any) -> None:
    """バイト列をそのまま保存する。Redis障害時は黙って諦める。"""
    await _set(lambda client: client.set(key, value, ex=ttl_seconds), category, log_fields)


async def get_hash(
    key: str, *, decode: Callable[[dict[bytes, bytes]], Any | None], category: str, **log_fields: Any
) -> Any | None | Unavailable:
    """キーのHashの全項目（項目名・値ともバイト列）を`decode`へ渡し、その結果を返す。
    未保存・`decode`がNoneを返したエントリはNone、Redisを呼べない・失敗したときは`UNAVAILABLE`。"""

    async def read(client: redis.Redis) -> dict[bytes, bytes] | None:
        # redis-pyは同期・非同期のクライアントで型を共有し、戻り値を`Awaitable[X] | X`と宣言している。
        fields = await cast(Awaitable[dict[bytes, bytes]], client.hgetall(key))
        return fields or None

    return await _get(read, decode, category, log_fields)


async def set_hashes(
    hashes: Mapping[str, Mapping[str, str]], *, ttl_seconds: int, category: str, **log_fields: Any
) -> None:
    """キーごとのHashを、TTLとともに1往復（pipeline）で書く。Redis障害時は黙って諦める。"""

    async def write(client: redis.Redis) -> None:
        pipe = client.pipeline(transaction=False)
        for key, mapping in hashes.items():
            pipe.hset(key, mapping=dict(mapping))
            pipe.expire(key, ttl_seconds)
        await pipe.execute()

    await _set(write, category, log_fields)
