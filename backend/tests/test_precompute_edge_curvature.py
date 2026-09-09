"""app/batch/precompute_edge_curvature.pyのrun()結合検証。

要点は**SQL側の計算がdomain/geo.py: curvature_deg_per_kmと一致すること**。同じ列を
2通り（split時のPython・バッチのSQL）で埋めるため、定義がずれると同じEdgeに2つの値が
生まれる。実際にST_Azimuthをgeometryのまま呼んで平面計算になり、緯度による経度の縮みを
無視して15%ずれた（docs/tasks/T691.md）。

ridecompass_test DB（conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ）への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import logging

import pytest
from sqlalchemy import text

from app.batch.precompute_edge_curvature import run
from app.domain.graph import WaySpec, build_road_graph
from tests.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

# 直線（方位変化なし）とジグザグ（頂点ごとに折り返す）を並べる。
STRAIGHT_NODES = {1: (35.700, 139.700), 2: (35.710, 139.700), 3: (35.720, 139.700)}
ZIGZAG_NODES = {
    11: (35.700, 139.800),
    12: (35.701, 139.801),
    13: (35.702, 139.800),
    14: (35.703, 139.801),
    15: (35.704, 139.800),
}

# 球（domain/geo.py）と回転楕円体（PostGISのgeography）の違いぶんの許容差。
TOLERANCE_RATIO = 0.01


async def _seed(road_graph_repository, road_graph_session) -> None:
    ways = [
        WaySpec(osm_way_id=200, node_ids=[1, 2, 3], highway="residential"),
        WaySpec(osm_way_id=201, node_ids=[11, 12, 13, 14, 15], highway="residential"),
    ]
    graph = build_road_graph(ways, {**STRAIGHT_NODES, **ZIGZAG_NODES}, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await road_graph_session.commit()


async def _curvature_by_edge_id(road_graph_session) -> dict[str, float | None]:
    rows = (
        await road_graph_session.execute(text("SELECT edge_id, curvature_deg_per_km FROM road_edges"))
    ).all()
    return {r.edge_id: r.curvature_deg_per_km for r in rows}


async def test_run_matches_the_python_definition(road_graph_repository, road_graph_session):
    await _seed(road_graph_repository, road_graph_session)
    # split時にPythonが入れた値を消し、バッチのSQLだけで埋め直させる（本番の既存行と同じ状態）。
    before = await _curvature_by_edge_id(road_graph_session)
    await road_graph_session.execute(text("UPDATE road_edges SET curvature_deg_per_km = NULL"))
    await road_graph_session.commit()

    assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    await road_graph_session.rollback()  # バッチ側の別エンジンによる更新を読み直す
    after = await _curvature_by_edge_id(road_graph_session)

    assert set(after) == set(before)
    for edge_id, sql_value in after.items():
        python_value = before[edge_id]
        assert python_value is not None, f"split時に値が入っていない: {edge_id}"
        assert sql_value is not None, f"バッチが値を入れていない: {edge_id}"
        allowed = max(TOLERANCE_RATIO * python_value, 0.5)
        assert abs(sql_value - python_value) <= allowed, (
            f"{edge_id}: SQL={sql_value} とPython={python_value} が食い違う"
        )


async def test_straight_way_is_zero_and_zigzag_is_large(road_graph_repository, road_graph_session):
    """「まっすぐ＝0」「折り返す＝大きい」という向きが逆でないことを固定する。"""
    await _seed(road_graph_repository, road_graph_session)
    await road_graph_session.execute(text("UPDATE road_edges SET curvature_deg_per_km = NULL"))
    await road_graph_session.commit()

    assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    await road_graph_session.rollback()
    values = await _curvature_by_edge_id(road_graph_session)
    straight = [v for edge_id, v in values.items() if edge_id.startswith("way-200")]
    zigzag = [v for edge_id, v in values.items() if edge_id.startswith("way-201")]
    assert straight and zigzag
    assert all(v == pytest.approx(0.0, abs=1.0) for v in straight)
    assert all(v > 100 for v in zigzag)


async def test_run_dry_run_leaves_curvature_untouched(road_graph_repository, road_graph_session):
    await _seed(road_graph_repository, road_graph_session)
    await road_graph_session.execute(text("UPDATE road_edges SET curvature_deg_per_km = NULL"))
    await road_graph_session.commit()

    assert await run(TEST_DATABASE_URL, dry_run=True) == 0

    await road_graph_session.rollback()
    # NULLは「未計算」であって0（まっすぐ）ではない——dry-runがこれを埋めてはいけない。
    assert set((await _curvature_by_edge_id(road_graph_session)).values()) == {None}


async def test_run_warns_and_skips_when_no_edges(road_graph_session, caplog):
    with caplog.at_level(logging.WARNING, logger="ridecompass.precompute_edge_curvature"):
        assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    assert any("road_edgesが0件" in r.getMessage() for r in caplog.records)
