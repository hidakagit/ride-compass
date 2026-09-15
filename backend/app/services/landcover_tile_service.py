"""土地被覆ラスタタイル（`GET /api/region/landcover-tiles/...`）の配信。

描画そのものは`infrastructure/landcover_raster.py`が行い、ここはキャッシュ確認・
書き込み（路面/POI/事故タイルと共通の`services/tile_serving.py`の骨格）と、
配信できる状態かどうかの判断だけを持つ。

描画はGDAL側の同期I/Oのため`asyncio.to_thread`へ逃がす（イベントループを止めると、
同時に処理中のルート生成まで詰まる）。
"""

import asyncio
import logging

from app.domain.landcover import LANDCOVER_CLASSES
from app.infrastructure import landcover_raster
from app.infrastructure.cache_identity import LANDCOVER_REVISION, cache_identity
from app.services.tile_serving import TileResponse, serve_cached_tile

logger = logging.getLogger("ridecompass.landcover_tile")

PNG_CONTENT_TYPE = "image/png"

#: タイルURL・ディスクキャッシュのパスへ入る世代。
LANDCOVER_TILE_VERSION = cache_identity(LANDCOVER_REVISION, LANDCOVER_CLASSES)

_EMPTY_TILE = landcover_raster.empty_tile_png()


def _tile_cache_path(z: int, x: int, y: int) -> str:
    return f"region/landcover/v{LANDCOVER_TILE_VERSION}/{z}/{x}/{y}.png"


async def get_landcover_tile(z: int, x: int, y: int) -> TileResponse | None:
    """タイル1枚を返す。ラスタが1枚も無ければNone（設定の問題で、範囲外とは区別する）。"""
    if not await asyncio.to_thread(landcover_raster.has_sources):
        logger.warning(
            "土地被覆ラスタが未設定のためタイルを配信できません"
            "（環境変数LULC_RASTER_PATHS、docs/disaster-recovery.md参照） z=%s x=%s y=%s",
            z,
            x,
            y,
        )
        return None

    async def fetch_tile(_fields: dict) -> bytes | None:
        return await asyncio.to_thread(landcover_raster.render_tile, z, x, y)

    return await serve_cached_tile(
        z=z,
        x=x,
        y=y,
        cache_path=_tile_cache_path(z, x, y),
        empty_tile=_EMPTY_TILE,
        content_type=PNG_CONTENT_TYPE,
        external_call_name="landcover-tile",
        fetch_tile=fetch_tile,
        source_label="raster",
    )
