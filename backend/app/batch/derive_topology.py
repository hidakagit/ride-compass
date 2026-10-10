"""生データから道路網の形（`road_edges`）と、区間を持つ道の鍵（`road_ways`）と、区間の端点に集まる枝の数（`road_nodes`）を作る。

道を交差点で切って区間にする。**切る位置は「2本以上の道が通るノード」**で、これは
`osm_way`の参照ノード列だけから決まる——道路網の形は他の派生に依存しない。

**処理はDB内で完結する。**入力も出力もDBにあり、行をプロセスへ取り出さない。

`branch_count`は**そこに集まる道の本数**で、グラフの位相としての次数とは別物。2本の枝が
同じ次の交差点へ向かうと位相の次数は1つに潰れるが、自転車から見ればそこは分岐である。
交差点の密度を測るのに要るのは枝の本数のほう。

`road_nodes`と`road_ways`を先に入れる。`road_edges`の端点と親の道は、それぞれへの
外部キーで縛られている。区間・道・頂点の値は後ろの段がそれぞれの表へ書く。
"""

import logging
import time

import asyncpg

from app.infrastructure.source_models import ways_source_sql

logger = logging.getLogger("ridecompass.derive_topology")

#: `payload`はリトルエンディアンの符号付き64bit整数を並べたもの（取込の
#: `source_adapters/osm_pbf.py: way_payload`が書く）。最上位バイトのシフトは桁あふれを
#: 折り返すが、それが符号付き64bitの解釈そのものなので値は正しい。
_DECODE_WAYS = f"""
CREATE TEMP TABLE _way ON COMMIT DROP AS
SELECT w.osm_way_id AS way_id, d.node_ids, w.geom
FROM {ways_source_sql(extra_columns=("payload",))} w
CROSS JOIN LATERAL (
  SELECT array_agg(
           ((get_byte(w.payload, i * 8 + 7)::bigint << 56)
          | (get_byte(w.payload, i * 8 + 6)::bigint << 48)
          | (get_byte(w.payload, i * 8 + 5)::bigint << 40)
          | (get_byte(w.payload, i * 8 + 4)::bigint << 32)
          | (get_byte(w.payload, i * 8 + 3)::bigint << 24)
          | (get_byte(w.payload, i * 8 + 2)::bigint << 16)
          | (get_byte(w.payload, i * 8 + 1)::bigint <<  8)
          |  get_byte(w.payload, i * 8    )::bigint) ORDER BY i) AS node_ids
  FROM generate_series(0, octet_length(w.payload) / 8 - 1) AS i
) d
"""

#: 切る位置は両端と「2本以上の道が通るノード」。始点と終点が同じになる区間は、閉じた線に
#: 方位が定義できないため、中間の位置でもう1回切って端点を別にする（同じノードを2度通る
#: wayでも同じ形の区間ができるので、始点＝終点の区間全般に当てはめる）。
#:
#: 長さは測地線（楕円体）で測る。利用者が見る距離であり、時間コストの分母でもある。
#: 球で近似しても費用は変わらないので、近似する理由が無い。
_SEGMENTS = """
CREATE TEMP TABLE _seg ON COMMIT DROP AS
WITH n AS (
  SELECT way_id, ord, node_id
  FROM _way, unnest(node_ids) WITH ORDINALITY AS u(node_id, ord)),
last AS (SELECT way_id, max(ord) AS last_ord FROM n GROUP BY 1),
passes AS (SELECT node_id, count(*) AS c FROM n GROUP BY 1),
cuts0 AS (
  SELECT n.way_id, n.ord
  FROM n JOIN last ON last.way_id = n.way_id
         JOIN passes p ON p.node_id = n.node_id
  WHERE n.ord = 1 OR n.ord = last.last_ord OR p.c >= 2),
span0 AS (
  SELECT way_id, ord AS start_ord, lead(ord) OVER w AS end_ord
  FROM cuts0 WINDOW w AS (PARTITION BY way_id ORDER BY ord)),
mid AS (
  SELECT s.way_id, (s.start_ord + s.end_ord) / 2 AS ord
  FROM span0 s
  JOIN n a ON a.way_id = s.way_id AND a.ord = s.start_ord
  JOIN n z ON z.way_id = s.way_id AND z.ord = s.end_ord
  WHERE s.end_ord IS NOT NULL AND a.node_id = z.node_id
    AND s.end_ord - s.start_ord >= 2),
cuts AS (SELECT way_id, ord FROM cuts0 UNION SELECT way_id, ord FROM mid),
span AS (
  SELECT way_id, ord AS start_ord, lead(ord) OVER w AS end_ord,
         (row_number() OVER w) - 1 AS segment_index
  FROM cuts WINDOW w AS (PARTITION BY way_id ORDER BY ord)),
pts AS (
  SELECT w.way_id, dp.path[1] AS ord, dp.geom AS pt
  FROM _way w, ST_DumpPoints(w.geom) AS dp),
built AS (
  SELECT s.way_id, s.segment_index, s.start_ord, s.end_ord,
         ST_MakeLine(p.pt ORDER BY p.ord) AS geom
  FROM span s JOIN pts p
    ON p.way_id = s.way_id AND p.ord BETWEEN s.start_ord AND s.end_ord
  WHERE s.end_ord IS NOT NULL
  GROUP BY s.way_id, s.segment_index, s.start_ord, s.end_ord)
SELECT b.way_id AS osm_way_id, b.segment_index::smallint AS segment_index,
       a.node_id AS from_node_id, z.node_id AS to_node_id, b.geom,
       ST_Length(b.geom::geography)::real AS distance_m,
       degrees(ST_Azimuth(ST_StartPoint(b.geom)::geography,
                          ST_EndPoint(b.geom)::geography))::real AS bearing_deg,
       degrees(ST_Azimuth(ST_EndPoint(b.geom)::geography,
                          ST_StartPoint(b.geom)::geography))::real AS reverse_bearing_deg
FROM built b
JOIN n a ON a.way_id = b.way_id AND a.ord = b.start_ord
JOIN n z ON z.way_id = b.way_id AND z.ord = b.end_ord
"""

