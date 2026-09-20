"""地理院の標高タイルのアダプタ。

**タイル1枚を1行**として返す。これで面のデータが点・線と同じ骨格に乗り、取込の経路を
分けずに済む。

`payload`は標高をint16（0.1m単位）で並べた配列で、欠測は`NODATA`。配信元はテキストで
返すが、同じ内容が数倍の大きさになるため詰めて持つ。どう読むかは`attrs`が持つ
（幅・高さ・型・尺度・欠測値）ので、読み手は形を推測しない。

ズームは元データの分解能から決める——プロファイルが`zoom`を持ち、実装は持たない。
配信元がそれ以上を持たない（z16以降は404）ことは確認済み。
"""

import asyncio
import logging
import struct
from collections.abc import AsyncIterator

import httpx
import shapely
from shapely.geometry import box

from app.batch.ingest import SourceRecord, register_adapter
from app.batch.source_profile import SourceProfile, SourceSpec
from app.domain.region import BoundingBox, tiles_covering_bbox
from app.infrastructure.elevation_client import (
    DEM_MISSING_MARKER,
    DEM_TILE_SIZE,
    DEM_TILE_URL,
    DEM_TYPE_PRIORITY,
)

logger = logging.getLogger("ridecompass.ingest.gsi_dem_tile")

#: 上流への同時接続数。配信元へ並べてよい数の上限で、`elevation_client`と同じ考え方。
MAX_CONCURRENT = 8

#: int16へ詰めるときの尺度（0.1m単位）と欠測値。
SCALE = 10
NODATA = -32768

REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)


def _pack(text: str) -> tuple[bytes, int]:
    """タイル本文（256行×256列のカンマ区切り、欠測は`e`）をint16の配列へ詰める。"""
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
                values.append(max(-32767, min(32767, int(round(float(cell) * SCALE)))))
    return struct.pack(f"<{len(values)}h", *values), missing


def _tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """XYZタイルの経緯度の範囲（min_lon, min_lat, max_lon, max_lat）。"""
    import math

    n = 2 ** z

    def lon(i: int) -> float:
        return i / n * 360.0 - 180.0

    def lat(j: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * j / n))))

    return lon(x), lat(y + 1), lon(x + 1), lat(y)


async def _fetch_one(client: httpx.AsyncClient, product: str, z: int, x: int, y: int
                     ) -> tuple[str, str] | None:
    """整備区域内なら(実際に当たった製品, 本文)。区域外はNone。

    製品は粗い側へ落ちていく（配信元が細かい製品を全域では持たないため）。
    """
    order = [product] + [p for p in DEM_TYPE_PRIORITY if p != product]
    for candidate in order:
        url = DEM_TILE_URL.format(type=candidate, z=z, x=x, y=y)
        response = await client.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return candidate, response.text
        if response.status_code != 404:
            response.raise_for_status()
    return None


@register_adapter("gsi_dem_tile")
async def read_gsi_dem_tiles(spec: SourceSpec, profile: SourceProfile) -> AsyncIterator[SourceRecord]:
    target = profile.target
    product = str(spec.grid.get("product", DEM_TYPE_PRIORITY[0]))
    zoom = int(spec.grid["zoom"])
    min_lat, min_lon, max_lat, max_lon = target.bbox
    tiles = tiles_covering_bbox(
        BoundingBox(min_latitude=min_lat, min_longitude=min_lon,
                    max_latitude=max_lat, max_longitude=max_lon),
        zoom,
    )
    logger.info("標高タイル: product=%s zoom=%d 対象%d枚", product, zoom, len(tiles))

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    outside = 0

    async with httpx.AsyncClient() as client:
        async def fetch(xy: tuple[int, int]):
            async with semaphore:
                return xy, await _fetch_one(client, product, zoom, xy[0], xy[1])

        for start in range(0, len(tiles), MAX_CONCURRENT * 8):
            chunk = tiles[start:start + MAX_CONCURRENT * 8]
            for coro in asyncio.as_completed([fetch(xy) for xy in chunk]):
                (x, y), result = await coro
                if result is None:
                    outside += 1
                    continue
                actual_product, text = result
                payload, missing = _pack(text)
                yield SourceRecord(
                    natural_key=f"{actual_product}/{zoom}/{x}/{y}",
                    geom_wkb=shapely.to_wkb(box(*_tile_bounds(zoom, x, y))),
                    attrs={
                        "product": actual_product, "z": zoom, "x": x, "y": y,
                        "width": DEM_TILE_SIZE, "height": DEM_TILE_SIZE,
                        "dtype": "int16_le", "scale": SCALE, "nodata": NODATA,
                        "missing": missing,
                    },
                    payload=payload,
                )
    if outside:
        logger.info("整備区域外で取得できなかったタイル: %d枚", outside)
