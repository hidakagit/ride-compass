"""停止要因と交差点の数（`batch/derive_counts.py`）が、経路の上でどう通っても1か所1回になること。

生データ（道・ノードのタグ）から派生の段を本物のまま通し、区間の値を経路に沿って足す。
見ないもの: 道の値が区間の和であること → `test_derive_counts.py`の流し直しのテスト。道に属さないノードの
種別と行 → `test_derive_nodes.py`。
"""

import asyncpg
import pytest
import pytest_asyncio

from app.batch import derive_counts, derive_nodes, derive_topology
from app.domain.tuning import TUNING_PARAMETERS_BY_ID
from tests.source_ingest import ingest_records, point_record, way_record

# road_graph_session（conftest.py）と同じDBを使うため、.claude/rules/testing.mdのパターン2どおり
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


def _point(node_id: int) -> tuple[float, float]:
    dlon, dlat, _ = NODES[node_id]
    return (BASE_LON + dlon, BASE_LAT + dlat)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def stop_conn(derive_conn):
    """道とノードを取り込み、区間・ノードの材料・数え上げまで作った状態。"""
    conn = derive_conn
    await ingest_records("osm_way", [
        way_record(way_id, [_point(n) for n in node_ids], node_ids)
        for way_id, node_ids in WAYS.items()], conn=conn)
    await ingest_records("osm_node", [
        point_record(node_id, *_point(node_id), tags)
        for node_id, (_, _, tags) in NODES.items()], conn=conn)
    await derive_topology.derive(conn)
    await derive_nodes.derive(conn, TUNING_PARAMETERS_BY_ID["signal.match_radius_m"].default)
    await derive_counts.derive(conn)
    return conn


async def _along(conn: asyncpg.Connection, column: str) -> dict[str, float]:
    """経路ごとに、通る区間の値を足す（どの道も区間1本）。"""
    values = {r["osm_way_id"]: r["v"] for r in await conn.fetch(
        f"SELECT osm_way_id, {column} AS v FROM edge_counts")}
    return {name: sum(values[w] for w in ways) for name, ways in ROUTES.items()}


async def test_each_stop_place_counts_once_on_any_route_through_it(stop_conn):
    """まとまり1つ（信号交差点・道の途中の信号・複線の踏切）は、どの経路で通っても1回。

    区間の端に乗る点だけを数えると、流入路の途中にある信号・道の途中の信号・踏切が0回になる。
    端の0.5を整数へ丸めると、継ぎ目の信号が2回になる。
    """
    signals = await _along(stop_conn, "poi_signal")
    crossings = await _along(stop_conn, "poi_level_crossing")
    level_crossing_route = "複線の踏切を渡る"
    assert signals == {name: 0.0 if name == level_crossing_route else 1.0 for name in ROUTES}
    assert crossings == {name: 1.0 if name == level_crossing_route else 0.0 for name in ROUTES}


async def test_an_intersection_counts_once_on_a_route_through_it(stop_conn):
    """枝の多い交差点のノードは、入る区間と出る区間が0.5ずつ持ち、通れば1回になる。
    枝の少ないノード（道の継ぎ目・行き止まり）は交差点に数えない。"""
    through_intersection = {name for name, ways in ROUTES.items()
                            if any(100 in WAYS[w] for w in ways)}
    assert await _along(stop_conn, "intersection_count") == {
        name: 1.0 if name in through_intersection else 0.0 for name in ROUTES}

