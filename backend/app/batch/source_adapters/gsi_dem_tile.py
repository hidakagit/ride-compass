"""地理院の標高タイルのアダプタ。

**製品×タイル1枚を1行**として返す。これで面のデータが点・線と同じ骨格に乗り、取込の経路を
分けずに済む。同じタイル座標に複数の製品があれば、その数だけ行ができる——どの製品の値を
採るかは画素ごとの判断で、派生（`derive_elevation.py`）が持つ。

**配信元は叩かない。**取りに行くのは`scripts/fetch_dem_tiles.py`の仕事で、ここは
`app/batch/dem_tile_store.py`が指す置き場にあるものを読む。

標高をint32（0.01m単位）で並べ、`raster`として持つ。配信元のPNGは画素の色に標高を
符号化しており、DBの中で画素を読むには値の並びへ戻しておく必要がある。位置・画素の大きさ・
型・欠測値は`raster`の値自身が持つので、読み手は`attrs`から形を組み立てない。

どの製品をどのズームで読むかはプロファイルが持ち、実装は持たない。
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.batch import dem_tile_store
from app.batch.ingest import AdapterInputs, SourceRecord, register_adapter
from app.batch.source_adapters.raster_wkb import tile_bbox_wkb, tile_raster_wkb
from app.batch.source_profile import SourceProfile, SourceProfileError, SourceSpec
from app.domain.region import BoundingBox, tiles_covering_bbox
from app.infrastructure.gsi_dem_png import read_gsi_dem_png
from app.infrastructure.source_models import SourceFeatureRow

logger = logging.getLogger("ridecompass.ingest.gsi_dem_tile")

#: 1枚の一辺の画素数。配信元の仕様で、自前で描くタイルの画素数
#: （`infrastructure/landcover_raster.py: TILE_SIZE`）を変えてもこちらは変わらない。
#: 出典: https://maps.gsi.go.jp/development/demtile.html
_DEM_TILE_SIZE = 256

#: 詰めるときの尺度と欠測値。地理院の標高タイル（PNG形式）の標高分解能が0.01mなので、
#: 画素の値をそのまま0.01m単位として丸めずに保つ。
#: 出典: https://maps.gsi.go.jp/development/demtile.html
#:
#: 型はint32。関東のbboxには富士山（3,776m）が入り、0.01m単位では377,600となって
#: int16（上限32,767＝3,276.7m）に収まらない。
SCALE = 100
NODATA = -2147483648


def pack_elevations(png: bytes) -> tuple[bytes, int]:
    """タイル1枚（PNG）を、画素の順（行ごと）にint32の配列へ詰める。欠測の画素の数も返す。"""
    elevations, missing = read_gsi_dem_png(png)
    packed = np.where(missing, NODATA, elevations).astype("<i4")
    return packed.tobytes(), int(missing.sum())


@dataclass(frozen=True)
class DemGrid:
    """`gsi_dem_tile`の`grid`。"""

    #: 配信元の製品名（`dem5a`等）→ 読むズーム。
    products: dict[str, int]

    def __post_init__(self) -> None:
        unknown = sorted(set(self.products) - set(dem_tile_store.PRODUCT_PRIORITY))
        if not self.products or unknown:
            raise SourceProfileError(
                f"gsi_dem_tile の grid.products は {dem_tile_store.PRODUCT_PRIORITY} から"
                f"選んでください（知らない製品: {unknown}）")


def _products(spec: SourceSpec) -> dict[str, int]:
    return {str(product): int(zoom) for product, zoom in spec.grid.products.items()}


def _bbox(profile: SourceProfile) -> BoundingBox:
    min_lat, min_lon, max_lat, max_lon = profile.target.bbox
    return BoundingBox(min_latitude=min_lat, min_longitude=min_lon, max_latitude=max_lat, max_longitude=max_lon)


def gsi_dem_tile_inputs(spec: SourceSpec, profile: SourceProfile) -> AdapterInputs:
    """置き場にある、範囲を覆うタイル。区域外の印とまだ写していないタイルは、どちらも行にならない。"""
    root = dem_tile_store.TILE_ROOT
    return AdapterInputs(files=tuple(
        dem_tile_store.tile_path(root, product, zoom, x, y)
        for product, zoom in _products(spec).items()
        for x, y in tiles_covering_bbox(_bbox(profile), zoom)
        if dem_tile_store.is_stored(root, product, zoom, x, y)))


@register_adapter("gsi_dem_tile", grid=DemGrid, required=(SourceFeatureRow.rast,), inputs=gsi_dem_tile_inputs)
async def read_gsi_dem_tiles(spec: SourceSpec, profile: SourceProfile,
                             origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    root = dem_tile_store.TILE_ROOT
    products = _products(spec)
    # タイルは`fetch_dem_tiles.py`が先に写している。取込が読むのはその置き場。
    origin.update({"tile_root": str(root), "products": products})
    bbox = _bbox(profile)

    for product, zoom in products.items():
        tiles = tiles_covering_bbox(bbox, zoom)
        stored = absent = unfetched = 0
        for x, y in tiles:
            if not dem_tile_store.is_stored(root, product, zoom, x, y):
                if dem_tile_store.is_absent(root, product, zoom, x, y):
                    absent += 1
                else:
                    unfetched += 1
                continue
            stored += 1
            pixels, missing = pack_elevations(dem_tile_store.read_tile(root, product, zoom, x, y))
            yield SourceRecord(
                natural_key=f"{product}/{zoom}/{x}/{y}",
                geom_wkb=tile_bbox_wkb(zoom, x, y),
                # 型・欠測値・位置はrasterの値自身が持つため書かない。尺度（0.01m単位）は
                # rasterが持てず、幅は画素の番地を出すのに要る——rasterから読むと、その
                # たびにタイルの画素が実体化される。
                attrs={
                    "product": product, "z": zoom, "x": x, "y": y,
                    "width": _DEM_TILE_SIZE, "scale": SCALE, "missing": missing,
                },
                rast=tile_raster_wkb(
                    pixels, zoom=zoom, x=x, y=y,
                    width=_DEM_TILE_SIZE, height=_DEM_TILE_SIZE,
                    dtype="int32_le", nodata=NODATA),
            )
        logger.info("標高タイル: product=%s zoom=%d 対象%d枚 / 読んだ%d枚・区域外%d枚 / 置き場 %s",
                    product, zoom, len(tiles), stored, absent, root)
        if unfetched:
            logger.warning("まだ写していない標高タイル: product=%s zoom=%d %d枚"
                           "（scripts/fetch_dem_tiles.py が写す）", product, zoom, unfetched)
