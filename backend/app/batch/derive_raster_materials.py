"""面のデータ（標高・土地被覆）を線へ落として、区間と道の値にする。

面の生データは`source_features`にタイル1枚=1行で入っている。**面のまま持つ派生は
作らない**——面を読む出口は「そのまま見せる」か「線へ落とす」のどちらかで、面のままの
中間結果を要る相手がいない。

タイルは要るものだけを主キーで1枚ずつ読む。全部をメモリへ載せると関東規模で数百MBに
なり、全国では載らない。

値の出し方そのものはdomainが持つ（`compute_elevation_values`・`class_percentages`）。
このバッチは画素を読んで渡すだけで、勾配の上限や有効画素数の下限をここに持たない。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.derive_raster_materials
"""

import argparse
import asyncio
import logging
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402

from app.batch._common import asyncpg_dsn, with_derived_data_revision_bump  # noqa: E402
from app.config import settings  # noqa: E402
from app.domain.attributes import compute_elevation_values  # noqa: E402
from app.domain.geo import LatLonPoint  # noqa: E402
from app.domain.landcover import LandcoverPercentages, class_percentages  # noqa: E402
from app.domain.material_sql import BRIDGE_NORMALIZED_SQL, TUNNEL_NORMALIZED_SQL  # noqa: E402

logger = logging.getLogger("ridecompass.derive_raster_materials")

#: `source_features.attrs.dtype`（取込が書く）からnumpyの型への対応。
_NUMPY_DTYPE = {"int16_le": "<i2", "int32_le": "<i4", "uint8": "u1"}

#: 土地被覆を数える帯。中心線からこの距離までを見て、路面そのものの幅は除く。
LANDCOVER_RING_M = 100.0
LANDCOVER_INNER_M = 10.0

#: Webメルカトル（EPSG:3857）が世界を写す一辺の長さ（m）。
WORLD_M = 2 * math.pi * 6378137.0

#: `source_features`の道の行を、材料の式（`domain/material_sql.py`）が期待する別名へ
#: 合わせる。式の側にタグ列の名前が書かれているため、こちらが合わせる。
_WAYS_AS_W = (
    "(SELECT natural_key::bigint AS osm_way_id, attrs AS tags, geom "
    "FROM source_features WHERE source = 'osm_way') w"
)


def _tile_list_sql(source: str) -> str:
    return ("SELECT natural_key, (attrs->>'x')::int AS x, (attrs->>'y')::int AS y, "
            f"(attrs->>'z')::int AS z FROM source_features WHERE source = '{source}'")


def pixel_size_m(zoom: int, tile_size: int) -> float:
    return WORLD_M / (2 ** zoom * tile_size)


def pixel_of(lon: float, lat: float, zoom: int, tile_size: int) -> tuple[int, int, int, int]:
    """経緯度が落ちるタイル番号と、そのタイルの中の画素位置。"""
    n = 2 ** zoom
    radians = math.radians(lat)
    fx = (lon + 180.0) / 360.0 * n
    fy = (1.0 - math.log(math.tan(radians) + 1 / math.cos(radians)) / math.pi) / 2.0 * n
    x, y = int(fx), int(fy)
    return (x, y,
            min(tile_size - 1, int((fx - x) * tile_size)),
            min(tile_size - 1, int((fy - y) * tile_size)))


# --- 標高 -------------------------------------------------------------------


_EDGE_SHAPES = f"""
SELECT e.osm_way_id, e.segment_index, ST_AsBinary(e.geom) AS wkb,
       (coalesce({TUNNEL_NORMALIZED_SQL}, '') NOT IN ('', 'no')
        OR coalesce({BRIDGE_NORMALIZED_SQL}, '') NOT IN ('', 'no')) AS on_structure
FROM road_edges e JOIN {_WAYS_AS_W} ON w.osm_way_id = e.osm_way_id
"""

_UPDATE_ELEVATION = """
UPDATE edge_materials SET start_elevation_m = $3, end_elevation_m = $4,
    elevation_gain_m = $5, elevation_loss_m = $6, average_grade = $7,
    max_grade = $8, min_grade = $9
WHERE osm_way_id = $1 AND segment_index = $2
"""


