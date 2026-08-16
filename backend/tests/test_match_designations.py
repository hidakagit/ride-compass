"""match_designations.pyのDELETE/INSERT安全策(改善計画T73)の統合テスト。

ridecompass_test DB(conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ)への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import logging

import asyncpg
import pytest
import pytest_asyncio

from app.batch.match_designations import _write_matches
from app.domain.graph import WaySpec, build_road_graph
from tests.conftest import TEST_DATABASE_URL

NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)


def _asyncpg_dsn(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("+asyncpg", "").replace("?ssl=", "?sslmode=").replace("&ssl=", "&sslmode=")


@pytest_asyncio.fixture
async def designation_conn(road_graph_session):
    # road_graph_sessionはテーブル作成・後始末のためだけに依存する(接続不可時のskipも
    # このフィクスチャ経由で効く)。実際の読み書きはbatch側と同じasyncpg直結で行う。
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DATABASE_URL))
    try:
        yield conn
    finally:
        await conn.close()


async def _seed_designation_attribute(conn: asyncpg.Connection, edge_id: str, kind: str, ratio: float = 0.8) -> None:
    await conn.execute(
        "INSERT INTO designation_attributes (edge_id, kind, matched_ratio, data_version, calculated_at) "
        "VALUES ($1, $2, $3, 'seed', now())",
        edge_id, kind, ratio,
    )


class TestWriteMatches:
    async def test_skips_delete_when_candidates_are_empty(
        self, designation_conn, road_graph_repository, road_graph_session, caplog
    ):
        # 改善計画T73: route_designationsが空(import未実行・取込失敗後)等でcandidatesが
        # 0件のとき、従来はDELETEだけ実行され既存designation_attributesが静かに全消しされていた。
        way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
        graph = build_road_graph([way], {1: NODE1, 2: NODE2}, graph_version="v1")
        await road_graph_repository.save_graph(graph)
        await road_graph_session.commit()
        edge_id = next(iter(graph.edges))
        await _seed_designation_attribute(designation_conn, edge_id, "emergency_transport")

        with caplog.at_level(logging.WARNING, logger="app.batch.match_designations"):
            elapsed = await _write_matches(designation_conn, candidates=[], matched=[], data_version="test")

        assert elapsed == 0.0
        assert any("候補が0件" in r.message for r in caplog.records)
        remaining = await designation_conn.fetchval(
            "SELECT count(*) FROM designation_attributes WHERE edge_id = $1", edge_id
        )
        assert remaining == 1

    async def test_replaces_existing_rows_when_candidates_present(
        self, designation_conn, road_graph_repository, road_graph_session
    ):
        way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
        graph = build_road_graph([way], {1: NODE1, 2: NODE2}, graph_version="v1")
        await road_graph_repository.save_graph(graph)
        await road_graph_session.commit()
        edge_id = next(iter(graph.edges))
        await _seed_designation_attribute(designation_conn, edge_id, "emergency_transport", ratio=0.5)

        elapsed = await _write_matches(
            designation_conn,
            candidates=[(edge_id, "emergency_transport", 0.9)],
            matched=[(edge_id, "emergency_transport", 0.9)],
            data_version="buffer20m",
        )

        assert elapsed >= 0.0
        row = await designation_conn.fetchrow(
            "SELECT matched_ratio, data_version FROM designation_attributes WHERE edge_id = $1", edge_id
        )
        assert row["matched_ratio"] == pytest.approx(0.9)
        assert row["data_version"] == "buffer20m"

    async def test_rolls_back_delete_when_insert_fails_midway(
        self, designation_conn, road_graph_repository, road_graph_session, monkeypatch
    ):
        # T71と同じ観点: DELETE+executemanyの原子性が崩れていないことを確認する。
        way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
        graph = build_road_graph([way], {1: NODE1, 2: NODE2}, graph_version="v1")
        await road_graph_repository.save_graph(graph)
        await road_graph_session.commit()
        edge_id = next(iter(graph.edges))
        await _seed_designation_attribute(designation_conn, edge_id, "emergency_transport", ratio=0.5)

        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(asyncpg.Connection, "executemany", _boom)

        with pytest.raises(RuntimeError):
            await _write_matches(
                designation_conn,
                candidates=[(edge_id, "emergency_transport", 0.9)],
                matched=[(edge_id, "emergency_transport", 0.9)],
                data_version="buffer20m",
            )

        row = await designation_conn.fetchrow(
            "SELECT matched_ratio, data_version FROM designation_attributes WHERE edge_id = $1", edge_id
        )
        assert row["matched_ratio"] == pytest.approx(0.5)
        assert row["data_version"] == "seed"
