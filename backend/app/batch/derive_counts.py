"""区間と道に付く「数」の値（事故・停止要因・交差点）を埋める。

区間（`edge_counts`）と道（`way_counts`）の両方を同じ規則で埋める——同じ知識を2つの粒度で持つ
以上、数え方が違ってはいけない（地図と評価で値が食い違う原因になる）。道の値は区間の和から導く。

**停止要因は、まとまり1つを道路網の上の1つの場所として数える。**場所に端から入る区間と
出る区間が0.5ずつ持ち、場所を通り抜ける区間が1を持つので、経路上ではどう通っても合計1回に
なる。規則の中身は`docs/modules/backend/static-road-attributes.md`「停止要因の数え方」。
"""

import logging
import time

import asyncpg

from app.domain.accident import (
    ACCIDENT_FATAL_WEIGHT,
    ACCIDENT_MATCH_MAX_DISTANCE_M,
    BICYCLE_SQL,
    FATAL_SQL,
)
from app.domain.geo import degrees_covering_m
from app.infrastructure.source_models import (
    ACCIDENTS_SOURCE_SQL,
    WAYS_SOURCE_SQL,
    nodes_lookup_sql,
)
from app.domain.traffic import (
    INTERSECTION_DEGREE_THRESHOLD,
    PLACE_SHARE_PER_END,
    POI_CLUSTER_EPS_M,
    POI_COUNT_KINDS,
    count_kind_sql,
    place_count_sql,
    poi_count_column,
)

logger = logging.getLogger("ridecompass.derive_counts")

#: 同じ種別の点をまとまりへ分ける。まとまりの点はすべて残す——どの区間に触れるかを点ごとに見るため。
_CLUSTER_SQL = f"""
CREATE TEMP TABLE _stop_nodes ON COMMIT DROP AS
WITH classified AS (
    SELECT nm.osm_node_id, {count_kind_sql("nm")} AS count_kind, n.geom
    FROM node_kinds nm
    JOIN LATERAL {nodes_lookup_sql("nm.osm_node_id")} n ON true
    WHERE {count_kind_sql("nm")} IS NOT NULL
)
SELECT osm_node_id, count_kind, geom,
       ST_ClusterDBSCAN(ST_Transform(geom, 3857), eps := $1, minpoints := 1)
           OVER (PARTITION BY count_kind) AS cluster_id
FROM classified
"""

#: 点が乗る区間。区間の形は道の構成ノードの座標をそのまま頂点に持つので、点と交わる区間が
#: その点を頂点に持つ区間になる。道を空間で絞ってから、その区間を主キーで引く。点が区間の
#: 端点なら`at_end`。
_STOP_TOUCHES_SQL = f"""
CREATE TEMP TABLE _stop_touches ON COMMIT DROP AS
SELECT s.count_kind, s.cluster_id, s.osm_node_id, e.osm_way_id, e.segment_index,
       e.from_node_id, e.to_node_id, s.osm_node_id IN (e.from_node_id, e.to_node_id) AS at_end
FROM _stop_nodes s
JOIN {WAYS_SOURCE_SQL} w ON w.geom && s.geom AND ST_Intersects(w.geom, s.geom)
JOIN road_edges e ON e.osm_way_id = w.osm_way_id AND ST_Intersects(e.geom, s.geom)
"""

#: 停止要因の件数の列。種別は`POI_COUNT_KINDS`から導く——ここで並べると、種別を足したときに
#: 材料とタイルの列は増えるのにこの段が数えず、新しい列が0のまま残る。
_STOP_COLUMNS = {kind: poi_count_column(kind) for kind in POI_COUNT_KINDS}

#: 区間の両端のノード（区間1本につき2行）。
_EDGE_ENDS = """ends AS (
    SELECT osm_way_id, segment_index, from_node_id AS node_id FROM road_edges
    UNION ALL
    SELECT osm_way_id, segment_index, to_node_id FROM road_edges
)"""

#: まとまりが占める場所の内側のノードは、点が乗るノードと、点を途中に持つ区間が2本以上集まる
#: ノード。区間の値は内側の端の数で決まる（`place_count_sql`）。内側の端を持たない区間は、点を
#: 途中に持つときだけ数える。
_EDGE_STOP_COUNTS = f"""
WITH {_EDGE_ENDS},
through AS (
    SELECT DISTINCT count_kind, cluster_id, osm_way_id, segment_index, from_node_id, to_node_id
    FROM _stop_touches WHERE NOT at_end
),
inside AS (
    SELECT count_kind, cluster_id, osm_node_id AS node_id FROM _stop_touches WHERE at_end
    UNION
    SELECT t.count_kind, t.cluster_id, u.node_id
    FROM through t, unnest(ARRAY[t.from_node_id, t.to_node_id]) AS u(node_id)
    GROUP BY t.count_kind, t.cluster_id, u.node_id HAVING count(*) >= 2
),
bounded AS (
    SELECT i.count_kind, i.cluster_id, e.osm_way_id, e.segment_index, count(*) AS inside_ends
    FROM inside i JOIN ends e ON e.node_id = i.node_id
    GROUP BY i.count_kind, i.cluster_id, e.osm_way_id, e.segment_index
),
counted AS (
    SELECT count_kind, osm_way_id, segment_index,
           {place_count_sql("coalesce(b.inside_ends, 0)")} AS n
    FROM through t
    FULL JOIN bounded b USING (count_kind, cluster_id, osm_way_id, segment_index)
)
UPDATE edge_counts m SET
    {", ".join(f"{c} = COALESCE(p.{c}, 0)" for c in _STOP_COLUMNS.values())}
FROM (
    SELECT osm_way_id, segment_index,
           {", ".join(f"sum(n) FILTER (WHERE count_kind = '{k}') AS {c}"
                      for k, c in _STOP_COLUMNS.items())}
    FROM counted GROUP BY osm_way_id, segment_index
) p
WHERE p.osm_way_id = m.osm_way_id AND p.segment_index = m.segment_index
"""

