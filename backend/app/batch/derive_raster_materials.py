"""面のデータ（標高・土地被覆）を線へ落として、区間と道の値にする。

面の生データは`source_features`にタイル1枚=1行で入っている。**面のまま持つ派生は
作らない**——面を読む出口は「そのまま見せる」か「線へ落とす」のどちらかで、面のままの
中間結果を要る相手がいない。

標高はDB内で完結する。画素は`payload`のまま`get_byte`で引くので、タイルの中身を
プロセスへ取り出さない。

値の出し方そのものはdomainが持つ（`elevation_values_sql`・`class_percentages`）。
このバッチは画素の読み方を渡すだけで、勾配の上限や有効画素数の下限をここに持たない。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.derive_raster_materials
"""

import argparse
import asyncio
import logging
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402

from app.batch._common import asyncpg_dsn, with_derived_data_revision_bump  # noqa: E402
from app.config import settings  # noqa: E402
from app.domain.attributes import elevation_values_sql  # noqa: E402
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


#: 区間の形と、その道が構造物の上かどうか。
_EDGE_SHAPES = f"""
SELECT e.osm_way_id, e.segment_index, e.geom,
       (coalesce({TUNNEL_NORMALIZED_SQL}, '') NOT IN ('', 'no')
        OR coalesce({BRIDGE_NORMALIZED_SQL}, '') NOT IN ('', 'no')) AS on_structure
FROM road_edges e JOIN {_WAYS_AS_W} ON w.osm_way_id = e.osm_way_id
"""


def pixel_address_sql(point: str, zoom: str, size: str) -> str:
    """経緯度が落ちるタイル番号と、そのタイルの中の画素位置を出す断片（Webメルカトル）。"""
    return f"""
    SELECT floor(fx)::int AS tx, floor(fy)::int AS ty,
           least({size} - 1, floor((fx - floor(fx)) * {size})::int) AS px,
           least({size} - 1, floor((fy - floor(fy)) * {size})::int) AS py
    FROM (SELECT (ST_X({point}) + 180.0) / 360.0 * (2::double precision ^ {zoom}) AS fx,
                 (1.0 - ln(tan(radians(ST_Y({point})))
                           + 1.0 / cos(radians(ST_Y({point})))) / pi()) / 2.0
                 * (2::double precision ^ {zoom}) AS fy) f"""


#: 画素1つが何バイトか。取込が`attrs`へ書いた型に従う。
PIXEL_BYTES = {"uint8": 1, "int16_le": 2}


def pixel_slice_sql(dtype: str, payload: str, index: str) -> str:
    """`index`番目の画素のバイトだけを取り出す断片。

    **値全体ではなくスライスで取る。**`payload`は圧縮しない設定なのでTOASTの一部だけを
    読めるが、`get_byte`のように値全体を指す形で書くと毎回すべてが実体化される。
    """
    width = PIXEL_BYTES[dtype]
    return f"substring({payload} from ({index}) * {width} + 1 for {width})"


def pixel_value_sql(dtype: str, pixel: str) -> str:
    """スライスした画素のバイトを数として読む断片。リトルエンディアン。"""
    if dtype == "uint8":
        return f"get_byte({pixel}, 0)"
    if dtype == "int16_le":
        return (f"((get_byte({pixel}, 1) << 8) | get_byte({pixel}, 0))"
                f" - CASE WHEN get_byte({pixel}, 1) > 127 THEN 65536 ELSE 0 END")
    raise ValueError(f"画素の型 '{dtype}' の読み方を持っていない")


def _tile_grid_sql(source: str) -> str:
    return ("SELECT (attrs->>'x')::int AS tx, (attrs->>'y')::int AS ty, payload,"
            " (attrs->>'nodata')::bigint AS nodata, (attrs->>'scale')::float AS scale"
            f" FROM source_features WHERE source = '{source}'")


