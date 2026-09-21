"""地理院の標高タイルのアダプタ。

**タイル1枚を1行**として返す。これで面のデータが点・線と同じ骨格に乗り、取込の経路を
分けずに済む。

**配信元は叩かない。**取りに行くのは`scripts/fetch_dem_tiles.py`の仕事で、ここは
`app/batch/dem_tile_store.py`が指す置き場にあるものを読む——取込のトランザクションの
中でHTTPを叩くと、関東全域（z15で約6万枚）では外部の一時的な失敗ひとつで全部が
やり直しになる。OSMの`.pbf`・土地被覆のGeoTIFFと同じく、取込はローカルのファイルを
読むだけにする。

標高をint32（0.01m単位）で並べ、`raster`として持つ。配信元はテキストで返すが、同じ
内容が数倍の大きさになるため詰める。位置・画素の大きさ・型・欠測値は`raster`の値自身が
持つので、読み手は`attrs`から形を組み立てない。

ズームは元データの分解能から決める——プロファイルが`zoom`を持ち、実装は持たない。
"""

import logging
import struct
from collections.abc import AsyncIterator
from typing import Any

import shapely
from shapely.geometry import box

from app.batch.dem_tile_store import PRODUCT_PRIORITY, TILE_ROOT, read_tile, stored_product
from app.batch.ingest import SourceRecord, register_adapter
from app.batch.source_adapters._raster_wkb import tile_raster_wkb
from app.batch.source_profile import SourceProfile, SourceSpec
from app.domain.region import BoundingBox, tiles_covering_bbox

logger = logging.getLogger("ridecompass.ingest.gsi_dem_tile")

#: 1枚の一辺の画素数。出典: https://maps.gsi.go.jp/development/demtile.html
DEM_TILE_SIZE = 256

#: 欠測を表す文字。「標高値が存在しない画素には「e」の文字が格納されている。」
#: 出典: https://maps.gsi.go.jp/development/demtile.html
DEM_MISSING_MARKER = "e"

#: 詰めるときの尺度と欠測値。地理院の標高タイル（テキスト形式）は「標高データは小数点
#: 第二位までデータとして入っている（単位はm）」ため、0.01m単位で丸めずに保つ。
#: 出典: https://maps.gsi.go.jp/development/demtile.html
#:
#: 型はint32。関東のbboxには富士山（3,776m）が入り、0.01m単位では377,600となって
#: int16（上限32,767＝3,276.7m）に収まらない。
SCALE = 100
NODATA = -2147483648


def _pack(text: str) -> tuple[bytes, int]:
    """タイル本文（256行×256列のカンマ区切り、欠測は`e`）をint32の配列へ詰める。

    欠測の表し方は配信元の仕様。「標高値が存在しない画素には「e」の文字が格納されている。」
    出典: https://maps.gsi.go.jp/development/demtile.html
    """
    values: list[int] = []
    missing = 0
    for line in text.strip("\n").split("\n"):
        if not line:
            continue
        for cell in line.split(","):
            if cell == DEM_MISSING_MARKER:
                values.append(NODATA)
                missing += 1
            else:
                values.append(int(round(float(cell) * SCALE)))
    return struct.pack(f"<{len(values)}i", *values), missing


def _tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """XYZタイルの経緯度の範囲（min_lon, min_lat, max_lon, max_lat）。"""
    import math

    n = 2 ** z

    def lon(i: int) -> float:
        return i / n * 360.0 - 180.0

    def lat(j: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * j / n))))

    return lon(x), lat(y + 1), lon(x + 1), lat(y)


@register_adapter("gsi_dem_tile")
async def read_gsi_dem_tiles(spec: SourceSpec, profile: SourceProfile,
                             origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    target = profile.target
    product = str(spec.grid.get("product", PRODUCT_PRIORITY[0]))
    zoom = int(spec.grid["zoom"])
    # タイルは`fetch_dem_tiles.py`が先に写している。取込が読むのはその置き場。
    origin.update({"tile_root": str(TILE_ROOT), "product": product, "zoom": zoom})
    min_lat, min_lon, max_lat, max_lon = target.bbox
    tiles = tiles_covering_bbox(
        BoundingBox(min_latitude=min_lat, min_longitude=min_lon,
                    max_latitude=max_lat, max_longitude=max_lon),
        zoom,
    )
    logger.info("標高タイル: product=%s zoom=%d 対象%d枚 / 置き場 %s",
                product, zoom, len(tiles), TILE_ROOT)

    absent = 0
    for x, y in tiles:
        # 写したときに当たった製品で読む。指定と違っていても、粗い側へ落ちた結果である。
        actual_product = stored_product(TILE_ROOT, zoom, x, y)
        if actual_product is None:
            absent += 1
            continue
        pixels, missing = _pack(read_tile(TILE_ROOT, actual_product, zoom, x, y))
        yield SourceRecord(
            natural_key=f"{actual_product}/{zoom}/{x}/{y}",
            geom_wkb=shapely.to_wkb(box(*_tile_bounds(zoom, x, y))),
            # 型・欠測値・位置はrasterの値自身が持つため書かない。尺度（0.01m単位）は
            # rasterが持てず、幅は画素の番地を出すのに要る——rasterから読むと、その
            # たびにタイルの画素が実体化される。
            attrs={
                "product": actual_product, "z": zoom, "x": x, "y": y,
                "width": DEM_TILE_SIZE, "scale": SCALE, "missing": missing,
            },
            rast=tile_raster_wkb(
                pixels, zoom=zoom, x=x, y=y,
                width=DEM_TILE_SIZE, height=DEM_TILE_SIZE,
                dtype="int32_le", nodata=NODATA),
        )

    if absent:
        # 区域外か、まだ写していないか。どちらなのかは置き場の印が持つ。
        logger.info("手元に無い標高タイル: %d枚（scripts/fetch_dem_tiles.py が写す）", absent)
