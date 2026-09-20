"""道1本の性質（上下線分離・指定路線）を埋める。区間粒度の対応物を持たない値。

**通行方向はここでタグから決める**（`domain/traffic.py: resolve_direction`）。
判定はPythonの1実装だけが持ち、SQLへ書き写さない——上下線分離の判定は相方の向きも
見るため、いったん一時表へ出してからSQLへ渡す。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.derive_way_materials
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from app.batch._common import asyncpg_dsn, with_derived_data_revision_bump  # noqa: E402
from app.config import settings  # noqa: E402
from app.domain import divided_carriageway as dc  # noqa: E402
from app.domain.designation import (  # noqa: E402
    DESIGNATION_BUFFER_WIDTH_M,
    DESIGNATION_IMPORT_KINDS,
    DESIGNATION_MATCH_MIN_RATIO,
)
from app.domain.traffic import resolve_direction  # noqa: E402

logger = logging.getLogger("ridecompass.derive_way_materials")


def designation_column(kind: str) -> str:
    """指定路線の種別に対応する`way_materials`の列名。種別が増えても対応表は要らない。"""
    return f"designation_{kind}"


#: 判定に要るものを1つの表へまとめ、索引を張る。相方探しは自分自身を何度も引くため、
#: `source_features`の全ソースが載る親表を毎回たどらせない。
_WAY_FACTS = """
CREATE TEMP TABLE _way_facts ON COMMIT DROP AS
SELECT s.natural_key::bigint AS osm_way_id, s.geom,
       d.direction,
       s.attrs->>'highway' AS highway,
       lower(btrim(coalesce(s.attrs->>'carriageway', ''))) AS carriageway,
       COALESCE(NULLIF(btrim(s.attrs->>'ref'), ''), NULLIF(btrim(s.attrs->>'name'), '')) AS ident,
       degrees(ST_Azimuth(ST_StartPoint(s.geom)::geography, ST_EndPoint(s.geom)::geography))
           + CASE WHEN d.direction = 'backward' THEN 180 ELSE 0 END AS travel_deg
FROM source_features s
JOIN way_materials d ON d.osm_way_id = s.natural_key::bigint
WHERE s.source = 'osm_way'
"""

#: 逆向きに並走しているか。方位の差が180度に近いことで見る。
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


#: 帯は指定路線1本ごとに決まるので、先に1回だけ作る（`MATERIALIZED`でインライン化を禁じ、
#: 道との突き合わせの中で行ごとに作り直されるのを防ぐ）。
#:
#: 突き合わせは`geometry`同士の`ST_Intersects`にする。`::geography`を挟むとPostGISが
#: GiSTを使わず総当たりに落ちる。
#:
#: 同じ道へ複数の指定路線が寄与しうるため、交差をまとめてから測る（二重計上を避ける）。
#: `ST_Intersection`の格子（1e-7度、OSMの座標精度と同じ桁）は必須——省くと、交差して
#: いるのに空の線が返ることがある（線が帯の中心軸と完全に重なるとき）。
_MATCH_DESIGNATIONS = """
WITH buffered AS MATERIALIZED (
    SELECT natural_key, attrs->>'kind' AS kind,
           ST_Buffer(geom::geography, $1)::geometry AS buffer_geom
    FROM source_features WHERE source = 'designation' AND attrs->>'kind' = $2
),
matched AS (
    SELECT w.natural_key::bigint AS osm_way_id,
           ST_Length(w.geom::geography) AS way_length_m,
           ST_Union(ST_CollectionExtract(ST_Intersection(w.geom, b.buffer_geom, 1e-7), 2))
               AS unioned
    FROM buffered b
    JOIN source_features w ON w.source = 'osm_way' AND ST_Intersects(w.geom, b.buffer_geom)
    GROUP BY w.source, w.natural_key
)
SELECT osm_way_id, ST_Length(unioned::geography) / NULLIF(way_length_m, 0) AS ratio
FROM matched
"""


async def _load_directions(conn: asyncpg.Connection) -> int:
    rows = await conn.fetch(
        "SELECT natural_key, attrs FROM source_features WHERE source = 'osm_way'")
    directions = []
    for row in rows:
        attrs = row["attrs"]
        tags = json.loads(attrs) if isinstance(attrs, str) else dict(attrs)
        directions.append((int(row["natural_key"]), resolve_direction(tags)))
    await conn.executemany(
        "UPDATE way_materials SET direction = $2 WHERE osm_way_id = $1", directions)
    return len(directions)


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


async def derive_designations(conn: asyncpg.Connection) -> dict[str, int]:
    started = time.perf_counter()
    matched: dict[str, int] = {}
    for kind in DESIGNATION_IMPORT_KINDS:
        rows = await conn.fetch(_MATCH_DESIGNATIONS, DESIGNATION_BUFFER_WIDTH_M, kind)
        hits = [(r["osm_way_id"], r["ratio"]) for r in rows
                if r["ratio"] is not None and r["ratio"] >= DESIGNATION_MATCH_MIN_RATIO]
        column = designation_column(kind)
        await conn.execute(f"UPDATE way_materials SET {column} = NULL")
        await conn.executemany(
            f"UPDATE way_materials SET {column} = $2 WHERE osm_way_id = $1", hits)
        matched[kind] = len(hits)
        if not hits:
            logger.warning("指定路線 kind=%s のマッチが0件です（取込済みか確認すること）", kind)
    logger.info("指定路線: %s / %.1f秒", matched, time.perf_counter() - started)
    return matched


async def derive(conn: asyncpg.Connection) -> None:
    async with conn.transaction():
        count = await _load_directions(conn)
        logger.info("通行方向を決めた: %d本", count)
        await derive_divided(conn)
        await derive_designations(conn)


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
    # 派生が変われば、それを読んで作ったキャッシュは古くなる。
    return asyncio.run(with_derived_data_revision_bump(
        run(database_url), database_url=database_url, dry_run=False))


if __name__ == "__main__":
    raise SystemExit(main())