async def derive_elevation(conn: asyncpg.Connection) -> int:
    started = time.perf_counter()
    tiles = await conn.fetch(_tile_list_sql("dem"))
    if not tiles:
        logger.warning("標高タイルが1枚も取り込まれていません")
        return 0
    zoom = tiles[0]["z"]
    key_of = {(t["x"], t["y"]): t["natural_key"] for t in tiles}

    edges: list[tuple[int, int, list[LatLonPoint], bool]] = []
    # タイルごとに「どの区間の何番目の点か」を集めてから読む。同じタイルを何度も開かない。
    wanted: dict[tuple[int, int], list[tuple[int, int, int, int]]] = defaultdict(list)
    for row in await conn.fetch(_EDGE_SHAPES):
        line = shapely.from_wkb(bytes(row["wkb"]))
        points = [LatLonPoint(lat, lon) for lon, lat in line.coords]
        index = len(edges)
        edges.append((row["osm_way_id"], row["segment_index"], points, row["on_structure"]))
        for order, point in enumerate(points):
            x, y, px, py = pixel_of(point.longitude, point.latitude, zoom, 256)
            wanted[(x, y)].append((index, order, px, py))

    heights: list[list[float | None]] = [[None] * len(e[2]) for e in edges]
    missing_tiles = 0
    for (x, y), items in wanted.items():
        key = key_of.get((x, y))
        if key is None:
            missing_tiles += 1
            continue
        row = await conn.fetchrow(
            "SELECT payload, (attrs->>'scale')::float AS scale, "
            "(attrs->>'nodata')::bigint AS nodata, (attrs->>'width')::int AS width, "
            "attrs->>'dtype' AS dtype "
            "FROM source_features WHERE source = 'dem' AND natural_key = $1", key)
        # 型は取込が`attrs`へ書いたものに従う。ここで決め打つと、取込側の型を変えたときに
        # 黙って別の数を読む。
        grid = np.frombuffer(row["payload"], dtype=_NUMPY_DTYPE[row["dtype"]]).reshape(
            row["width"], row["width"])
        for index, order, px, py in items:
            value = int(grid[py, px])
            if value != row["nodata"]:
                heights[index][order] = value / row["scale"]

    updates = []
    for index, (way_id, segment_index, points, on_structure) in enumerate(edges):
        values = compute_elevation_values(points, heights[index],
                                          dem_reflects_road_surface=not on_structure)
        if values.start_elevation_m is None:
            continue
        updates.append((way_id, segment_index, values.start_elevation_m, values.end_elevation_m,
                        values.elevation_gain_m, values.elevation_loss_m, values.average_grade,
                        values.max_grade, values.min_grade))
    await conn.executemany(_UPDATE_ELEVATION, updates)

    logger.info("標高: 区間 %d/%d本に値が付いた / タイル %d枚（不足 %d枚）/ %.1f秒",
                len(updates), len(edges), len(wanted) - missing_tiles, missing_tiles,
                time.perf_counter() - started)
    return len(updates)


# --- 土地被覆 ---------------------------------------------------------------


#: 帯を先に作って索引を張る。タイル1枚ごとに作り直すと、同じ区間を何度も膨らませることになる。
_BUILD_RINGS = """
CREATE TEMP TABLE _rings ON COMMIT DROP AS
SELECT osm_way_id, segment_index,
       ST_Transform(ST_Difference(ST_Buffer(geom::geography, $1)::geometry,
                                  ST_Buffer(geom::geography, $2)::geometry), 3857) AS ring
FROM road_edges
"""

_RINGS_IN_TILE = """
SELECT osm_way_id, segment_index, ST_AsBinary(ring) AS wkb FROM _rings
WHERE ring && ST_MakeEnvelope($1, $2, $3, $4, 3857)
"""


def _landcover_columns() -> list[tuple[str, str]]:
    """(`LandcoverPercentages`の項目名, `edge_materials`の列名) の対応。

    クラスが1つ増えてもここは変わらない——項目名から列名を導いており、並べていない。
    """
    return [(name, "lc_" + name.removesuffix("_percent"))
            for name in LandcoverPercentages.model_fields if name.endswith("_percent")]


