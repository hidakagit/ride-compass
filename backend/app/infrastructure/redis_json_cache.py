"""RedisへJSONで持つcache-asideの共通骨格。

呼び出し元が持つのはキー設計・TTL・値の意味づけだけで、可用性チェックから
サーキットブレーカーへの記録までをここが引き受ける。
"""

import json
from typing import Any

from app.infrastructure.debug_log import error_type_label, log_external_call
from app.infrastructure.redis_client import (
    get_redis_client_or_none,
    record_redis_failure,
    record_redis_success,
    redis_available,
)


def _client_or_none():
    """サーキットブレーカーが開いている間は接続自体を試さない。"""
    return get_redis_client_or_none() if redis_available() else None


async def get_json(key: str, *, category: str, **log_fields: Any) -> Any | None:
    """キーに対応するJSONを返す。未保存・Redis障害・壊れたエントリはいずれもNone。

    `category`は`log_external_call`のカテゴリ（`/api/debug/stats`の集計単位）。
    """
    client = _client_or_none()
    if client is None:
        return None
    with log_external_call(category, **log_fields) as fields:
        try:
            raw = await client.get(key)
        except Exception as exc:  # noqa: BLE001 Redis障害は「未キャッシュ」へのfail-open対象
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        record_redis_success()
        fields["result"] = "ok"
        fields["cache"] = "hit" if raw is not None else "miss"
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            # 壊れたエントリ（フォーマット変更等）は未キャッシュ扱いにする。
            fields["cache"] = "miss"
            return None


async def set_json(key: str, value: Any, *, ttl_seconds: int, category: str, **log_fields: Any) -> None:
    """値をJSONで保存する。Redis障害時は黙って諦める（呼び出し元は成否を気にしない）。"""
    client = _client_or_none()
    if client is None:
        return
    with log_external_call(category, **log_fields) as fields:
        try:
            await client.set(key, json.dumps(value), ex=ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return
        record_redis_success()
        fields["result"] = "ok"
