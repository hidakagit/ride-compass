"""道1本の性質（通行方向・上下線分離）を埋める。区間粒度の対応物を持たない値。

**通行方向はここでタグから決める**。引き当ての表は`domain/traffic.py`が持ち、
このバッチはそれをSQLへ渡すだけで、タグを読むために行を取り出さない。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.derive_way_materials
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from app.batch._common import asyncpg_dsn, with_derived_data_revision_bump  # noqa: E402
from app.config import settings  # noqa: E402
from app.domain import divided_carriageway as dc  # noqa: E402
from app.domain.material_sql import WAYS_SOURCE_SQL  # noqa: E402
from app.domain.traffic import direction_sql  # noqa: E402

logger = logging.getLogger("ridecompass.derive_way_materials")


#: 判定に要るものを1つの表へまとめ、索引を張る。相方探しは自分自身を何度も引くため、
#: `source_features`の全ソースが載る親表を毎回たどらせない。
_WAY_FACTS = f"""
CREATE TEMP TABLE _way_facts ON COMMIT DROP AS
SELECT w.osm_way_id, w.geom,
       d.direction,
       w.highway,
       lower(btrim(coalesce(w.tags->>'carriageway', ''))) AS carriageway,
       COALESCE(NULLIF(btrim(w.tags->>'ref'), ''), NULLIF(btrim(w.tags->>'name'), '')) AS ident,
       degrees(ST_Azimuth(ST_StartPoint(w.geom)::geography, ST_EndPoint(w.geom)::geography))
           + CASE WHEN d.direction = 'backward' THEN 180 ELSE 0 END AS travel_deg
FROM {WAYS_SOURCE_SQL} w
JOIN way_materials d ON d.osm_way_id = w.osm_way_id
"""

#: 逆向きに並走しているか。
_ANTIPARALLEL = """
abs(((b.travel_deg - t.travel_deg)::numeric % 360 + 360) % 360 - 180) < $1
"""


def _divided_sql() -> str:
    fractions = ", ".join(str(f) for f in dc.SAMPLE_FRACTIONS)
    named_deg = dc.NAMED_GAP_M / dc.PREFILTER_METERS_PER_DEGREE
    geometric_deg = dc.GEOMETRIC_GAP_M / dc.PREFILTER_METERS_PER_DEGREE
    return f"""
UPDATE way_materials m SET divided = v.divided
FROM (
    SELECT t.osm_way_id,
           t.direction <> 'both' AND t.travel_deg IS NOT NULL AND (
               -- 条件1: OSM自身の申告
               t.carriageway = ANY($4)
               -- 条件2: 同じ路線番号/名前の対向一方通行が近くにある
               OR (t.ident IS NOT NULL AND EXISTS (
                   SELECT 1 FROM _way_facts b
                   WHERE b.osm_way_id <> t.osm_way_id
                     AND b.direction <> 'both'
                     AND b.ident = t.ident
                     AND b.geom && ST_Expand(t.geom, {named_deg})
                     AND ST_DWithin(t.geom::geography, b.geom::geography, $2)
                     AND {_ANTIPARALLEL}
               ))
               -- 条件3: 全長にわたって対向する同種別の一方通行が寄り添う
               OR NOT EXISTS (
                   SELECT 1 FROM unnest(ARRAY[{fractions}]::double precision[]) AS f
                   WHERE NOT EXISTS (
                       SELECT 1 FROM _way_facts b
                       WHERE b.osm_way_id <> t.osm_way_id
                         AND b.direction <> 'both'
                         AND b.highway = t.highway
                         -- 名前が食い違う道どうしは対にしない（両方無名は許す）。
                         -- 主線に沿う側道を上下線の片側と見なさないため。
                         AND (b.ident IS NOT DISTINCT FROM t.ident
                              OR t.ident IS NULL OR b.ident IS NULL)
                         -- 前置フィルタは標本点まわりの小さな箱にする（wayの全体bboxで
                         -- 広げると長い道で候補が爆発する）。索引を使わせるためにあり、
                         -- 正確な距離は次の行が決める。
                         AND b.geom && ST_Expand(
                               ST_LineInterpolatePoint(t.geom, f), {geometric_deg})
                         AND ST_DWithin(
                               ST_LineInterpolatePoint(t.geom, f)::geography,
                               b.geom::geography, $3)
                         AND {_ANTIPARALLEL}
                   )
               )
           ) AS divided
    FROM _way_facts t
) v
WHERE v.osm_way_id = m.osm_way_id
"""


#: 引き当てる側が期待する形（`id`・`tags`）へ生データを写す。
_SOURCE_WAYS = f"SELECT osm_way_id AS id, tags FROM {WAYS_SOURCE_SQL} w"

_UPDATE_DIRECTIONS = f"""
UPDATE way_materials m SET direction = d.direction
FROM ({direction_sql(_SOURCE_WAYS)}) d
WHERE d.id = m.osm_way_id
"""


async def _load_directions(conn: asyncpg.Connection) -> int:
    return int((await conn.execute(_UPDATE_DIRECTIONS)).split()[-1])


async def derive_divided(conn: asyncpg.Connection) -> int:
    started = time.perf_counter()
    await conn.execute(_WAY_FACTS)
    await conn.execute("CREATE INDEX ON _way_facts USING GIST (geom)")
    await conn.execute("ANALYZE _way_facts")
    await conn.execute(_divided_sql(), dc.BEARING_TOLERANCE_DEG, dc.NAMED_GAP_M,
                       dc.GEOMETRIC_GAP_M, list(dc.TAG_VALUES))
    divided = await conn.fetchval("SELECT count(*) FROM way_materials WHERE divided")
    logger.info("上下線分離: 該当 %d本 / %.1f秒", divided, time.perf_counter() - started)
    return divided


async def derive(conn: asyncpg.Connection) -> None:
    async with conn.transaction():
        count = await _load_directions(conn)
        logger.info("通行方向を決めた: %d本", count)
        await derive_divided(conn)


async def run(database_url: str) -> int:
    conn = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        await derive(conn)
    finally:
        await conn.close()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="道1本の性質を埋める")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    database_url = args.database_url or settings.database_url
    return asyncio.run(with_derived_data_revision_bump(
        run(database_url), database_url=database_url, dry_run=False))


if __name__ == "__main__":
    raise SystemExit(main())