async def derive_landcover(conn: asyncpg.Connection) -> int:
    started = time.perf_counter()
    tiles = await conn.fetch(_tile_list_sql("lulc"))
    if not tiles:
        logger.warning("土地被覆タイルが1枚も取り込まれていません")
        return 0
    zoom = tiles[0]["z"]
    size = pixel_size_m(zoom, 256)
    half = WORLD_M / 2

    await conn.execute(_BUILD_RINGS, LANDCOVER_RING_M, LANDCOVER_INNER_M)
    await conn.execute("CREATE INDEX ON _rings USING GIST (ring)")

    # クラス番号をそのまま添字にして数える。domainが分母（無効クラス）を決める。
    tally: dict[tuple[int, int], np.ndarray] = {}
    width = 16
    for tile in tiles:
        row = await conn.fetchrow(
            "SELECT payload, (attrs->>'width')::int AS width FROM source_features "
            "WHERE source = 'lulc' AND natural_key = $1", tile["natural_key"])
        if row["payload"] is None:
            continue
        grid = np.frombuffer(row["payload"], dtype=np.uint8).reshape(row["width"], row["width"])
        origin_x, origin_y = tile["x"] * row["width"], tile["y"] * row["width"]
        rings = await conn.fetch(
            _RINGS_IN_TILE,
            -half + origin_x * size, half - (origin_y + row["width"]) * size,
            -half + (origin_x + row["width"]) * size, half - origin_y * size)
        for ring_row in rings:
            ring = shapely.from_wkb(bytes(ring_row["wkb"]))
            # 同じ帯へ何百点も当てるため、先に索引を作らせる。
            shapely.prepare(ring)
            min_x, min_y, max_x, max_y = ring.bounds
            i0 = max(0, int((min_x + half) / size) - origin_x)
            i1 = min(row["width"] - 1, int((max_x + half) / size) - origin_x)
            j0 = max(0, int((half - max_y) / size) - origin_y)
            j1 = min(row["width"] - 1, int((half - min_y) / size) - origin_y)
            if i0 > i1 or j0 > j1:
                continue
            xs = -half + (origin_x + np.arange(i0, i1 + 1) + 0.5) * size
            ys = half - (origin_y + np.arange(j0, j1 + 1) + 0.5) * size
            mesh_x, mesh_y = np.meshgrid(xs, ys)
            inside = shapely.contains_xy(ring, mesh_x, mesh_y)
            if not inside.any():
                continue
            counted = np.bincount(grid[j0:j1 + 1, i0:i1 + 1][inside], minlength=width)
            key = (ring_row["osm_way_id"], ring_row["segment_index"])
            if key in tally:
                tally[key] += counted
            else:
                tally[key] = counted

    columns = _landcover_columns()
    updates = []
    empty = 0
    for (way_id, segment_index), counts in tally.items():
        percentages = class_percentages({value: int(counts[value]) for value in range(width)})
        if percentages is None:
            # 画素が足りない（覆われていない・雲）。計算済みであることは残す。
            empty += 1
            updates.append((way_id, segment_index, 0, *([None] * len(columns))))
            continue
        updates.append((way_id, segment_index, percentages.valid_pixels,
                        *(round(getattr(percentages, name), 2) for name, _ in columns)))

    sets = ", ".join(f"{column} = ${index + 4}" for index, (_, column) in enumerate(columns))
    await conn.executemany(
        f"UPDATE edge_materials SET lc_valid_pixels = $3, {sets} "
        "WHERE osm_way_id = $1 AND segment_index = $2", updates)

    logger.info("土地被覆: 区間 %d本（うち画素不足 %d本）/ タイル %d枚 / %.1f秒",
                len(updates), empty, len(tiles), time.perf_counter() - started)
    return len(updates) - empty


# --- 道への集約 -------------------------------------------------------------


def _way_rollup_sql() -> str:
    """道の値は区間から導く。長さで重み付けた平均にするのは、どちらも割合のため。"""
    columns = [column for _, column in _landcover_columns()]
    averaged = ", ".join(
        f"sum(m.{c} * e.distance_m) / nullif(sum(e.distance_m) "
        f"FILTER (WHERE m.{c} IS NOT NULL), 0) AS {c}" for c in columns)
    assigned = ", ".join(f"{c} = s.{c}" for c in columns)
    return f"""
UPDATE way_materials w SET lc_valid_pixels = s.lc_valid_pixels, {assigned}
FROM (
    SELECT m.osm_way_id, sum(m.lc_valid_pixels) AS lc_valid_pixels, {averaged}
    FROM edge_materials m JOIN road_edges e
      ON e.osm_way_id = m.osm_way_id AND e.segment_index = m.segment_index
    WHERE m.lc_valid_pixels IS NOT NULL
    GROUP BY m.osm_way_id
) s WHERE s.osm_way_id = w.osm_way_id
"""


async def derive(conn: asyncpg.Connection) -> None:
    async with conn.transaction():
        await derive_elevation(conn)
        await derive_landcover(conn)
        await conn.execute(_way_rollup_sql())


async def run(database_url: str) -> int:
    conn = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        await derive(conn)
    finally:
        await conn.close()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="面のデータを線へ落とす")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    database_url = args.database_url or settings.database_url
    # 派生が変われば、それを読んで作ったキャッシュは古くなる。
    return asyncio.run(with_derived_data_revision_bump(
        run(database_url), database_url=database_url, dry_run=False))


if __name__ == "__main__":
    raise SystemExit(main())
