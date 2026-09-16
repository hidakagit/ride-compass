"""土地被覆ラスタタイル（`GET /api/region/landcover-tiles/...`）の配信。

描画そのものは`infrastructure/landcover_raster.py`が行い、ここはキャッシュ確認・
書き込み（路面/POI/事故タイルと共通の`services/tile_serving.py`の骨格）と、
配信できる状態かどうかの判断だけを持つ。

描画はGDAL側の同期I/Oのため`asyncio.to_thread`へ逃がす（イベントループを止めると、
同時に処理中のルート生成まで詰まる）。
"""

import asyncio
import logging

from app.config import settings
from app.domain.landcover import LANDCOVER_CLASSES, raster_set_fingerprint
from app.infrastructure import landcover_raster
from app.infrastructure.cache_identity import LANDCOVER_REVISION, cache_identity
from app.services.tile_serving import TileResponse, serve_cached_tile

logger = logging.getLogger("ridecompass.landcover_tile")

PNG_CONTENT_TYPE = "image/png"

#: タイルURLへ入る世代（配色・クラス構成と手書きリビジョンから決まる）。
#:
#: **どのラスタを開いているかはここへ入れられない**。この値は生成物
#: （`region-tile-config.json`）を通してフロントのURLへ焼き込まれ、生成はビルド機で行う
#: ——ラスタの置き場所は環境変数（`LULC_RASTER_PATHS`）で環境ごとに違うため、入れると
#: 生成物がビルド機の設定で決まり、本番の実際の構成とずれる。ラスタ構成への追随は
#: サーバー側のディスクキャッシュ（`_tile_cache_path`）で行い、ブラウザ側は
#: `cache_policy.py`が`immutable`を付けないことで再検証できるようにしてある。
LANDCOVER_TILE_VERSION = cache_identity(LANDCOVER_REVISION, LANDCOVER_CLASSES)

_EMPTY_TILE = landcover_raster.empty_tile_png()


def _tile_cache_path(z: int, x: int, y: int) -> str:
    """ディスクキャッシュのパス。**開いているラスタの構成**も鍵に入れる。

    タイルの中身はどのラスタを開いていたかに従属する。対応範囲を広げるためゾーンを1枚
    足しても鍵が同じだと、継ぎ目のタイルは古い絵（片側が透明のまま）を返し続ける。
    """
    raster_set = raster_set_fingerprint(settings.lulc_raster_paths_list)
    return f"region/landcover/v{LANDCOVER_TILE_VERSION}/{raster_set}/{z}/{x}/{y}.png"


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
