"""生データから道路網の形（`road_edges`）と、ノードに付く値（`node_materials`）を作る。

道を交差点で切って区間にする。**切る位置は「2本以上の道が通るノード」**で、これは
`osm_way`の参照ノード列だけから決まる——道路網の形は他の派生に依存しない。

`branch_count`は**そこに集まる道の本数**で、グラフの位相としての次数とは別物。2本の枝が
同じ次の交差点へ向かうと位相の次数は1つに潰れるが、自転車から見ればそこは分岐である。
交差点の密度を測るのに要るのは枝の本数のほう。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.derive_topology
    .venv\\Scripts\\python.exe -m app.batch.derive_topology --database-url ...
"""

import argparse
import asyncio
import logging
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

from app.batch._common import asyncpg_dsn  # noqa: E402
from app.config import settings  # noqa: E402
from app.domain.geo import LatLonPoint, bearing_between, haversine_distance_km  # noqa: E402

logger = logging.getLogger("ridecompass.derive_topology")

COPY_CHUNK = 20_000


def split_segments(node_ids: list[int], split_at: set[int]) -> list[list[int]]:
    """道の参照ノード列を、交差点で切って区間へ分ける。

    両端は常に区間の端になる。中間のノードは、他の道も通っていれば切る。
    """
    segments: list[list[int]] = []
    current: list[int] = []
    for index, node_id in enumerate(node_ids):
        current.append(node_id)
        is_end = index == len(node_ids) - 1
        if (index > 0 and not is_end and node_id in split_at) or is_end:
            if len(current) >= 2:
                segments.append(current)
            current = [node_id]
    return segments


def _length_m(points: list[tuple[float, float]]) -> float:
    """折れ線の長さ（m）。`LatLonPoint`を使うのは、区間ぶんのループを回すため。"""
    total_km = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
        total_km += haversine_distance_km(LatLonPoint(lat1, lon1), LatLonPoint(lat2, lon2))
    return total_km * 1000


async def _load_ways(conn: asyncpg.Connection) -> tuple[dict[int, list[int]], dict[int, list[tuple[float, float]]]]:
    """`osm_way`の参照ノード列と形状を読む。"""
    node_ids: dict[int, list[int]] = {}
    shapes: dict[int, list[tuple[float, float]]] = {}
    rows = await conn.fetch(
        "SELECT natural_key, payload, ST_AsBinary(geom) AS wkb "
        "FROM source_features WHERE source = 'osm_way'")
    for row in rows:
        way_id = int(row["natural_key"])
        payload = row["payload"] or b""
        node_ids[way_id] = list(struct.unpack(f"<{len(payload) // 8}q", payload))
        line = shapely.from_wkb(bytes(row["wkb"]))
        shapes[way_id] = [(lat, lon) for lon, lat in line.coords]
    return node_ids, shapes


async def _load_node_positions(conn: asyncpg.Connection) -> dict[int, tuple[float, float]]:
    rows = await conn.fetch(
        "SELECT natural_key, ST_Y(geom) AS lat, ST_X(geom) AS lon "
        "FROM source_features WHERE source = 'osm_node'")
    return {int(r["natural_key"]): (r["lat"], r["lon"]) for r in rows}


async def _latest_run(conn: asyncpg.Connection, source: str) -> int:
    run_id = await conn.fetchval(
        "SELECT max(run_id) FROM source_runs WHERE source = $1 AND status = 'succeeded'", source)
    if run_id is None:
        raise RuntimeError(f"'{source}' の取込が成功していません")
    return run_id


async def derive(conn: asyncpg.Connection) -> tuple[int, int]:
    """`road_edges`・`edge_materials`の器・`node_materials`を作り直す。"""
    run_id = await _latest_run(conn, "osm_way")
    started = time.perf_counter()

    way_nodes, way_shapes = await _load_ways(conn)
    positions = await _load_node_positions(conn)
    logger.info("読み込み: way %d件 / node %d件", len(way_nodes), len(positions))

    # 2本以上の道が通るノードで切る。同じ道が同じノードを2度通る場合も分岐とみなす。
    passes = Counter()
    for ids in way_nodes.values():
        for node_id in ids:
            passes[node_id] += 1
    split_at = {node_id for node_id, count in passes.items() if count >= 2}

    # そこに集まる道の本数。両端は1本ぶん、中間の通過は2本ぶん（入って出る）に数える。
    branches: dict[int, int] = defaultdict(int)

    edges: list[tuple] = []
    for way_id, ids in way_nodes.items():
        shape = way_shapes.get(way_id)
        if shape is None:
            continue
        position_of = dict(zip(ids, shape)) if len(ids) == len(shape) else positions
        for segment_index, segment in enumerate(split_segments(ids, split_at)):
            points = [position_of[n] for n in segment if n in position_of]
            if len(points) < 2:
                continue
            start, end = points[0], points[-1]
            edges.append((
                way_id, segment_index, segment[0], segment[-1],
                shapely.to_wkb(LineString([(lon, lat) for lat, lon in points])),
                round(_length_m(points), 1),
                bearing_between(LatLonPoint(*start), LatLonPoint(*end)),
                # 逆向きの方位は+180°ではない。終点→始点で測り直す。
                bearing_between(LatLonPoint(*end), LatLonPoint(*start)),
                run_id,
            ))
            branches[segment[0]] += 1
            branches[segment[-1]] += 1

    async with conn.transaction():
        await conn.execute("TRUNCATE road_edges CASCADE")
        await conn.execute("TRUNCATE node_materials")
        stage = "_stage_edges"
        await conn.execute(
            f'CREATE TEMP TABLE "{stage}" (osm_way_id bigint, segment_index smallint, '
            "from_node_id bigint, to_node_id bigint, geom_wkb bytea, distance_m real, "
            "bearing_deg real, reverse_bearing_deg real, source_run_id bigint) "
            "ON COMMIT DROP")
        for start in range(0, len(edges), COPY_CHUNK):
            await conn.copy_records_to_table(
                stage, records=edges[start:start + COPY_CHUNK],
                columns=["osm_way_id", "segment_index", "from_node_id", "to_node_id",
                         "geom_wkb", "distance_m", "bearing_deg",
                         "reverse_bearing_deg", "source_run_id"])
        await conn.execute(
            "INSERT INTO road_edges (osm_way_id, segment_index, from_node_id, to_node_id, "
            "geom, distance_m, bearing_deg, reverse_bearing_deg, source_run_id) "
            "SELECT osm_way_id, segment_index, from_node_id, to_node_id, "
            "ST_SetSRID(ST_GeomFromWKB(geom_wkb), 4326), distance_m, bearing_deg, "
            "reverse_bearing_deg, source_run_id "
            f'FROM "{stage}"')
        # 値はこれから埋める。行だけ先に作り、未計算をNULLで表す。
        await conn.execute(
            "INSERT INTO edge_materials (osm_way_id, segment_index, source_run_id) "
            "SELECT osm_way_id, segment_index, source_run_id FROM road_edges")
        await conn.executemany(
            "INSERT INTO node_materials (osm_node_id, branch_count, source_run_id) "
            "VALUES ($1, $2, $3) ON CONFLICT (osm_node_id) DO UPDATE "
            "SET branch_count = EXCLUDED.branch_count",
            [(node_id, count, run_id) for node_id, count in branches.items()])

    elapsed = time.perf_counter() - started
    logger.info("導出完了: 区間 %d本 / ノード %d点 / %.1f秒", len(edges), len(branches), elapsed)
    return len(edges), len(branches)


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
    return asyncio.run(run(args.database_url or settings.database_url))


if __name__ == "__main__":
    raise SystemExit(main())
