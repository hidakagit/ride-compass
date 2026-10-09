"""土地被覆の画像を区間の周りの帯で数えて、区間と道の土地被覆の割合にする。

土地被覆の生データは`source_features`にタイル1枚=1行、`raster`として入っている。**面のまま
持つ派生は作らない**——面を読む出口は「そのまま見せる」か「線へ落とす」のどちらかで、
面のままの中間結果を要る相手がいない。

**処理はDB内で完結する。**画素をプロセスへ取り出さず、帯に重なる画素を数える
（`ST_Clip` + `ST_ValueCount`）。

値の出し方そのものはdomainが持つ（`class_percentages_sql`）。このバッチは画素の数え方を
組み立てるだけで、有効画素数の下限を持たない。
"""

import logging
import time

import asyncpg

from app.batch.common import reset_columns_sql
from app.domain.landcover import (
    LANDCOVER_RING_INNER_M,
    LANDCOVER_RING_OUTER_M,
    PERCENT_CLASSES,
    class_percentages_sql,
    landcover_key,
)
from app.infrastructure.source_models import LANDCOVER_TILES_SQL

logger = logging.getLogger("ridecompass.derive_landcover")


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
JOIN {LANDCOVER_TILES_SQL} t ON t.geom && r.ring4326
CROSS JOIN LATERAL ST_ValueCount(ST_Clip(t.rast, 1, r.ring, true)) AS vc
GROUP BY r.osm_way_id, r.segment_index, (vc).value
"""


def _landcover_columns() -> list[tuple[str, str]]:
    """(割合の項目名, `edge_materials`の列名) の対応。"""
    return [(name, "lc_" + landcover_key(name)) for name, _ in PERCENT_CLASSES]


def _reset_landcover_sql(table: str) -> str:
    columns = ["lc_valid_pixels", *(column for _, column in _landcover_columns())]
    return reset_columns_sql(table, dict.fromkeys(columns, "NULL"))


def _update_landcover_sql() -> str:
    assigned = ", ".join(f"{column} = p.{name}" for name, column in _landcover_columns())
    return f"""
UPDATE edge_materials m SET lc_valid_pixels = p.valid_pixels, {assigned}
FROM ({class_percentages_sql(_COUNT_CLASSES)}) p
WHERE p.osm_way_id = m.osm_way_id AND p.segment_index = m.segment_index
"""


async def _derive_edges(conn: asyncpg.Connection) -> int:
    started = time.perf_counter()
    await conn.execute(_reset_landcover_sql("edge_materials"))
    tiles = await conn.fetchval(f"SELECT count(*) FROM {LANDCOVER_TILES_SQL} t")
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
    # 有効画素のある区間は割合を全部持つ（表の制約）ので、集める区間はどの列も同じ。割合を持つ区間が1本も無い道は
    # 集約に出ず、有効画素も割合もNULLのまま残る。倍精度で平均してからREALの列へ入れる——REALのまま足すと
    # 丸めで100をわずかに超え、表の制約に断られる。
    averaged = ", ".join(
        f"sum(m.{c}::double precision * e.distance_m) / sum(e.distance_m::double precision) AS {c}"
        for c in columns)
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
        await _derive_edges(conn)
        await conn.execute(_reset_landcover_sql("way_materials"))
        await conn.execute(_way_rollup_sql())
