"""区間と道に付く「数」の値（事故・停止要因・交差点）を埋める。

`edge_materials`と`way_materials`の両方を同じ規則で埋める——同じ知識を2つの粒度で持つ
以上、数え方が違ってはいけない（地図と評価で値が食い違う原因になる）。

**停止要因は、まとまり1つを道路網の上の1つの場所として数える。**場所に端から入る区間と
出る区間が0.5ずつ持ち、場所を通り抜ける区間が1を持つので、経路上ではどう通っても合計1回に
なる。規則の中身は`docs/modules/backend/static-road-attributes.md`「停止要因の数え方」。
"""

import logging
import time

import asyncpg

from app.batch._common import reset_columns_sql
from app.domain.accident import (
    ACCIDENT_FATAL_WEIGHT,
    ACCIDENT_MATCH_MAX_DISTANCE_M,
    BICYCLE_PARTY_TYPE_CODES,
    FATAL_SQL,
    bicycle_sql,
)
from app.domain.geo import KM_PER_DEGREE_LATITUDE
from app.infrastructure.source_models import ACCIDENTS_SOURCE_SQL, WAYS_SOURCE_SQL, nodes_lookup_sql
from app.domain.traffic import (
    INTERSECTION_DEGREE_THRESHOLD,
    POI_CLUSTER_EPS_M,
    POI_COUNT_KINDS,
    count_kind_sql,
    poi_count_column,
)

logger = logging.getLogger("ridecompass.derive_counts")

#: 同じ種別の点をまとまりへ分ける。まとまりの点はすべて残す——どの区間に触れるかを点ごとに見るため。
_CLUSTER_SQL = f"""
CREATE TEMP TABLE _stop_nodes ON COMMIT DROP AS
WITH classified AS (
    SELECT nm.osm_node_id, {count_kind_sql("nm")} AS count_kind, n.geom
    FROM node_materials nm
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
#: 材料とタイルの列は増えるのにこの段が数えず、新しい列が未計算（NULL）のまま残る。
_STOP_COLUMNS = {kind: poi_count_column(kind) for kind in POI_COUNT_KINDS}

#: まとまりが占める場所の内側のノードは、点が乗るノードと、点を途中に持つ区間が2本以上集まる
#: ノード。区間の値は内側の端の数で決まる（0本なら通り抜けるので1、1本なら0.5、2本なら場所の
#: 中なので0）。内側の端を持たない区間は、点を途中に持つときだけ数える。
_EDGE_STOP_COUNTS = f"""
WITH ends AS (
    SELECT osm_way_id, segment_index, from_node_id AS node_id FROM road_edges
    UNION ALL
    SELECT osm_way_id, segment_index, to_node_id FROM road_edges
),
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
           CASE coalesce(b.inside_ends, 0) WHEN 0 THEN 1.0 WHEN 1 THEN 0.5 ELSE 0 END AS n
    FROM through t
    FULL JOIN bounded b USING (count_kind, cluster_id, osm_way_id, segment_index)
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

#: 数える前に0へ戻す。停止要因・事故が1つも無い区間も0になる（NULLは「未計算」を表すため）。
#: 交差点の数は全区間を書くので戻さない。
_EDGE_RESET = reset_columns_sql(
    "edge_materials", {c: "0" for c in ("accident_count", *_STOP_COLUMNS.values())})

#: 交差点のノードも前後の区間が0.5ずつ持つ（経路上で1回になる）。
_EDGE_INTERSECTIONS = """
WITH ends AS (
    SELECT osm_way_id, segment_index, from_node_id AS node_id FROM road_edges
    UNION ALL
    SELECT osm_way_id, segment_index, to_node_id FROM road_edges
)
UPDATE edge_materials m SET intersection_count = c.n
FROM (
    SELECT e.osm_way_id, e.segment_index,
           count(*) FILTER (WHERE nm.branch_count >= $1) * 0.5 AS n
    FROM ends e JOIN node_materials nm ON nm.osm_node_id = e.node_id
    GROUP BY e.osm_way_id, e.segment_index
) c
WHERE c.osm_way_id = m.osm_way_id AND c.segment_index = m.segment_index
"""

#: 自転車の関わった事故を、帰属の距離の内で最も近い区間へ1件だけ付ける。鍵の2列は同じ1回の
#: 探索から取る——別々に探すと、等距離のタイで実在しない組を指しうる。近さは地上の距離（m）で
#: 比べる。緯度経度の度のまま比べると経度1度が緯度1度より短いぶん東西の距離を長く見て、南北に
#: 少し遠い区間へ付けてしまう。
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
    WHERE {bicycle_sql("$4")}
)
UPDATE edge_materials m SET accident_count = COALESCE(s.total, 0)
FROM (
    SELECT osm_way_id, segment_index, sum(weight) AS total
    FROM nearest GROUP BY osm_way_id, segment_index
) s
WHERE s.osm_way_id = m.osm_way_id AND s.segment_index = m.segment_index
"""

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
    # 事故の前置フィルタの箱。経度1度は緯度1度より短いので半径の2倍の度で取る（緯度60度まで円を含む）。
    degrees = ACCIDENT_MATCH_MAX_DISTANCE_M / (KM_PER_DEGREE_LATITUDE * 1000.0) * 2.0

    async with conn.transaction():
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
        await conn.execute(_EDGE_RESET)
        await conn.execute(_EDGE_STOP_COUNTS)
        await conn.execute(_EDGE_INTERSECTIONS, INTERSECTION_DEGREE_THRESHOLD)
        await conn.execute(_EDGE_ACCIDENTS, ACCIDENT_FATAL_WEIGHT, degrees,
                           ACCIDENT_MATCH_MAX_DISTANCE_M, sorted(BICYCLE_PARTY_TYPE_CODES))
        await conn.execute(_WAY_ORPHANS)
        await conn.execute(_WAY_FROM_EDGES)
        await conn.execute("ANALYZE way_materials")

    logger.info("数の値を埋めた: 停止要因 %d点（まとまり %d・区間に乗る点 %d） / %.1f秒",
                stops["points"], stops["clusters"], stops["on_network"],
                time.perf_counter() - started)
