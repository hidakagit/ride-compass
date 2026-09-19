"""土地被覆ラスタタイル（`GET /api/region/landcover-tiles/...`）の配信。

描画そのものは`infrastructure/landcover_raster.py`が行い、ここはキャッシュ確認・
書き込み（路面/POI/事故タイルと共通の`services/tile_serving.py`の骨格）と、
配信できる状態かどうかの判断だけを持つ。

描画はGDAL側の同期I/Oのため`asyncio.to_thread`へ逃がす（イベントループを止めると、
同時に処理中のルート生成まで詰まる）。
"""

import asyncio
import logging
import time

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
#: 生成物がビルド機の設定で決まり、本番の実際の構成とずれる。**実際に開けている**ラスタ
#: 構成への追随はサーバー側のディスクキャッシュ（`_tile_cache_path`）で行い、ブラウザ側は
#: `cache_policy.py`が`immutable`を付けないことで再検証できるようにしてある。
LANDCOVER_TILE_VERSION = cache_identity(LANDCOVER_REVISION, LANDCOVER_CLASSES)

_EMPTY_TILE = landcover_raster.empty_tile_png()


def _tile_cache_path(z: int, x: int, y: int) -> str:
    """ディスクキャッシュのパス。**実際に開けているラスタの構成**も鍵に入れる。

    タイルの中身はどのラスタを開いていたかに従属する。対応範囲を広げるためゾーンを1枚
    足しても鍵が同じだと、継ぎ目のタイルは古い絵（片側が透明のまま）を返し続ける。
    設定された一覧ではなく開けている一覧を使うのは、**起動時に1枚だけ置かれていなかった
    場合も同じことが起きる**ため——そのとき設定の側で鍵を作ると、欠けたゾーンの透明な絵が
    「完全な構成」の鍵で恒久的に残る。
    """
    raster_set = raster_set_fingerprint(landcover_raster.opened_raster_paths())
    return f"region/landcover/v{LANDCOVER_TILE_VERSION}/{raster_set}/{z}/{x}/{y}.png"


#: 「配信できない」警告を出す間隔（秒）。タイル1枚ごとに出すと、地図を1画面開くだけで
#: 数十行・利用者数ぶん積み上がり、他のログが読めなくなる。状態はタイルごとに変わらない
#: （ラスタが無いのは配信全体の状態）ため、1枚ごとに出す意味が無い。
_UNAVAILABLE_LOG_INTERVAL_SECONDS = 60.0
_last_unavailable_log = 0.0


def _log_unavailable_once_in_a_while() -> None:
    global _last_unavailable_log
    now = time.monotonic()
    if now - _last_unavailable_log < _UNAVAILABLE_LOG_INTERVAL_SECONDS:
        return
    _last_unavailable_log = now
    configured = settings.lulc_raster_paths_list
    # 原因を決め打ちしない。未設定と「設定はあるが開けない」は対処が違う
    # （前者は環境変数、後者はファイルの配置・権限・壊れたGeoTIFF）。
    cause = (
        "環境変数LULC_RASTER_PATHSが未設定です"
        if not configured
        else f"設定された{len(configured)}件のいずれも開けません（配置・権限・ファイルの中身を確認）"
    )
    logger.warning(
        "土地被覆タイルを配信できません: %s（docs/disaster-recovery.md参照）", cause
    )


async def get_landcover_tile(z: int, x: int, y: int) -> TileResponse | None:
    """タイル1枚を返す。ラスタが1枚も無ければNone（設定の問題で、範囲外とは区別する）。"""
    if not await asyncio.to_thread(landcover_raster.has_sources):
        _log_unavailable_once_in_a_while()
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
