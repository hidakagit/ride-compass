"""生データから道路網の形（`road_edges`）と、ノードに集まる枝の数（`node_materials`）を作る。

道を交差点で切って区間にする。**切る位置は「2本以上の道が通るノード」**で、これは
`osm_way`の参照ノード列だけから決まる——道路網の形は他の派生に依存しない。

**処理はDB内で完結する。**入力も出力もDBにあり、行をプロセスへ取り出さない。

`branch_count`は**そこに集まる道の本数**で、グラフの位相としての次数とは別物。2本の枝が
同じ次の交差点へ向かうと位相の次数は1つに潰れるが、自転車から見ればそこは分岐である。
交差点の密度を測るのに要るのは枝の本数のほう。

`node_materials`を先に入れる。`road_edges`の端点はここへの外部キーで縛られている。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.derive_topology
    .venv\\Scripts\\python.exe -m app.batch.derive_topology --database-url ...
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

logger = logging.getLogger("ridecompass.derive_topology")

#: `payload`はリトルエンディアンの符号付き64bit整数を並べたもの（取込が`struct.pack`で
#: 書く）。最上位バイトのシフトは桁あふれを折り返すが、それが符号付き64bitの解釈そのもの
#: なので値は正しい。
_DECODE_WAYS = """
CREATE TEMP TABLE _way ON COMMIT DROP AS
SELECT w.natural_key::bigint AS way_id, d.node_ids, w.geom
FROM source_features w
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
WHERE w.source = 'osm_way' AND w.payload IS NOT NULL
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
INSERT INTO node_materials (osm_node_id, branch_count, source_run_id)
SELECT node_id, count(*), $1
FROM (SELECT from_node_id AS node_id FROM _seg
      UNION ALL
      SELECT to_node_id FROM _seg) e
GROUP BY node_id
"""

_INSERT_EDGES = """
INSERT INTO road_edges (osm_way_id, segment_index, from_node_id, to_node_id,
                        geom, distance_m, bearing_deg, reverse_bearing_deg, source_run_id)
SELECT osm_way_id, segment_index, from_node_id, to_node_id,
       geom, distance_m, bearing_deg, reverse_bearing_deg, $1
FROM _seg
"""

#: 値はこれから埋める。行だけ先に作り、未計算をNULLで表す。
_INSERT_EDGE_MATERIALS = """
INSERT INTO edge_materials (osm_way_id, segment_index, source_run_id)
SELECT osm_way_id, segment_index, source_run_id FROM road_edges
"""


async def _latest_run(conn: asyncpg.Connection, source: str) -> int:
    run_id = await conn.fetchval(
        "SELECT max(run_id) FROM source_runs WHERE source = $1 AND status = 'succeeded'", source)
    if run_id is None:
        raise RuntimeError(f"'{source}' の取込が成功していません")
    return run_id


async def derive(conn: asyncpg.Connection) -> tuple[int, int]:
    run_id = await _latest_run(conn, "osm_way")
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
        if any(unusable.values()):
            logger.warning(
                "表へ入れられない区間を落とした: 方位が定義できない %d本 / 長さ0 %d本 / "
                "頂点不足 %d本", unusable["no_bearing"], unusable["zero_length"],
                unusable["degenerate"])
            await conn.execute(f"DELETE FROM _seg WHERE NOT ({_USABLE})")
        await conn.execute("ANALYZE _seg")

        # 端点の外部キーがある以上、参照する側とされる側は1文で空にする（2文に分けると
        # 同じトランザクション内でも「参照されている表は削除できない」で止まる）。
        await conn.execute("TRUNCATE road_edges, node_materials CASCADE")
        # 端点の外部キーが指す先を先に作る。
        nodes = await conn.execute(_INSERT_NODES, run_id)
        edges = await conn.execute(_INSERT_EDGES, run_id)
        await conn.execute(_INSERT_EDGE_MATERIALS)
        # 後ろの段はこの3表を読む。autovacuumは既定60秒周期の背景処理で、派生は
        # 数秒で走り切るため、統計が付くのを待てない。無いまま読まれると実行計画が
        # 桁で外れる。
        await conn.execute("ANALYZE road_edges, node_materials, edge_materials")

    edge_count = int(edges.split()[-1])
    node_count = int(nodes.split()[-1])
    logger.info("導出完了: way %d本 → 区間 %d本 / ノード %d点 / %.1f秒",
                ways, edge_count, node_count, time.perf_counter() - started)
    return edge_count, node_count


async def run(database_url: str) -> int:
    conn = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        await derive(conn)
    finally:
        await conn.close()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="生データから道路網の形を導く")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    database_url = args.database_url or settings.database_url
    return asyncio.run(with_derived_data_revision_bump(
        run(database_url), database_url=database_url, dry_run=False))


if __name__ == "__main__":
    raise SystemExit(main())
