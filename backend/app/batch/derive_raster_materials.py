"""面のデータ（標高・土地被覆）を線へ落として、区間と道の値にする。

面の生データは`source_features`にタイル1枚=1行、`raster`として入っている。**面のまま
持つ派生は作らない**——面を読む出口は「そのまま見せる」か「線へ落とす」のどちらかで、
面のままの中間結果を要る相手がいない。

**処理はDB内で完結する。**画素をプロセスへ取り出さない。標高は1点の画素を引き
（`ST_Value`）、土地被覆は帯に重なる画素を数える（`ST_Clip` + `ST_ValueCount`）——
どちらもPostGISのrasterが持っている操作である。

標高は同じ地点に複数の製品のタイルがありうる。**どの製品の値を採るかは画素ごとに決める**
——配信元の定める精度の順（`dem_tile_store.PRODUCT_PRIORITY`）に見て、値のある最初の製品を
採る。どの製品にも値が無い画素は欠測のまま残る。

値の出し方そのものはdomainが持つ（`elevation_values_sql`・`class_percentages_sql`）。
このバッチは画素の引き方を組み立てるだけで、勾配の上限や有効画素数の下限を持たない。
"""

import logging
import time

import asyncpg

from app.batch.dem_tile_store import PRODUCT_PRIORITY
from app.domain.attributes import elevation_values_sql
from app.domain.landcover import (
    LANDCOVER_RING_INNER_M,
    LANDCOVER_RING_OUTER_M,
    PERCENT_CLASSES,
    class_percentages_sql,
)
from app.domain.region import tile_position_sql
from app.domain.material_sql import (
    BRIDGE_NORMALIZED_SQL,
    TUNNEL_NORMALIZED_SQL,
    WAYS_SOURCE_SQL,
)

logger = logging.getLogger("ridecompass.derive_raster_materials")

_EDGE_SHAPES = f"""
SELECT e.osm_way_id, e.segment_index, e.geom,
       (coalesce({TUNNEL_NORMALIZED_SQL}, '') NOT IN ('', 'no')
        OR coalesce({BRIDGE_NORMALIZED_SQL}, '') NOT IN ('', 'no')) AS on_structure
FROM road_edges e JOIN {WAYS_SOURCE_SQL} w ON w.osm_way_id = e.osm_way_id
"""


def _tiles(source: str) -> str:
    return (f"(SELECT natural_key, rast, attrs, geom FROM source_features"
            f" WHERE source = '{source}') t")


# --- 標高 -------------------------------------------------------------------


#: 頂点を一度実体にしてからタイルへ結合する。関数から直に結合すると行数を見積もれず、
#: プランナがタイル側を入れ子で読み直す計画を選ぶ。
_VERTICES = f"""
CREATE TEMP TABLE _vertex ON COMMIT DROP AS
SELECT row_number() OVER () AS vid, s.osm_way_id, s.segment_index, dp.path[1] AS ord,
       ST_X(dp.geom) AS lon, ST_Y(dp.geom) AS lat, s.on_structure
FROM ({_EDGE_SHAPES}) s
CROSS JOIN LATERAL ST_DumpPoints(s.geom) AS dp
"""

#: 頂点ごとに採った標高。値のある画素だけを入れるので、行の無い頂点はまだどの製品でも
#: 値が見つかっていない。
_VERTEX_ELEVATION_TABLE = """
CREATE TEMP TABLE _vertex_elev (vid bigint PRIMARY KEY, elev double precision) ON COMMIT DROP
"""

#: 頂点のタイル座標（小数）の式。`$2`は製品のズーム。
_VERTEX_TILE_X, _VERTEX_TILE_Y = tile_position_sql("v.lon", "v.lat", "$2")

