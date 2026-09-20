"""区間と道に付く「数」の値（事故・停止要因・交差点）を埋める。

`edge_materials`と`way_materials`の両方を同じ規則で埋める——同じ知識を2つの粒度で持つ
以上、数え方が違ってはいけない（地図と評価で値が食い違う原因になる）。

**停止要因は端点を0.5ずつ持つ。**交差点のノードは前後の区間が半分ずつ持ち、経路上では
合計1回になる。旧実装は「到着側の区間が持つ」だったが、それは有向Edgeに依存した規則で、
区間を1本1行にすると向きによって数えられたり数えられなかったりする。

**同じ種別の点は先にまとめる。**日本のOSMは1つの信号交差点を流入路ごと・横断歩道位置
ごとの複数ノードで描くため、素直に数えると停止回数を上回る。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.derive_counts
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
from app.domain.accident import (  # noqa: E402
    ACCIDENT_FATAL_WEIGHT,
    ACCIDENT_MATCH_MAX_DISTANCE_M,
    FATAL_SQL,
)
from app.domain.traffic import (  # noqa: E402
    INTERSECTION_DEGREE_THRESHOLD,
    POI_CLUSTER_EPS_M,
)

logger = logging.getLogger("ridecompass.derive_counts")

#: 分類器が付ける種別 → 数えるときのまとめ方。停止要因の数は`POI_COUNT_KINDS`の粒度で持つ。
COUNT_KIND_OF: dict[str, str] = {
    "traffic_signals": "signal",
    "crossing": "crossing",
    "stop": "stop",
    "give_way": "stop",
    "level_crossing": "level_crossing",
    "railway_crossing": "level_crossing",
    "barrier": "barrier",
    "traffic_calming": "barrier",
}

#: 信号が近いノードは、種別が横断歩道でも信号として数える。
_SIGNAL_OVERRIDE = "signal"

#: 種別ごとに近い点をまとめ、まとまりの代表を1点だけ残す。
_CLUSTER_SQL = """
CREATE TEMP TABLE _stop_nodes ON COMMIT DROP AS
WITH classified AS (
    SELECT nm.osm_node_id,
           CASE WHEN nm.has_traffic_signals AND nm.kind IN ('traffic_signals', 'crossing')
                THEN $2 ELSE k.count_kind END AS count_kind,
           n.geom
    FROM node_materials nm
    JOIN source_features n ON n.source = 'osm_node' AND n.natural_key = nm.osm_node_id::text
    JOIN (VALUES {kind_values}) AS k(kind, count_kind) ON k.kind = nm.kind
),
clustered AS (
    SELECT osm_node_id, count_kind,
           ST_ClusterDBSCAN(ST_Transform(geom, 3857), eps := $1, minpoints := 1)
               OVER (PARTITION BY count_kind) AS cluster_id
    FROM classified
)
SELECT DISTINCT ON (count_kind, cluster_id) osm_node_id, count_kind
FROM clustered ORDER BY count_kind, cluster_id, osm_node_id
"""

#: 端点を0.5ずつ持つ。`road_edges`は区間1本に1行なので、両端をそのまま足して割る。
_EDGE_STOP_COUNTS = """
WITH ends AS (
    SELECT osm_way_id, segment_index, from_node_id AS node_id FROM road_edges
    UNION ALL
    SELECT osm_way_id, segment_index, to_node_id FROM road_edges
),
counted AS (
    SELECT e.osm_way_id, e.segment_index, s.count_kind, count(*) * 0.5 AS n
    FROM ends e JOIN _stop_nodes s ON s.osm_node_id = e.node_id
    GROUP BY e.osm_way_id, e.segment_index, s.count_kind
)
UPDATE edge_materials m SET
    poi_signal         = COALESCE(p.signal, 0),
    poi_crossing       = COALESCE(p.crossing, 0),
    poi_stop           = COALESCE(p.stop, 0),
    poi_level_crossing = COALESCE(p.level_crossing, 0),
    poi_barrier        = COALESCE(p.barrier, 0)
FROM (
    SELECT osm_way_id, segment_index,
           sum(n) FILTER (WHERE count_kind = 'signal')          AS signal,
           sum(n) FILTER (WHERE count_kind = 'crossing')        AS crossing,
           sum(n) FILTER (WHERE count_kind = 'stop')            AS stop,
           sum(n) FILTER (WHERE count_kind = 'level_crossing')  AS level_crossing,
           sum(n) FILTER (WHERE count_kind = 'barrier')         AS barrier
    FROM counted GROUP BY osm_way_id, segment_index
) p
WHERE p.osm_way_id = m.osm_way_id AND p.segment_index = m.segment_index
"""

#: 停止要因が1つも無い区間も0で埋める（NULLは「未計算」を表すため）。
_EDGE_STOP_ZERO = """
UPDATE edge_materials SET poi_signal = 0, poi_crossing = 0, poi_stop = 0,
                          poi_level_crossing = 0, poi_barrier = 0
