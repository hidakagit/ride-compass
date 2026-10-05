"""土地被覆ラスタタイルの配信。

描画はGDAL側の同期I/Oのため`asyncio.to_thread`へ逃がす（イベントループを止めると、
同時に処理中のルート生成まで詰まる）。
"""

import asyncio

from app.config import settings
from app.infrastructure import landcover_raster
from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.media_types import PNG_CONTENT_TYPE
from app.infrastructure.region_tile_cache import (
    LANDCOVER_TILE_KIND,
    TileResponse,
    landcover_generation,
    serve_region_tile,
)

_CATEGORY = "region:landcover-tile"

_EMPTY_TILE = landcover_raster.empty_tile_png()


def _log_unavailable() -> None:
    configured = settings.lulc_raster_paths_list
    # 原因を決め打ちしない。未設定と「設定はあるが開けない」は対処が違う
    # （前者は環境変数、後者はファイルの配置・権限・壊れたGeoTIFF）。
    cause = (
        "環境変数LULC_RASTER_PATHSが未設定です"
        if not configured
        else f"設定された{len(configured)}件のいずれも開けません（配置・権限・ファイルの中身を確認）"
    )
    log_throttled_warning(_CATEGORY, "土地被覆タイルを配信できません: %s", cause)


async def get_landcover_tile(z: int, x: int, y: int) -> TileResponse | None:
    """タイル1枚を返す。ラスタが1枚も無ければNone（設定の問題で、範囲外とは区別する）。"""
    if not await asyncio.to_thread(landcover_raster.has_sources):
        _log_unavailable()
        return None

    async def fetch_tile(_fields: dict) -> bytes | None:
        return await asyncio.to_thread(landcover_raster.render_tile, z, x, y)

    return await serve_region_tile(
        kind=LANDCOVER_TILE_KIND,
        generation=landcover_generation(),
        z=z,
        x=x,
        y=y,
        extension="png",
        empty_tile=_EMPTY_TILE,
        content_type=PNG_CONTENT_TYPE,
        external_call_name=_CATEGORY,
        fetch_tile=fetch_tile,
        source_label="raster",
    )