#: 全区間の行を0で作ってから数える。停止要因・事故が1つも無い区間は0のまま残る。
_EDGE_ROWS = f"""
INSERT INTO edge_counts (osm_way_id, segment_index, accident_count, intersection_count,
                         {", ".join(_STOP_COLUMNS.values())})
SELECT osm_way_id, segment_index, 0, 0, {", ".join("0" for _ in _STOP_COLUMNS)} FROM road_edges
"""

#: 交差点のノードも、停止要因の場所と同じく端を持つ区間が分け持つ（経路上で1回になる）。
_EDGE_INTERSECTIONS = f"""
WITH {_EDGE_ENDS}
UPDATE edge_counts m SET intersection_count = c.n
FROM (
    SELECT e.osm_way_id, e.segment_index,
           count(*) FILTER (WHERE nm.branch_count >= $1) * {PLACE_SHARE_PER_END} AS n
    FROM ends e JOIN road_nodes nm ON nm.osm_node_id = e.node_id
    GROUP BY e.osm_way_id, e.segment_index
) c
WHERE c.osm_way_id = m.osm_way_id AND c.segment_index = m.segment_index
"""

#: 自転車の関わった事故を、帰属の距離の内で最も近い区間へ1件だけ付ける。鍵の2列は同じ1回の
#: 探索から取る——別々に探すと、等距離のタイで実在しない組を指しうる。
_EDGE_ACCIDENTS = f"""
WITH nearest AS (
    SELECT CASE WHEN {FATAL_SQL} THEN $1 ELSE 1.0 END AS weight, n.osm_way_id, n.segment_index
    FROM {ACCIDENTS_SOURCE_SQL} a
    CROSS JOIN LATERAL (
        SELECT e.osm_way_id, e.segment_index FROM road_edges e
        WHERE e.geom && ST_Expand(a.geom, $2)
          AND ST_DWithin(e.geom::geography, a.geom::geography, $3)
        ORDER BY ST_Distance(e.geom::geography, a.geom::geography), e.osm_way_id, e.segment_index
        LIMIT 1) n
    WHERE {BICYCLE_SQL}
)
UPDATE edge_counts m SET accident_count = COALESCE(s.total, 0)
FROM (
    SELECT osm_way_id, segment_index, sum(weight) AS total
    FROM nearest GROUP BY osm_way_id, segment_index
) s
WHERE s.osm_way_id = m.osm_way_id AND s.segment_index = m.segment_index
"""

#: 道1本へ区間の和として写す列。
_WAY_SUMMED_COLUMNS = ("accident_count", "intersection_count", *_STOP_COLUMNS.values())

#: どの道も区間を持つ（`derive_topology`は区間のある道だけを入れる）ので、全部の道が行を持つ。
_WAY_FROM_EDGES = f"""
INSERT INTO way_counts (osm_way_id, {", ".join(_WAY_SUMMED_COLUMNS)})
SELECT osm_way_id, {", ".join(f"sum({c})" for c in _WAY_SUMMED_COLUMNS)}
FROM edge_counts GROUP BY osm_way_id
"""


async def derive(conn: asyncpg.Connection) -> None:
    started = time.perf_counter()

    # 事故の行と、それを入れた取込を同じ時点から読む（間に取込が入れ替えても食い違わない）。
    async with conn.transaction(isolation="repeatable_read"):
        await conn.execute(_CLUSTER_SQL, POI_CLUSTER_EPS_M)
        await conn.execute("ANALYZE _stop_nodes")
        await conn.execute(_STOP_TOUCHES_SQL)
        await conn.execute("ANALYZE _stop_touches")
        stops = await conn.fetchrow(
            "SELECT (SELECT count(*) FROM _stop_nodes) AS points,"
            " (SELECT count(DISTINCT (count_kind, cluster_id)) FROM _stop_nodes) AS clusters,"
            " (SELECT count(DISTINCT osm_node_id) FROM _stop_touches) AS on_network")
        if stops is None:
            raise RuntimeError("集計の問い合わせが行を返さなかった")
        await conn.execute("TRUNCATE edge_counts, way_counts")
        await conn.execute(_EDGE_ROWS)
        await conn.execute("ANALYZE edge_counts")
        await conn.execute(_EDGE_STOP_COUNTS)
        await conn.execute(_EDGE_INTERSECTIONS, INTERSECTION_DEGREE_THRESHOLD)
        await conn.execute(_EDGE_ACCIDENTS, ACCIDENT_FATAL_WEIGHT, degrees_covering_m(ACCIDENT_MATCH_MAX_DISTANCE_M),
                           ACCIDENT_MATCH_MAX_DISTANCE_M)
        await conn.execute(_WAY_FROM_EDGES)
        await conn.execute("ANALYZE edge_counts, way_counts")

    logger.info("数の値を埋めた: 停止要因 %d点（まとまり %d・区間に乗る点 %d） / %.1f秒",
                stops["points"], stops["clusters"], stops["on_network"],
                time.perf_counter() - started)
