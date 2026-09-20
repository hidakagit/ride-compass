"""地理院の標高タイルのアダプタ。

**タイル1枚を1行**として返す。これで面のデータが点・線と同じ骨格に乗り、取込の経路を
分けずに済む。

`payload`は標高をint32（0.01m単位）で並べた配列で、欠測は`NODATA`。配信元はテキストで
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
logger = logging.getLogger("ridecompass.ingest.gsi_dem_tile")

#: 配信元のタイルURLと、1枚の一辺の画素数。
#: 出典: https://maps.gsi.go.jp/development/demtile.html
DEM_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/{type}/{z}/{x}/{y}.txt"
DEM_TILE_SIZE = 256

#: 欠測を表す文字。「標高値が存在しない画素には「e」の文字が格納されている。」
#: 出典: https://maps.gsi.go.jp/development/demtile.html
DEM_MISSING_MARKER = "e"

#: 製品を計測精度の良い順に並べたもの。「航空レーザ測量（DEM1A）のデータが存在しない
#: 箇所では、航空レーザ測量（DEM5A）→写真測量（DEM5B, DEM5C）→1/2.5万地形図等高線
#: （DEM10B）の順で存在する最も計測精度の良い標高タイルの値が参照され、その地点の
#: 標高値として採用されます。」
#: 出典: https://maps.gsi.go.jp/development/hyokochi.html
DEM_TYPE_PRIORITY = ("dem5a", "dem5b", "dem5c", "dem")

#: 上流への同時接続数。配信元へ並べてよい数の上限。
MAX_CONCURRENT = 8

#: 詰めるときの尺度と欠測値。地理院の標高タイル（テキスト形式）は「標高データは小数点
#: 第二位までデータとして入っている（単位はm）」ため、0.01m単位で丸めずに保つ。
#: 出典: https://maps.gsi.go.jp/development/demtile.html
#:
#: 型はint32。関東のbboxには富士山（3,776m）が入り、0.01m単位では377,600となって
#: int16（上限32,767＝3,276.7m）に収まらない。
SCALE = 100
NODATA = -2147483648

REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)


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
                        "dtype": "int32_le", "scale": SCALE, "nodata": NODATA,
                        "missing": missing,
                    },
                    payload=payload,
                )
    if outside:
        logger.info("整備区域外で取得できなかったタイル: %d枚", outside)
