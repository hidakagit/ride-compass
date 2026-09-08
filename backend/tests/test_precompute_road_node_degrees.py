"""app/batch/precompute_road_node_degrees.pyのrun()結合検証。

集計SQL自体（`recompute_node_degrees`）の検証はtests/test_road_graph_repository.py側。
ここではバッチのオーケストレーション（対象件数の判定・dry-runの非書き込み・
road_edgesが空のときのスキップ・実行後にdegreeが入ること）を確認する。

ridecompass_test DB（conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ）への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import logging

import pytest
from sqlalchemy import text

from app.batch.precompute_road_node_degrees import run
from app.domain.graph import WaySpec, build_road_graph
from tests.conftest import TEST_DATABASE_URL

# road_graph_session/road_graph_repository（conftest.py）はDB接続確立コスト削減のため
# ファイル単位で1本のエンジン・イベントループを使い回す設計。ファイル内の全テストの
# イベントループスコープをそれに合わせる必要がある（docs/testing.mdパターン2）。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)
NODE3 = (35.702, 139.700)
NODE4 = (35.700, 139.702)


async def _seed_y_junction(road_graph_repository, road_graph_session) -> None:
    """NODE2へ3本のWayが集まるY字（NODE2の次数3、端点3つは次数1）。"""
    ways = [
        WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential"),
        WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential"),
        WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential"),
    ]
    graph = build_road_graph(ways, {1: NODE1, 2: NODE2, 3: NODE3, 4: NODE4}, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await road_graph_session.commit()


async def _degrees_by_osm_node_id(road_graph_session) -> dict[int, int]:
    rows = (
        await road_graph_session.execute(
            text("SELECT osm_node_id, degree FROM road_nodes WHERE osm_node_id IS NOT NULL")
        )
    ).all()
    return {r.osm_node_id: r.degree for r in rows}


async def test_run_writes_global_degrees(road_graph_repository, road_graph_session):
    await _seed_y_junction(road_graph_repository, road_graph_session)

    assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    await road_graph_session.rollback()  # バッチ側の別エンジンによる更新を読み直す
    assert await _degrees_by_osm_node_id(road_graph_session) == {1: 1, 2: 3, 3: 1, 4: 1}


async def test_run_dry_run_leaves_degrees_untouched(road_graph_repository, road_graph_session):
    await _seed_y_junction(road_graph_repository, road_graph_session)

    assert await run(TEST_DATABASE_URL, dry_run=True) == 0

    await road_graph_session.rollback()
    # 未計算の初期値（road_nodes.degreeのDEFAULT 0）のまま。
    assert set((await _degrees_by_osm_node_id(road_graph_session)).values()) == {0}


async def test_run_warns_and_skips_when_no_edges(road_graph_session, caplog):
    with caplog.at_level(logging.WARNING, logger="ridecompass.precompute_road_node_degrees"):
        assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    assert any("road_edgesが0件" in r.getMessage() for r in caplog.records)
