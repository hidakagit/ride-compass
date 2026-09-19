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
from tests.conftest import postgis_database_url
from tests.road_graph_scaffolds import three_way_junction_spec, three_way_junction_graph

# road_graph_session/road_graph_repository（conftest.py）はDB接続確立コスト削減のため
# ファイル単位で1本のエンジン・イベントループを使い回す設計。ファイル内の全テストの
# イベントループスコープをそれに合わせる必要がある（docs/testing.mdパターン2）。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

# 端点3つは近接させる（このバッチの検証対象は次数の集計で、距離は関係しない）。
NODE3 = (35.702, 139.700)
NODE4 = (35.700, 139.702)


async def _seed_y_junction(road_graph_repository, road_graph_session) -> None:
    """NODE2へ3本のWayが集まるY字（NODE2の次数3、端点3つは次数1）。"""
    # 区間はwayの派生行（`road_edges.osm_way_id`がFK）のため、本番と同じく先にwayを入れる。
    await road_graph_repository.save_raw_ways(*three_way_junction_spec(NODE3, NODE4))
    await road_graph_repository.save_graph(three_way_junction_graph(NODE3, NODE4))
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

    assert await run(postgis_database_url(), dry_run=False) == 0

    await road_graph_session.rollback()  # バッチ側の別エンジンによる更新を読み直す
    assert await _degrees_by_osm_node_id(road_graph_session) == {1: 1, 2: 3, 3: 1, 4: 1}


async def test_run_dry_run_leaves_degrees_untouched(road_graph_repository, road_graph_session):
    await _seed_y_junction(road_graph_repository, road_graph_session)

    assert await run(postgis_database_url(), dry_run=True) == 0

    await road_graph_session.rollback()
    # 未計算の初期値（road_nodes.degreeのDEFAULT 0）のまま。
    assert set((await _degrees_by_osm_node_id(road_graph_session)).values()) == {0}


async def test_run_warns_and_skips_when_no_edges(road_graph_session, caplog):
    with caplog.at_level(logging.WARNING, logger="ridecompass.precompute_road_node_degrees"):
        assert await run(postgis_database_url(), dry_run=False) == 0

    assert any("road_edgesが0件" in r.getMessage() for r in caplog.records)
