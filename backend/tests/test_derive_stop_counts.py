"""停止要因と交差点の数（`batch/derive_counts.py`）が、経路の上でどう通っても1か所1回になること。

生データ（道・ノードのタグ）から派生の段を本物のまま通し、区間の値を経路に沿って足す。
"""

import json
import struct
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_counts, derive_node_materials, derive_topology
from app.batch._common import asyncpg_dsn
from app.batch.ingest import ensure_partition
from app.domain.tuning import TUNING_PARAMETERS_BY_ID
from tests.conftest import postgis_database_url

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

BASE_LON, BASE_LAT = 139.70, 35.68
SIGNAL = {"highway": "traffic_signals"}
LEVEL_CROSSING = {"railway": "level_crossing"}

#: ノード → (経度の差, 緯度の差, タグ)。0.0001度は約10m、同じ種別の点をまとめる距離の内側。
NODES: dict[int, tuple[float, float, dict[str, str]]] = {
    # 4本の道が集まる交差点。信号は交差点のノードではなく、3本の流入路の途中にある。
    100: (0.0, 0.0, {}),
    11: (-0.002, 0.0, {}), 12: (-0.0001, 0.0, SIGNAL),
    21: (0.002, 0.0, {}), 22: (0.0001, 0.0, SIGNAL),
    31: (0.0, 0.002, {}), 32: (0.0, 0.0001, SIGNAL),
    41: (0.0, -0.002, {}), 42: (0.0, -0.0001, {}),
    # 交差点から離れた、道の途中の信号（横断歩道の押しボタン信号など）。
    51: (0.01, 0.0, {}), 52: (0.0105, 0.0, SIGNAL), 53: (0.011, 0.0, {}),
    # 道の継ぎ目のノードに乗る信号。
    61: (0.0, 0.01, {}), 62: (0.0005, 0.01, SIGNAL), 63: (0.001, 0.01, {}),
    # 複線の踏切（線路1本ごとに1点）。
    81: (0.0, 0.02, {}), 82: (0.0005, 0.02, LEVEL_CROSSING),
    83: (0.00055, 0.02, LEVEL_CROSSING), 84: (0.001, 0.02, {}),
}

WAYS: dict[int, list[int]] = {
    1: [11, 12, 100], 2: [100, 22, 21], 3: [31, 32, 100], 4: [100, 42, 41],
    5: [51, 52, 53],
    6: [61, 62], 7: [62, 63],
    8: [81, 82, 83, 84],
}

#: 経路（通る道の並び）。どの道も区間1本になる（途中のノードはどれも2本以上の道が通らない）。
ROUTES: dict[str, tuple[int, ...]] = {
    "交差点を直進": (1, 2),
    "交差点を信号の無い流入路へ曲がる": (1, 4),
    "信号の無い流入路から直進": (4, 3),
    "道の途中の信号を通る": (5,),
    "継ぎ目の信号を通る": (6, 7),
    "複線の踏切を渡る": (8,),
}

TABLES = ("edge_materials", "way_materials", "road_edges", "node_materials",
          "source_features", "source_runs")


def _point(node_id: int) -> tuple[float, float]:
    dlon, dlat, _ = NODES[node_id]
    return (BASE_LON + dlon, BASE_LAT + dlat)


async def _insert_run(conn: asyncpg.Connection, source: str) -> int:
    return await conn.fetchval(
        "INSERT INTO source_runs (source, status, started_at, origin, profile, counts)"
        " VALUES ($1, 'succeeded', $2, $3, $3, $3) RETURNING run_id",
        source, datetime.now(UTC), json.dumps({}))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def stop_conn(road_graph_engine):
    """`road_graph_engine`に依存するのはスキーマを作らせるため（`test_derive_topology.py`と同じ）。"""
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        for source in ("osm_way", "osm_node"):
            await ensure_partition(conn, source)
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        way_run = await _insert_run(conn, "osm_way")
        for way_id, node_ids in WAYS.items():
            wkt = "LINESTRING(" + ", ".join(
                f"{lon} {lat}" for lon, lat in map(_point, node_ids)) + ")"
            await conn.execute(
                "INSERT INTO source_features (source, natural_key, run_id, geom, attrs, payload)"
                " VALUES ('osm_way', $1, $2, ST_GeomFromText($3, 4326), '{}'::jsonb, $4)",
                str(way_id), way_run, wkt, struct.pack(f"<{len(node_ids)}q", *node_ids))
        node_run = await _insert_run(conn, "osm_node")
        for node_id, (_, _, tags) in NODES.items():
            lon, lat = _point(node_id)
            await conn.execute(
                "INSERT INTO source_features (source, natural_key, run_id, geom, attrs)"
                " VALUES ('osm_node', $1, $2, ST_SetSRID(ST_MakePoint($3, $4), 4326), $5::jsonb)",
                str(node_id), node_run, lon, lat, json.dumps(tags))
        await derive_topology.derive(conn)
        await derive_node_materials.derive(conn, TUNING_PARAMETERS_BY_ID["signal.match_radius_m"].default)
        await derive_counts.derive(conn)
        yield conn
    finally:
        await conn.execute("TRUNCATE " + ", ".join(TABLES) + " CASCADE")
        await conn.close()


async def _along(conn: asyncpg.Connection, table: str, column: str) -> dict[str, float]:
    """経路ごとに、通る道の値を足す（どの道も区間1本なので、道の値と区間の値は同じ）。"""
    values = {r["osm_way_id"]: r["v"] for r in await conn.fetch(
        f"SELECT osm_way_id, sum({column}) AS v FROM {table} GROUP BY osm_way_id")}
    return {name: sum(values[w] for w in ways) for name, ways in ROUTES.items()}


@pytest.mark.parametrize("table", ["edge_materials", "way_materials"])
async def test_each_stop_place_counts_once_on_any_route_through_it(stop_conn, table):
    """まとまり1つ（信号交差点・道の途中の信号・複線の踏切）は、どの経路で通っても1回。

    区間の端に乗る点だけを数えると、流入路の途中にある信号・道の途中の信号・踏切が0回になる。
    端の0.5を整数へ丸めると、継ぎ目の信号が2回になる。
    """
    signals = await _along(stop_conn, table, "poi_signal")
    crossings = await _along(stop_conn, table, "poi_level_crossing")
    level_crossing_route = "複線の踏切を渡る"
    assert signals == {name: 0.0 if name == level_crossing_route else 1.0 for name in ROUTES}
    assert crossings == {name: 1.0 if name == level_crossing_route else 0.0 for name in ROUTES}


async def test_an_intersection_counts_once_on_a_route_through_it(stop_conn):
    """枝の多い交差点のノードは、入る区間と出る区間が0.5ずつ持ち、通れば1回になる。
    枝の少ないノード（道の継ぎ目・行き止まり）は交差点に数えない。"""
    through_intersection = {name for name, ways in ROUTES.items()
                            if any(100 in WAYS[w] for w in ways)}
    assert await _along(stop_conn, "edge_materials", "intersection_count") == {
        name: 1.0 if name in through_intersection else 0.0 for name in ROUTES}
