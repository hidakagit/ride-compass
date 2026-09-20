"""基礎地図（OpenFreeMap）のベクタタイルのアダプタ。

配信元のタイルをそのまま`payload`へ入れる。中身（Mapbox Vector Tile）を解釈しない——
利用者へ渡すだけのもので、こちらが加工の入力にはしない。

配信元のURLは版を含む（`planet/<版>/{z}/{x}/{y}.pbf`）。版はTileJSONから取り、
`source_runs.origin`へ記録する。どの版を配ったのかは後から分からなくなる。
"""

import asyncio
import logging
from collections.abc import AsyncIterator

import httpx
import shapely
from shapely.geometry import box

from app.batch.ingest import SourceRecord, register_adapter
from app.batch.source_profile import SourceProfile, SourceSpec
from app.domain.region import BoundingBox, tiles_covering_bbox

logger = logging.getLogger("ridecompass.ingest.openfreemap_tile")

UPSTREAM_HOST = "https://tiles.openfreemap.org"

#: 上流への同時接続数。
MAX_CONCURRENT = 8

REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)


def _tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    import math

    n = 2 ** z

    def lon(i: int) -> float:
        return i / n * 360.0 - 180.0

    def lat(j: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * j / n))))

    return lon(x), lat(y + 1), lon(x + 1), lat(y)


@register_adapter("openfreemap_tile")
async def read_openfreemap_tiles(spec: SourceSpec, profile: SourceProfile
                                 ) -> AsyncIterator[SourceRecord]:
    product = str(spec.grid.get("product", "planet"))
    zoom = int(spec.grid["zoom"])
    min_lat, min_lon, max_lat, max_lon = profile.target.bbox
    tiles = tiles_covering_bbox(
        BoundingBox(min_latitude=min_lat, min_longitude=min_lon,
                    max_latitude=max_lat, max_longitude=max_lon),
        zoom,
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    missing = 0

    async with httpx.AsyncClient() as client:
        tilejson = (await client.get(f"{UPSTREAM_HOST}/{product}", timeout=REQUEST_TIMEOUT)).json()
        template = tilejson["tiles"][0]
        logger.info("基礎地図タイル: %s zoom=%d 対象%d枚", template, zoom, len(tiles))

        async def fetch(xy: tuple[int, int]):
            async with semaphore:
                url = template.format(z=zoom, x=xy[0], y=xy[1])
                response = await client.get(url, timeout=REQUEST_TIMEOUT)
                if response.status_code == 404:
                    return xy, None
                response.raise_for_status()
                return xy, response.content

        for start in range(0, len(tiles), MAX_CONCURRENT * 8):
            chunk = tiles[start:start + MAX_CONCURRENT * 8]
            for coro in asyncio.as_completed([fetch(xy) for xy in chunk]):
                (x, y), content = await coro
                if content is None:
                    missing += 1
                    continue
                yield SourceRecord(
                    natural_key=f"{product}/{zoom}/{x}/{y}",
                    geom_wkb=shapely.to_wkb(box(*_tile_bounds(zoom, x, y))),
                    attrs={"product": product, "z": zoom, "x": x, "y": y,
                           "content_type": "application/x-protobuf", "template": template},
                    payload=content,
                )
    if missing:
        logger.info("配信元が持っていないタイル: %d枚", missing)