async def _grid_spec(conn: asyncpg.Connection, source: str) -> tuple[int, int, str]:
    """タイルの並び方（ズーム・1辺の画素数・型）。**全タイルで1つ**であることを確かめる。"""
    rows = await conn.fetch(
        "SELECT DISTINCT (attrs->>'z')::int AS z, (attrs->>'width')::int AS width,"
        " attrs->>'dtype' AS dtype FROM source_features WHERE source = $1", source)
    if len(rows) != 1:
        raise RuntimeError(f"'{source}'のタイルの並び方が1つに定まりません: {len(rows)}種類")
    return rows[0]["z"], rows[0]["width"], rows[0]["dtype"]


def _vertex_address_sql(zoom: int, size: int) -> str:
    """区間の頂点それぞれに、その位置のタイル番号と画素位置を付ける。"""
    return f"""
SELECT s.osm_way_id, s.segment_index, dp.path[1] AS ord,
       ST_X(dp.geom) AS lon, ST_Y(dp.geom) AS lat, s.on_structure,
       a.tx, a.ty, a.px, a.py
FROM ({_EDGE_SHAPES}) s
CROSS JOIN LATERAL ST_DumpPoints(s.geom) AS dp
CROSS JOIN LATERAL ({pixel_address_sql("dp.geom", str(zoom), str(size))}) a
"""


def _vertex_elevation_sql(size: int, dtype: str) -> str:
    """画素位置の付いた頂点へ、DEMの値を引いて標高にする。"""
    pixel = pixel_slice_sql(dtype, "t.payload", f"(v.py * {size} + v.px)")
    value = pixel_value_sql(dtype, "b.pixel")
    return f"""
SELECT v.osm_way_id, v.segment_index, v.ord, v.lon, v.lat, v.on_structure,
       CASE WHEN b.pixel IS NULL THEN NULL
            WHEN ({value}) = t.nodata THEN NULL
            ELSE ({value}) / t.scale END AS elev
FROM _vertex v
LEFT JOIN ({_tile_grid_sql("dem")}) t ON t.tx = v.tx AND t.ty = v.ty
CROSS JOIN LATERAL (SELECT {pixel} AS pixel) b
"""


async def derive_elevation(conn: asyncpg.Connection) -> int:
    started = time.perf_counter()
    if not await conn.fetchval("SELECT count(*) FROM source_features WHERE source = 'dem'"):
        logger.warning("標高タイルが1枚も取り込まれていません")
        return 0
    zoom, size, dtype = await _grid_spec(conn, "dem")

    # **頂点をいったん実体にしてから**タイルへ結合する。関数から直に結合すると行数を
    # 見積もれず、プランナがタイル側を入れ子で読み直す計画を選ぶ（開発DBで数秒が
    # 数分になる）。
    await conn.execute(f"CREATE TEMP TABLE _vertex ON COMMIT DROP AS {_vertex_address_sql(zoom, size)}")
    await conn.execute("ANALYZE _vertex")
    await conn.execute(
        f"CREATE TEMP TABLE _vertex_elev ON COMMIT DROP AS {_vertex_elevation_sql(size, dtype)}")
    await conn.execute("ANALYZE _vertex_elev")

    values = elevation_values_sql("SELECT * FROM _vertex_elev")
    result = await conn.execute(f"""
        UPDATE edge_materials m SET
            start_elevation_m = v.start_elevation_m, end_elevation_m = v.end_elevation_m,
            elevation_gain_m = v.elevation_gain_m, elevation_loss_m = v.elevation_loss_m,
            average_grade = v.average_grade,
            max_grade = v.max_grade, min_grade = v.min_grade
        FROM ({values}) v
        WHERE v.osm_way_id = m.osm_way_id AND v.segment_index = m.segment_index""")
    updated = int(result.split()[-1])
    await conn.execute("DROP TABLE _vertex_elev")
    await conn.execute("DROP TABLE _vertex")

    edges = await conn.fetchval("SELECT count(*) FROM road_edges")
    logger.info("標高: 区間 %d/%d本に値が付いた / %.1f秒",
                updated, edges, time.perf_counter() - started)
    return updated


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
