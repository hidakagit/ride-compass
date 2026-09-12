"""JMA動的タイルの在否インデックス（どのタイルに描くものがあるか）。

JMA動的タイルは疎で、平常時はほぼ全てのタイルが空である。にもかかわらずクライアントは
中身の有無を知らないまま画面内の全タイルを要求し、平常時は取得のほぼ全部が空タイルに
費やされる。`basetime`が10分ごとに変わりURLも変わるため、ブラウザキャッシュ
（`api/cache_policy.py`）では救えない。

`jma_tile_prewarm_service.py`が運用範囲のタイルを10分ごとに取得する過程で在否を判定し、
ここへ記録する。クライアントは`GET /api/jma-tile-index`で1回受け取り、インデックスに
無いタイルは要求しない。

**正本を持たないキャッシュ**: 失っても機能は壊れない（インデックスが無ければクライアントは
従来どおり全タイルを取りに行くだけ）。Redisとのやり取りは`redis_json_cache`の共通骨格へ
委ね、このモジュールはキー設計・TTLだけを持つ（在否の判定自体は`jma_tile_content.py`）。
"""

from app.infrastructure.redis_json_cache import get_json, set_json

__all__ = ["get_index", "set_index"]

_LOG_CATEGORY = "cache:jma-tile-index"
# 要素ごとに`basetime`が異なる（risk系・nowc系・rasrf系で別々に更新される）ため、
# `basetime`をキーに含めず「最新の1つ」を固定キーで持ち、どの`basetime`に対する在否かは
# ペイロード側の要素ごとに持たせる。クライアントは自分が描こうとしている`basetime`と
# 一致する要素についてだけインデックスを使う。
_LATEST_KEY = "jma:tile-index:latest"
# プリウォーム間隔（10分）より長く取り、1回の遅延で即座に空にならないようにする
# （`jma_tile_redis_cache.py`のタイル本体TTLと同じ考え方）。
_TTL_SECONDS = 20 * 60


async def set_index(payload: dict) -> None:
    """最新のインデックス全体を保存する。"""
    await set_json(_LATEST_KEY, payload, ttl_seconds=_TTL_SECONDS, category=_LOG_CATEGORY, operation="set")


async def get_index() -> dict | None:
    """保存済みインデックス。未保存・Redis障害時はNone（クライアントは従来どおり全タイルを
    取りに行く）。"""
    return await get_json(_LATEST_KEY, category=_LOG_CATEGORY, operation="get")
