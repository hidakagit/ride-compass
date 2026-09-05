"""JMA動的タイル（ラスタPNG・洪水ベクタPBF）本体のRedis cache-aside（改善計画T510）。

以前は`tile_cache.py`（ファイル永続キャッシュ、有効期限なし）を使っていたが、キャッシュ
ヒットしていても`jma_tile.py`のレート制限は消費される作りだったため（T510の直接の
発端）、キャッシュヒット率をレート制限の判定より前に確定させる必要があった。ファイル
キャッシュはTTLの概念を持たず古いbasetime/validtimeのタイルが無期限に残り続けるため、
Redis（`wind_forecast_cache.py`と同じ「正本を持たないcache-aside」設計、TTL付き）へ
移した。

**正本を持たない**: road_graph_tile_cache.pyと異なり、このキャッシュを失っても
「データ未整備で機能が壊れる」ことはない（JMAへ再フェッチすればよいだけ）。Redis障害時は
`jma_tile_client.py`側が単に「未キャッシュ」として扱い実フェッチへ進むfail-open。

**バイナリの扱い**: `redis_client.py`は`decode_responses=True`（文字列前提）のため、
PNG/PBFの生バイト列をそのまま保存できない。base64エンコードした文字列をJSONへ包んで
1キーに保存する（`wind_forecast_cache.py`のJSON文字列パターンを踏襲）。
"""

import base64
import json

from app.infrastructure.debug_log import error_type_label, log_external_call
from app.infrastructure.redis_client import (
    get_redis_client_or_none,
    record_redis_failure,
    record_redis_success,
    redis_available,
)
from app.infrastructure.tile_cache import cache_key

_KEY_PREFIX = "jma:tile"
# プリウォーム間隔（jma_tile_prewarm_service.py、10分）より余裕を持たせ、1回のプリウォーム
# 失敗・遅延で即座に空にならないようにする。
_TTL_SECONDS = 20 * 60


class TileNotFound:
    """指定パスのタイルが上流（JMA）に存在しないこと（404）を確認済みというキャッシュ済みの
    事実を表すセンチネル（改善計画T605、`elevation_client.py: _CoverageGap`と同じ設計）。
    降水・浸水想定区域等の疎な格子状タイルでは、特定のz/x/yに対応するデータが無いのは
    珍しくない正常系だが、basetime/validtimeが確定した過去の一時点に対する結果のため
    再フェッチしても変わらない。実際のタイル内容と同じキー・TTLで保持し、次回以降は
    上流へ問い合わせず即座に返せるようにする。"""


TILE_NOT_FOUND = TileNotFound()


def _key(path: str) -> str:
    return f"{_KEY_PREFIX}:{cache_key(path)}"


async def get(path: str) -> tuple[bytes, str] | TileNotFound | None:
    """Redisキャッシュ済みなら(内容, Content-Type)または`TILE_NOT_FOUND`を返す。
    未キャッシュ・Redis障害時はNone（呼び出し元は通常のオンデマンドフェッチへ
    フォールバックする）。"""
    if not redis_available():
        return None
    client = get_redis_client_or_none()
    if client is None:
        return None
    with log_external_call("cache:jma-tile-redis", path=path) as fields:
        try:
            raw = await client.get(_key(path))
        except Exception as exc:  # noqa: BLE001 Redis障害は「未キャッシュ」へのfail-open対象
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        record_redis_success()
        if raw is None:
            fields["result"] = "ok"
            fields["cache"] = "miss"
            return None
        try:
            payload = json.loads(raw)
            if payload.get("not_found"):
                fields["result"] = "ok"
                fields["cache"] = "hit"
                return TILE_NOT_FOUND
            content = base64.b64decode(payload["body_b64"])
            content_type = payload["content_type"]
        except (ValueError, TypeError, KeyError):
            # 壊れたエントリ（フォーマット変更等）は未キャッシュ扱いにする。
            fields["result"] = "ok"
            fields["cache"] = "miss"
            return None
        fields["result"] = "ok"
        fields["cache"] = "hit"
        return content, content_type


async def set(path: str, content: bytes, content_type: str) -> None:
    """取得できたタイルをRedisへ書き戻す（キャッシュの最適化であり、書き込み失敗は
    応答自体の成否に関与しない）。"""
    if not redis_available():
        return
    client = get_redis_client_or_none()
    if client is None:
        return
    with log_external_call("cache:jma-tile-redis", path=path) as fields:
        payload = json.dumps({"content_type": content_type, "body_b64": base64.b64encode(content).decode("ascii")})
        try:
            await client.set(_key(path), payload, ex=_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 書き込み失敗は次回フェッチで自己修復する
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
        else:
            record_redis_success()
            fields["result"] = "ok"


async def set_not_found(path: str) -> None:
    """上流の404（疎な格子状タイルでは珍しくない正常系）を確認したときに呼ぶ。`set()`と
    同じTTL・fail-open方針で、次回以降の問い合わせを`TILE_NOT_FOUND`で即座に済ませられる
    ようにする（改善計画T605）。"""
    if not redis_available():
        return
    client = get_redis_client_or_none()
    if client is None:
        return
    with log_external_call("cache:jma-tile-redis", path=path) as fields:
        payload = json.dumps({"not_found": True})
        try:
            await client.set(_key(path), payload, ex=_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 書き込み失敗は次回フェッチで自己修復する
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
        else:
            record_redis_success()
            fields["result"] = "ok"
