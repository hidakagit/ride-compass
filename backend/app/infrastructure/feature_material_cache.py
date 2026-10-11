"""地図の配信が読む、タイル1枚ぶんのフィーチャーごとの材料（`domain/dynamic_way_values.py: FeatureMaterials`）と、フィーチャーごとの
区間の材料（`domain/dynamic_way_values.py: FeatureSegments`）のディスクキャッシュ。どちらを持つかは読み出しの形の署名で分かれる。

材料は軸の定義・走行方位・時刻に依らないので、鍵にそれらを入れない——どの軸の要求も同じタイルの材料を共有し、
軸スタジオで折れ点を変えてもキャッシュを捨てずに次の応答から効く。

キーは`(路面タイルの世代, 読み出しの形の署名, z, x, y)`。路面タイルの世代（`cache_identity.py: tile_version`）は
呼び出し側が必須キーワードで渡す（`surface_tile_version`。配信している路面タイルと同じ文字列）。材料の鍵は路面タイルの
`feature_key`と一字一句一致して初めて意味を持ち、派生の作り直しで同じSQLでも別の値になるため、形の署名だけでは
足りない。infrastructureから`services/tile_version_service.py`を読むと依存が逆向きになるため、ここでは受け取るだけにする。
読み出しの形の署名（`value_shape`）も呼び出し側が必須キーワードで渡す。

読まれなくなった世代のエントリはTTLで失効し、書き込みのたびに`diskcache`が失効したものを消す（容量上限の退避とは別に働く）。
"""

import asyncio

from typing import TypeVar

from app.domain.dynamic_way_values import FeatureMaterials, FeatureSegments
from app.infrastructure import tile_persistent_cache

_KEY_PREFIX = "featmat"

_Materials = TypeVar("_Materials", FeatureMaterials, FeatureSegments)

# 材料は派生の表と生データで決まり、それらが変われば鍵の路面タイルの世代が変わる。鮮度の制約が無いので、
# 失っても読み直すだけのものとして長く持ち、DBへの再問い合わせを抑える。
_TTL_SECONDS = 24 * 3600


def _key(z: int, x: int, y: int, surface_tile_version: str, value_shape: str) -> tuple:
    return (_KEY_PREFIX, surface_tile_version, value_shape, z, x, y)


async def get_tile_materials(
    z: int, x: int, y: int, *, surface_tile_version: str, value_shape: str, kind: type[_Materials]
) -> _Materials | None:
    """タイルの材料（`kind`の値）。未キャッシュ・読み出し失敗はいずれもNone（フィーチャーの無いタイルは0行の値で返る）。"""
    key = _key(z, x, y, surface_tile_version, value_shape)
    cached = await asyncio.to_thread(tile_persistent_cache.get_by_key, key)
    return cached if isinstance(cached, kind) else None


async def set_tile_materials(
    z: int, x: int, y: int, materials: FeatureMaterials | FeatureSegments, *, surface_tile_version: str, value_shape: str
) -> None:
    """新しく読んだタイルの材料をディスクへ書き戻す。"""
    key = _key(z, x, y, surface_tile_version, value_shape)
    await asyncio.to_thread(tile_persistent_cache.set_by_key, key, materials, expire=_TTL_SECONDS)