WHERE poi_signal IS NULL
"""

#: 交差点も端点を0.5ずつ持つ。枝が閾値以上のノードを数える。
_EDGE_INTERSECTIONS = """
WITH ends AS (
    SELECT osm_way_id, segment_index, from_node_id AS node_id FROM road_edges
    UNION ALL
    SELECT osm_way_id, segment_index, to_node_id FROM road_edges
)
UPDATE edge_materials m SET intersection_count = COALESCE(c.n, 0)
FROM (
    SELECT e.osm_way_id, e.segment_index,
           round(count(*) FILTER (WHERE nm.branch_count >= $1) * 0.5) AS n
    FROM ends e LEFT JOIN node_materials nm ON nm.osm_node_id = e.node_id
    GROUP BY e.osm_way_id, e.segment_index
) c
WHERE c.osm_way_id = m.osm_way_id AND c.segment_index = m.segment_index
"""

#: 事故は最も近い区間へ1件だけ付ける。死亡事故は重みを掛ける（判定はdomainが持つ）。
_EDGE_ACCIDENTS = f"""
WITH nearest AS (
    SELECT a.natural_key,
           CASE WHEN {FATAL_SQL} THEN $1 ELSE 1.0 END AS weight,
           (SELECT e.osm_way_id FROM road_edges e
             WHERE e.geom && ST_Expand(a.geom, $2)
             ORDER BY e.geom <-> a.geom LIMIT 1) AS osm_way_id,
           (SELECT e.segment_index FROM road_edges e
             WHERE e.geom && ST_Expand(a.geom, $2)
             ORDER BY e.geom <-> a.geom LIMIT 1) AS segment_index
    FROM source_features a WHERE a.source = 'accident'
)
UPDATE edge_materials m SET accident_count = COALESCE(s.total, 0)
FROM (
    SELECT osm_way_id, segment_index, sum(weight) AS total
    FROM nearest WHERE osm_way_id IS NOT NULL
    GROUP BY osm_way_id, segment_index
) s
WHERE s.osm_way_id = m.osm_way_id AND s.segment_index = m.segment_index
"""

_EDGE_ACCIDENT_ZERO = "UPDATE edge_materials SET accident_count = 0 WHERE accident_count IS NULL"

#: 道の値は区間の値を足し上げる。同じ数え方から作るので、地図と評価で食い違わない。
_WAY_FROM_EDGES = """
INSERT INTO way_materials (osm_way_id, accident_count, intersection_count,
                           poi_signal, poi_crossing, poi_stop, poi_level_crossing, poi_barrier,
                           source_run_id)
SELECT m.osm_way_id, sum(m.accident_count), sum(m.intersection_count),
       sum(m.poi_signal), sum(m.poi_crossing), sum(m.poi_stop),
       sum(m.poi_level_crossing), sum(m.poi_barrier), max(e.source_run_id)
FROM edge_materials m JOIN road_edges e
  ON e.osm_way_id = m.osm_way_id AND e.segment_index = m.segment_index
GROUP BY m.osm_way_id
ON CONFLICT (osm_way_id) DO UPDATE SET
    accident_count = EXCLUDED.accident_count,
    intersection_count = EXCLUDED.intersection_count,
    poi_signal = EXCLUDED.poi_signal,
    poi_crossing = EXCLUDED.poi_crossing,
    poi_stop = EXCLUDED.poi_stop,
    poi_level_crossing = EXCLUDED.poi_level_crossing,
    poi_barrier = EXCLUDED.poi_barrier
"""


async def derive(conn: asyncpg.Connection) -> None:
    started = time.perf_counter()
    kind_values = ", ".join(f"('{k}', '{v}')" for k, v in sorted(COUNT_KIND_OF.items()))
    degrees = ACCIDENT_MATCH_MAX_DISTANCE_M / 111_000.0 * 2.0

    async with conn.transaction():
        await conn.execute(_CLUSTER_SQL.format(kind_values=kind_values),
                           POI_CLUSTER_EPS_M, _SIGNAL_OVERRIDE)
        clustered = await conn.fetchval("SELECT count(*) FROM _stop_nodes")
        await conn.execute(_EDGE_STOP_COUNTS)
        await conn.execute(_EDGE_STOP_ZERO)
        await conn.execute(_EDGE_INTERSECTIONS, INTERSECTION_DEGREE_THRESHOLD)
        await conn.execute(_EDGE_ACCIDENTS, ACCIDENT_FATAL_WEIGHT, degrees)
        await conn.execute(_EDGE_ACCIDENT_ZERO)
        await conn.execute(_WAY_FROM_EDGES)

    logger.info("数の値を埋めた: まとめ後の停止要因 %d点 / %.1f秒",
                clustered, time.perf_counter() - started)


async def run(database_url: str) -> int:
    conn = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        await derive(conn)
    finally:
        await conn.close()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="区間と道に付く数の値を埋める")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    database_url = args.database_url or settings.database_url
    # 派生が変われば、それを読んで作ったキャッシュは古くなる。
    return asyncio.run(with_derived_data_revision_bump(
        run(database_url), database_url=database_url, dry_run=False))


if __name__ == "__main__":
    raise SystemExit(main())