#: 表へ入れられない区間。数を出してから落とす——黙って減ると、次に数えたときに
#: 「取り込めていない」のか「元から無い」のかが分からない。
_USABLE = ("bearing_deg IS NOT NULL AND distance_m > 0"
           " AND NOT ST_IsEmpty(geom) AND ST_NumPoints(geom) >= 2")

_COUNT_UNUSABLE = f"""
SELECT count(*) FILTER (WHERE bearing_deg IS NULL)                        AS no_bearing,
       count(*) FILTER (WHERE distance_m <= 0)                            AS zero_length,
       count(*) FILTER (WHERE ST_IsEmpty(geom) OR ST_NumPoints(geom) < 2) AS degenerate
FROM _seg WHERE NOT ({_USABLE})
"""

_INSERT_NODES = """
INSERT INTO road_nodes (osm_node_id, branch_count)
SELECT node_id, count(*)
FROM (SELECT from_node_id AS node_id FROM _seg
      UNION ALL
      SELECT to_node_id FROM _seg) e
GROUP BY node_id
"""

_INSERT_WAYS = """
INSERT INTO road_ways (osm_way_id)
SELECT DISTINCT osm_way_id FROM _seg
"""

_INSERT_EDGES = """
INSERT INTO road_edges (osm_way_id, segment_index, from_node_id, to_node_id,
                        geom, distance_m, bearing_deg, reverse_bearing_deg)
SELECT osm_way_id, segment_index, from_node_id, to_node_id,
       geom, distance_m, bearing_deg, reverse_bearing_deg
FROM _seg
"""

async def derive(conn: asyncpg.Connection) -> None:
    started = time.perf_counter()

    async with conn.transaction():
        await conn.execute(_DECODE_WAYS)
        ways = await conn.fetchval("SELECT count(*) FROM _way")
        await conn.execute("ANALYZE _way")
        logger.info("道 %d本を読んだ。区間へ切る", ways)
        await conn.execute(_SEGMENTS)
        logger.info("切り終えた: 区間の候補 %d本。表へ入れる",
                    await conn.fetchval("SELECT count(*) FROM _seg"))

        unusable = await conn.fetchrow(_COUNT_UNUSABLE)
        if unusable is None:
            raise RuntimeError("集計の問い合わせが行を返さなかった")
        if any(unusable.values()):
            logger.warning(
                "表へ入れられない区間を落とした: 方位が定義できない %d本 / 長さ0 %d本 / "
                "頂点不足 %d本", unusable["no_bearing"], unusable["zero_length"],
                unusable["degenerate"])
            await conn.execute(f"DELETE FROM _seg WHERE NOT ({_USABLE})")
        await conn.execute("ANALYZE _seg")

        # 外部キーがある以上、参照する側とされる側は1文で空にする（2文に分けると
        # 同じトランザクション内でも「参照されている表は削除できない」で止まる）。CASCADEは、これらを外部キーで指す
        # 値の表も空にする——区間・道・頂点を作り直せば、その値は後ろの段が書き直す。
        await conn.execute("TRUNCATE road_edges, road_nodes, road_ways CASCADE")
        # 外部キーが指す先を先に作る。
        nodes = await conn.execute(_INSERT_NODES)
        await conn.execute(_INSERT_WAYS)
        edges = await conn.execute(_INSERT_EDGES)
        # 後ろの段はこれらの表を読む。autovacuumは既定60秒周期の背景処理で、派生は
        # 数秒で走り切るため、統計が付くのを待てない。無いまま読まれると実行計画が
        # 桁で外れる。
        await conn.execute("ANALYZE road_edges, road_nodes, road_ways")

    logger.info("導出完了: way %d本 → 区間 %d本 / ノード %d点 / %.1f秒",
                ways, int(edges.split()[-1]), int(nodes.split()[-1]), time.perf_counter() - started)