#: 1製品ぶん、まだ値の無い頂点に画素を引く。**製品を優先順に1つずつ流す**ので、上の製品に
#: 値のある頂点は下の製品を読まない——読む画素は欠けた頂点の分だけ増える。
#:
#: **どのタイルのどの画素かは算術で出す。**`ST_Intersects(rast, 点)`で絞ると当たり判定の
#: たびにタイルの画素が実体化され、外枠だけで絞ると境界線上の点が隣のタイルへ割り当たる。
#: 番地で決めれば、rasterに触らずに1枚・1画素へ確定する。製品ごとにズームが違っても、
#: その製品のズームで番地を出せば同じ式で済む。
#:
#: 標高は`scale`で割って戻す（取込が整数へ詰めているため。尺度だけはrasterが持てない）。
#: 幅は`attrs`が持つ——rasterから読むと、そのたびに画素が実体化される。
_FILL_FROM_PRODUCT = f"""
INSERT INTO _vertex_elev (vid, elev)
SELECT vid, elev FROM (
  SELECT a.vid,
         ST_Value(t.rast, 1,
                  least(w.n, floor((a.fx - a.tx) * w.n)::int + 1),
                  least(w.n, floor((a.fy - a.ty) * w.n)::int + 1))
         / (t.attrs->>'scale')::float AS elev
  FROM (SELECT v.vid, p.fx, p.fy, floor(p.fx)::int AS tx, floor(p.fy)::int AS ty
        FROM _vertex v
        CROSS JOIN LATERAL (SELECT {_VERTEX_TILE_X} AS fx, {_VERTEX_TILE_Y} AS fy) p
        WHERE NOT EXISTS (SELECT 1 FROM _vertex_elev e WHERE e.vid = v.vid)) a
  JOIN {_tiles("dem")}
    ON t.attrs->>'product' = $1
   AND (t.attrs->>'x')::int = a.tx AND (t.attrs->>'y')::int = a.ty
  CROSS JOIN LATERAL (SELECT (t.attrs->>'width')::int AS n) w
) s
WHERE elev IS NOT NULL
"""

_VERTEX_ELEVATIONS = """
SELECT v.osm_way_id, v.segment_index, v.ord, v.lon, v.lat, v.on_structure, e.elev
FROM _vertex v LEFT JOIN _vertex_elev e ON e.vid = v.vid
"""

_UPDATE_ELEVATION = f"""
UPDATE edge_materials m SET
    start_elevation_m = v.start_elevation_m, end_elevation_m = v.end_elevation_m,
    elevation_gain_m = v.elevation_gain_m, elevation_loss_m = v.elevation_loss_m,
    average_grade = v.average_grade,
    max_grade = v.max_grade, min_grade = v.min_grade
FROM ({elevation_values_sql(_VERTEX_ELEVATIONS)}) v
WHERE v.osm_way_id = m.osm_way_id AND v.segment_index = m.segment_index
"""


async def _products_in_priority(conn: asyncpg.Connection) -> list[tuple[str, int]]:
    """取り込まれた製品とそのズームを、画素の値を採る順に並べる。

    順を知らない製品や、1製品に2つのズームがあれば止める——どちらも、どの値を採るかを
    決められない。
    """
    rows = await conn.fetch(
        "SELECT attrs->>'product' AS product, array_agg(DISTINCT (attrs->>'z')::int) AS zooms"
        " FROM source_features WHERE source = 'dem' GROUP BY 1")
    zooms = {r["product"]: r["zooms"] for r in rows}
    unknown = sorted(set(zooms) - set(PRODUCT_PRIORITY))
    mixed = sorted(p for p, z in zooms.items() if len(z) != 1)
    if unknown or mixed:
        raise ValueError(f"標高タイルの製品を並べられません: 順を知らない {unknown}"
                         f" / ズームが複数 {mixed}")
    return [(p, zooms[p][0]) for p in PRODUCT_PRIORITY if p in zooms]


async def derive_elevation(conn: asyncpg.Connection) -> int:
    started = time.perf_counter()
    products = await _products_in_priority(conn)
    if not products:
        logger.warning("標高タイルが1枚も取り込まれていません")
        return 0

    await conn.execute(_VERTICES)
    await conn.execute("ANALYZE _vertex")
    await conn.execute(_VERTEX_ELEVATION_TABLE)
    vertices = await conn.fetchval("SELECT count(*) FROM _vertex")
    remaining = vertices
    for product, zoom in products:
        filled = int((await conn.execute(_FILL_FROM_PRODUCT, product, zoom)).split()[-1])
        remaining -= filled
        logger.info("標高: %s（z%d）で頂点 %d点に値が付いた / 残り %d/%d点",
                    product, zoom, filled, remaining, vertices)
        await conn.execute("ANALYZE _vertex_elev")
    updated = int((await conn.execute(_UPDATE_ELEVATION)).split()[-1])
    await conn.execute("DROP TABLE _vertex_elev")
    await conn.execute("DROP TABLE _vertex")

    edges = await conn.fetchval("SELECT count(*) FROM road_edges")
    logger.info("標高: 区間 %d/%d本に値が付いた / %.1f秒",
                updated, edges, time.perf_counter() - started)
    return updated


