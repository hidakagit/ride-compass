"""土地被覆の画像を区間の周りの帯で数えて、区間と道の土地被覆の割合（`edge_landcover`・`way_landcover`）にする。

土地被覆の生データは`source_features`にタイル1枚=1行、`raster`として入っている。**面のまま
持つ派生は作らない**——面を読む出口は「そのまま見せる」か「線へ落とす」のどちらかで、
面のままの中間結果を要る相手がいない。

**処理はDB内で完結する。**画素をプロセスへ取り出さず、帯に重なる画素を数える
（`ST_Clip` + `ST_ValueCount`）。

**区間の値は、その区間の形と土地被覆のタイルだけで決まる**（ほかの区間を読まない）。作り直しの入口が前回の表の
スキーマを渡したとき（タイルとコードが前回と同じ）は、座標の並びまで同じ形の区間へ前回の値を写し、残りの区間だけ
帯を作って数える。前回の表は読むだけで、書くのは作業用のスキーマの表だけ。道の値はどちらでも区間の値から作り直す。
値の出た区間・道だけが行を持つ。

値の出し方そのものはdomainが持つ（`class_percentages_sql`）。このバッチは画素の数え方を
組み立てるだけで、有効画素数の下限を持たない。
"""

import logging
import time

import asyncpg

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
#: タイルの位置はWebメルカトルなので、帯もそちらへそろえてから重ねる。前回の値を写した区間（`_reused`）は作らない。
_BUILD_RINGS = """
CREATE TEMP TABLE _rings ON COMMIT DROP AS
SELECT osm_way_id, segment_index, ring AS ring4326, ST_Transform(ring, 3857) AS ring
FROM (SELECT e.osm_way_id, e.segment_index,
             ST_Difference(ST_Buffer(e.geom::geography, $1)::geometry,
                           ST_Buffer(e.geom::geography, $2)::geometry) AS ring
      FROM road_edges e
      WHERE NOT EXISTS (SELECT 1 FROM _reused r
                        WHERE r.osm_way_id = e.osm_way_id AND r.segment_index = e.segment_index)) b
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
    """(割合の項目名, 表の列名) の対応。"""
    return [(name, "lc_" + landcover_key(name)) for name, _ in PERCENT_CLASSES]


def _value_columns() -> list[str]:
    return ["lc_valid_pixels", *(column for _, column in _landcover_columns())]


def _reused_edges_sql(previous: str | None) -> str:
    """前回の値を写す区間。同じ形とみなすのは、鍵が同じで座標とその並びも同じ区間だけ（`=`。`ST_Equals`のように
    形を幾何として比べる計算をしない）。"""
    if previous is None:
        return "CREATE TEMP TABLE _reused ON COMMIT DROP AS SELECT osm_way_id, segment_index FROM road_edges WHERE false"
    return f"""
CREATE TEMP TABLE _reused ON COMMIT DROP AS
SELECT e.osm_way_id, e.segment_index
FROM road_edges e JOIN {previous}.road_edges p
  ON p.osm_way_id = e.osm_way_id AND p.segment_index = e.segment_index AND p.geom = e.geom
"""


def _copy_reused_sql(previous: str) -> str:
    """前回の値を写す。前回に値の無かった区間は前回の表に行が無く、今回も行を持たない。"""
    columns = ", ".join(_value_columns())
    return f"""
INSERT INTO edge_landcover (osm_way_id, segment_index, {columns})
SELECT p.osm_way_id, p.segment_index, {", ".join(f"p.{column}" for column in _value_columns())}
FROM _reused r JOIN {previous}.edge_landcover p
  ON p.osm_way_id = r.osm_way_id AND p.segment_index = r.segment_index
"""


def _insert_landcover_sql() -> str:
    return f"""
INSERT INTO edge_landcover (osm_way_id, segment_index, {", ".join(_value_columns())})
SELECT osm_way_id, segment_index, valid_pixels, {", ".join(f"p.{name}" for name, _ in _landcover_columns())}
FROM ({class_percentages_sql(_COUNT_CLASSES)}) p
"""


async def _derive_edges(conn: asyncpg.Connection, previous: str | None) -> int:
    started = time.perf_counter()
    tiles = await conn.fetchval(f"SELECT count(*) FROM {LANDCOVER_TILES_SQL} t")
    if not tiles:
        logger.warning("土地被覆タイルが1枚も取り込まれていません")
        return 0

    edges = await conn.fetchval("SELECT count(*) FROM road_edges")
    await conn.execute(_reused_edges_sql(previous))
    reused = await conn.fetchval("SELECT count(*) FROM _reused")
    if previous is not None:
        await conn.execute(_copy_reused_sql(previous))
    logger.info("土地被覆: 形の変わらない区間 %d本へ前回の値を写し、%d本を数える", reused, edges - reused)
    await conn.execute(_BUILD_RINGS, LANDCOVER_RING_OUTER_M, LANDCOVER_RING_INNER_M)
    await conn.execute("CREATE INDEX ON _rings USING GIST (ring4326)")
    await conn.execute("ANALYZE _rings")
    logger.info("土地被覆: 帯 %d本を作った。重なる画素を数える",
                await conn.fetchval("SELECT count(*) FROM _rings"))
    updated = int((await conn.execute(_insert_landcover_sql())).split()[-1])

    logger.info("土地被覆: 数えた区間 %d/%d本に値が付いた / タイル %d枚 / %.1f秒",
                updated, edges - reused, tiles, time.perf_counter() - started)
    return updated


# --- 道への集約 -------------------------------------------------------------


def _way_rollup_sql() -> str:
    """道の値は区間から導く。長さで重み付けた平均にするのは、どちらも割合のため。"""
    columns = [column for _, column in _landcover_columns()]
    # 割合を持つ区間が1本も無い道は集約に出ず、行を持たない。倍精度で平均してからREALの列へ入れる——REALのまま足すと
    # 丸めで100をわずかに超え、表の制約に断られる。
    averaged = ", ".join(
        f"sum(m.{c}::double precision * e.distance_m) / sum(e.distance_m::double precision) AS {c}"
        for c in columns)
    return f"""
INSERT INTO way_landcover (osm_way_id, lc_valid_pixels, {", ".join(columns)})
SELECT m.osm_way_id, sum(m.lc_valid_pixels), {averaged}
FROM edge_landcover m JOIN road_edges e
  ON e.osm_way_id = m.osm_way_id AND e.segment_index = m.segment_index
GROUP BY m.osm_way_id
"""


async def derive(conn: asyncpg.Connection, *, previous: str | None) -> None:
    """`previous`は前回の表のスキーマ。Noneなら全区間を数える。"""
    async with conn.transaction():
        await conn.execute("TRUNCATE edge_landcover, way_landcover")
        await _derive_edges(conn, previous)
        await conn.execute("ANALYZE edge_landcover")
        await conn.execute(_way_rollup_sql())
        await conn.execute("ANALYZE way_landcover")
