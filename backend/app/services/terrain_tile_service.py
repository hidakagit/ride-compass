"""地理院の標高タイルを、MapLibreの`raster-dem`が読むTerrain-RGBにして配る。

変換後のタイルはキャッシュしない。ネットワークを使うのは変換前のタイルの取得だけで、そちらは
`GsiTileClient`がディスクへ持つ。変換自体はタイル1枚ぶんの配列演算とPNGの書き出しで、
同じものを二重にディスクへ置くだけの価値は無い。
"""

import asyncio

from app.domain.gsi_tiles import TERRAIN_UPSTREAM_PATH
from app.domain.terrain_rgb import gsi_dem_png_to_terrain_rgb
from app.infrastructure.gsi_tile_client import GsiTileClient, GsiTileNotFound

PNG_CONTENT_TYPE = "image/png"


async def get_terrain_rgb_tile(client: GsiTileClient, z: int, x: int, y: int) -> bytes | GsiTileNotFound | None:
    result = await client.get(TERRAIN_UPSTREAM_PATH.format(z=z, x=x, y=y))
    if isinstance(result, GsiTileNotFound) or result is None:
        return result
    content, _ = result
    # 配列演算とPNGの書き出しはCPUを掴む。同時に多数のタイルが来るため、
    # イベントループの外へ逃がす（gsi_tile_client.pyのディスクI/Oと同じ理由）。
    return await asyncio.to_thread(gsi_dem_png_to_terrain_rgb, content)
