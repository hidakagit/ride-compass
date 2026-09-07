"""RedisへJSONで持つcache-asideの共通骨格。

「Redisが使えるか確認 → クライアント取得 → `log_external_call`で計測 → 失敗は握り潰して
未キャッシュ扱い（fail-open）→ 成否をサーキットブレーカーへ記録」という手順は、Redisを
使うキャッシュすべてに共通する定型文である。`simple_api_client.py: cached_fetch`が
プロセス内`TTLCache`側で同じ重複を1箇所へまとめているのと同じことを、Redis側で行う。

**fail-openが前提**: ここが扱うのはいずれも正本を持たないキャッシュで、失っても再取得
すれば済む。Redis障害・接続不能・壊れたエントリはすべて「未キャッシュ」（`get`はNone）へ
倒し、呼び出し元が通常の取得経路へ進めるようにする——キャッシュの不調でアプリの機能を
止めない。

呼び出し元はキー設計とTTLの決定、値の意味づけだけを持つ。
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


async def get_json(key: str, *, category: str, **log_fields: Any) -> Any | None:
    """キーに対応するJSONを返す。未保存・Redis障害・壊れたエントリはいずれもNone。

    `category`は`log_external_call`のカテゴリ（`/api/debug/stats`の集計単位）。
    """
    if not redis_available():
        return None
    client = get_redis_client_or_none()
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
    if not redis_available():
        return
    client = get_redis_client_or_none()
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
