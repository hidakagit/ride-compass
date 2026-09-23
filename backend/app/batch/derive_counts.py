"""区間と道に付く「数」の値（事故・停止要因・交差点）を埋める。

`edge_materials`と`way_materials`の両方を同じ規則で埋める——同じ知識を2つの粒度で持つ
以上、数え方が違ってはいけない（地図と評価で値が食い違う原因になる）。

**停止要因は端点を0.5ずつ持つ。**交差点のノードは前後の区間が半分ずつ持ち、経路上では
合計1回になる。

**同じ種別の点は先にまとめる。**日本のOSMは1つの信号交差点を流入路ごと・横断歩道位置
ごとの複数ノードで描くため、素直に数えると停止回数を上回る。
"""

import logging
import time

import asyncpg

from app.domain.accident import (
    ACCIDENT_FATAL_WEIGHT,
    ACCIDENT_MATCH_MAX_DISTANCE_M,
    FATAL_SQL,
)
from app.domain.geo import KM_PER_DEGREE_LATITUDE
from app.domain.material_sql import nodes_lookup_sql
from app.domain.traffic import (
    INTERSECTION_DEGREE_THRESHOLD,
    POI_CLUSTER_EPS_M,
    POI_COUNT_KINDS,
    poi_count_column,
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

#: まとまりの代表を1点だけ残す。
_CLUSTER_SQL = f"""
CREATE TEMP TABLE _stop_nodes ON COMMIT DROP AS
WITH classified AS (
    SELECT nm.osm_node_id,
           CASE WHEN nm.has_traffic_signals AND nm.kind IN ('traffic_signals', 'crossing')
                THEN $2 ELSE k.count_kind END AS count_kind,
           n.geom
    FROM node_materials nm
    JOIN LATERAL {nodes_lookup_sql("nm.osm_node_id")} n ON true
    JOIN (VALUES {{kind_values}}) AS k(kind, count_kind) ON k.kind = nm.kind
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

#: 停止要因の件数の列。種別は`POI_COUNT_KINDS`から導く——ここで並べると、種別を足したときに
#: 材料とタイルの列は増えるのにこの段が数えず、新しい列が未計算（NULL）のまま残る。
_STOP_COLUMNS = {kind: poi_count_column(kind) for kind in POI_COUNT_KINDS}

#: `road_edges`は区間1本に1行なので、両端をそのまま足して割ると0.5ずつになる。
_EDGE_STOP_COUNTS = f"""
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
    {", ".join(f"{c} = COALESCE(p.{c}, 0)" for c in _STOP_COLUMNS.values())}
FROM (
    SELECT osm_way_id, segment_index,
           {", ".join(f"sum(n) FILTER (WHERE count_kind = '{k}') AS {c}"
                      for k, c in _STOP_COLUMNS.items())}
    FROM counted GROUP BY osm_way_id, segment_index
) p
WHERE p.osm_way_id = m.osm_way_id AND p.segment_index = m.segment_index
"""

#: 停止要因が1つも無い区間も0で埋める（NULLは「未計算」を表すため）。
_EDGE_STOP_ZERO = f"""
UPDATE edge_materials SET {", ".join(f"{c} = COALESCE({c}, 0)" for c in _STOP_COLUMNS.values())}
WHERE {" OR ".join(f"{c} IS NULL" for c in _STOP_COLUMNS.values())}
"""

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

#: 事故は最も近い区間へ1件だけ付ける。鍵の2列は同じ1回の探索から取る——別々に探すと、
#: 等距離のタイで実在しない組を指しうる。
_EDGE_ACCIDENTS = f"""
WITH nearest AS (
    SELECT CASE WHEN {FATAL_SQL} THEN $1 ELSE 1.0 END AS weight, n.osm_way_id, n.segment_index
    FROM source_features a
    CROSS JOIN LATERAL (
        SELECT e.osm_way_id, e.segment_index FROM road_edges e
        WHERE e.geom && ST_Expand(a.geom, $2)
        ORDER BY e.geom <-> a.geom, e.osm_way_id, e.segment_index LIMIT 1) n
    WHERE a.source = 'accident'
)
UPDATE edge_materials m SET accident_count = COALESCE(s.total, 0)
FROM (
    SELECT osm_way_id, segment_index, sum(weight) AS total
    FROM nearest GROUP BY osm_way_id, segment_index
) s
WHERE s.osm_way_id = m.osm_way_id AND s.segment_index = m.segment_index
"""

_EDGE_ACCIDENT_ZERO = "UPDATE edge_materials SET accident_count = 0 WHERE accident_count IS NULL"

_WAY_ORPHANS = """
DELETE FROM way_materials w
WHERE NOT EXISTS (SELECT 1 FROM road_edges e WHERE e.osm_way_id = w.osm_way_id)
"""

#: 道1本へ区間の和として写す列。
_WAY_SUMMED_COLUMNS = ("accident_count", "intersection_count", *_STOP_COLUMNS.values())

_WAY_FROM_EDGES = f"""
INSERT INTO way_materials (osm_way_id, {", ".join(_WAY_SUMMED_COLUMNS)}, source_run_id)
SELECT m.osm_way_id, {", ".join(f"sum(m.{c})" for c in _WAY_SUMMED_COLUMNS)}, max(e.source_run_id)
FROM edge_materials m JOIN road_edges e
  ON e.osm_way_id = m.osm_way_id AND e.segment_index = m.segment_index
GROUP BY m.osm_way_id
ON CONFLICT (osm_way_id) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in _WAY_SUMMED_COLUMNS)},
    source_run_id = EXCLUDED.source_run_id
"""


async def derive(conn: asyncpg.Connection) -> None:
    started = time.perf_counter()
    kind_values = ", ".join(f"('{k}', '{v}')" for k, v in sorted(COUNT_KIND_OF.items()))
    degrees = ACCIDENT_MATCH_MAX_DISTANCE_M / (KM_PER_DEGREE_LATITUDE * 1000.0) * 2.0

    async with conn.transaction():
        await conn.execute(_CLUSTER_SQL.format(kind_values=kind_values),
                           POI_CLUSTER_EPS_M, _SIGNAL_OVERRIDE)
        clustered = await conn.fetchval("SELECT count(*) FROM _stop_nodes")
        await conn.execute(_EDGE_STOP_COUNTS)
        await conn.execute(_EDGE_STOP_ZERO)
        await conn.execute(_EDGE_INTERSECTIONS, INTERSECTION_DEGREE_THRESHOLD)
        await conn.execute(_EDGE_ACCIDENTS, ACCIDENT_FATAL_WEIGHT, degrees)
        await conn.execute(_EDGE_ACCIDENT_ZERO)
        await conn.execute(_WAY_ORPHANS)
        await conn.execute(_WAY_FROM_EDGES)
        await conn.execute("ANALYZE way_materials")

    logger.info("数の値を埋めた: まとめ後の停止要因 %d点 / %.1f秒",
                clustered, time.perf_counter() - started)
