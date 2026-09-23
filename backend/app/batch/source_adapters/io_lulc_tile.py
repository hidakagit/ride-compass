"""土地被覆ラスタ（Esri×Impact Observatory LULC）のアダプタ。

配信元はUTMゾーン単位の大きなGeoTIFFだが、**取り込むときにタイルへ切る**。標高と同じ
格子に載せることで、面のソースが1つの形にそろい、読み手が形ごとの扱いを持たなくて済む。

ズームは元データの分解能から決める（10m画素なのでz14が7.73m/画素で釣り合う）。
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.batch.ingest import SourceRecord, file_origin, register_adapter
from app.batch.source_adapters._raster_wkb import tile_bbox_wkb, tile_raster_wkb
from app.batch.source_profile import SourceProfile, SourceSpec
from app.domain.region import BoundingBox, tiles_covering_bbox

logger = logging.getLogger("ridecompass.ingest.io_lulc_tile")

_TILE_SIZE = 256


@dataclass(frozen=True)
class LulcGrid:
    """`io_lulc_tile`の`grid`。"""

    zoom: int
    product: str = "io-lulc"
    year: int | None = None


@register_adapter("io_lulc_tile", grid=LulcGrid)
async def read_lulc_tiles(spec: SourceSpec, profile: SourceProfile,
                          origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    # rasterioのimport順の制約（PROJデータの固定）を持つモジュールを経由して読む。
    from app.infrastructure.landcover_raster import (
        has_sources, opened_raster_paths, tile_classes)

    if not has_sources():
        raise RuntimeError(
            "土地被覆のGeoTIFFが設定されていません（settings.lulc_raster_paths）")

    zoom = int(spec.grid.zoom)
    product = str(spec.grid.product)
    year = spec.grid.year
    origin.update({"product": product, "year": year, "zoom": zoom,
                   "rasters": [file_origin(Path(raster)) for raster in opened_raster_paths()]})
    min_lat, min_lon, max_lat, max_lon = profile.target.bbox
    tiles = tiles_covering_bbox(
        BoundingBox(min_latitude=min_lat, min_longitude=min_lon,
                    max_latitude=max_lat, max_longitude=max_lon),
        zoom,
    )
    logger.info("土地被覆タイル: product=%s zoom=%d 対象%d枚", product, zoom, len(tiles))

    uncovered = 0
    for x, y in tiles:
        classes = tile_classes(zoom, x, y)
        if classes is None:
            uncovered += 1
            continue
        yield SourceRecord(
            natural_key=f"{product}/{year}/{zoom}/{x}/{y}",
            geom_wkb=tile_bbox_wkb(zoom, x, y),
            # 型・欠測値・位置はrasterの値自身が持つため書かない。幅は画素の番地を
            # 出すのに要る（rasterから読むと画素が実体化される）。
            attrs={"product": product, "year": year, "z": zoom, "x": x, "y": y,
                   "width": _TILE_SIZE},
            rast=tile_raster_wkb(
                classes.tobytes(), zoom=zoom, x=x, y=y,
                width=_TILE_SIZE, height=_TILE_SIZE, dtype="uint8", nodata=0),
        )
    if uncovered:
        logger.info("ラスタが覆っていないタイル: %d枚", uncovered)