# --- 土地被覆 ---------------------------------------------------------------


#: 帯を先に作って索引を張る。タイル1枚ごとに作り直すと、同じ区間を何度も膨らませることになる。
#: タイルの位置はWebメルカトルなので、帯もそちらへそろえてから重ねる。
_BUILD_RINGS = """
CREATE TEMP TABLE _rings ON COMMIT DROP AS
SELECT osm_way_id, segment_index, ring AS ring4326, ST_Transform(ring, 3857) AS ring
FROM (SELECT osm_way_id, segment_index,
             ST_Difference(ST_Buffer(geom::geography, $1)::geometry,
                           ST_Buffer(geom::geography, $2)::geometry) AS ring
      FROM road_edges) b
"""

#: 帯に重なる画素をクラスごとに数える。**数え上げはPostGIS側で行う**——画素を行へ
#: 展開すると、帯1本あたり千個の単位で行が出る。欠測の画素は`ST_Clip`が外す。
_COUNT_CLASSES = f"""
SELECT r.osm_way_id, r.segment_index, (vc).value::int AS cls, sum((vc).count)::bigint AS n
FROM _rings r
JOIN {_tiles("lulc")} ON t.geom && r.ring4326
CROSS JOIN LATERAL ST_ValueCount(ST_Clip(t.rast, 1, r.ring, true)) AS vc
GROUP BY r.osm_way_id, r.segment_index, (vc).value
"""


def _landcover_columns() -> list[tuple[str, str]]:
    """(割合の項目名, `edge_materials`の列名) の対応。"""
    return [(name, "lc_" + name.removesuffix("_percent")) for name, _ in PERCENT_CLASSES]


def _update_landcover_sql() -> str:
    assigned = ", ".join(f"{column} = p.{name}" for name, column in _landcover_columns())
    return f"""
UPDATE edge_materials m SET lc_valid_pixels = p.valid_pixels, {assigned}
FROM ({class_percentages_sql(_COUNT_CLASSES)}) p
WHERE p.osm_way_id = m.osm_way_id AND p.segment_index = m.segment_index
"""


async def derive_landcover(conn: asyncpg.Connection) -> int:
    started = time.perf_counter()
    tiles = await conn.fetchval(
        "SELECT count(*) FROM source_features WHERE source = 'lulc'")
    if not tiles:
        logger.warning("土地被覆タイルが1枚も取り込まれていません")
        return 0

    await conn.execute(_BUILD_RINGS, LANDCOVER_RING_OUTER_M, LANDCOVER_RING_INNER_M)
    await conn.execute("CREATE INDEX ON _rings USING GIST (ring4326)")
    await conn.execute("ANALYZE _rings")
    logger.info("土地被覆: 帯 %d本を作った。重なる画素を数える",
                await conn.fetchval("SELECT count(*) FROM _rings"))
    updated = int((await conn.execute(_update_landcover_sql())).split()[-1])

    edges = await conn.fetchval("SELECT count(*) FROM road_edges")
    logger.info("土地被覆: 区間 %d/%d本に値が付いた / タイル %d枚 / %.1f秒",
                updated, edges, tiles, time.perf_counter() - started)
    return updated


# --- 道への集約 -------------------------------------------------------------


def _way_rollup_sql() -> str:
    """道の値は区間から導く。長さで重み付けた平均にするのは、どちらも割合のため。"""
    columns = [column for _, column in _landcover_columns()]
    # 0〜100へ丸め込む。入力が割合である以上、加重平均が範囲外へ出るのはREALの丸めだけ。
    # 表の制約が受け取れる値にして渡す。
    averaged = ", ".join(
        f"least(100, greatest(0, sum(m.{c} * e.distance_m) / nullif(sum(e.distance_m) "
        f"FILTER (WHERE m.{c} IS NOT NULL), 0))) AS {c}" for c in columns)
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
