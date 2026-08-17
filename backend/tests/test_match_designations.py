"""match_designations.pyのDELETE/INSERT安全策(改善計画T73)の統合テスト。

ridecompass_test DB(conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ)への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import logging

import asyncpg
import pytest
import pytest_asyncio

from app.batch._common import asyncpg_dsn
from app.batch.match_designations import _write_matches
from app.domain.graph import WaySpec
from tests.conftest import TEST_DATABASE_URL

# road_graph_session/road_graph_repository（conftest.py）はDB接続確立コスト削減のため
# ファイル単位で1本のエンジン・イベントループを使い回す設計。ファイル内の全テストの
# イベントループスコープをそれに合わせる必要がある。
pytestmark = pytest.mark.asyncio(loop_scope="module")

NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)
OSM_WAY_ID = 100


@pytest_asyncio.fixture(loop_scope="module")
async def designation_conn(road_graph_session):
    # road_graph_sessionはテーブル作成・後始末のためだけに依存する(接続不可時のskipも
    # このフィクスチャ経由で効く)。実際の読み書きはbatch側と同じasyncpg直結で行う。
    conn = await asyncpg.connect(asyncpg_dsn(TEST_DATABASE_URL))
    try:
        yield conn
    finally:
        await conn.close()


async def _seed_designation_attribute(
    conn: asyncpg.Connection, osm_way_id: int, kind: str, ratio: float = 0.8
) -> None:
    await conn.execute(
        "INSERT INTO designation_attributes (osm_way_id, kind, matched_ratio, data_version, calculated_at) "
        "VALUES ($1, $2, $3, 'seed', now())",
        osm_way_id, kind, ratio,
    )


class TestWriteMatches:
    async def test_skips_delete_when_candidates_are_empty(
        self, designation_conn, road_graph_repository, road_graph_session, caplog
    ):
        # 改善計画T73: route_designationsが空(import未実行・取込失敗後)等でcandidatesが
        # 0件のとき、従来はDELETEだけ実行され既存designation_attributesが静かに全消しされていた。
        # 改善計画T74: designation_attributesはosm_raw_ways基準のため、FK制約を満たすため
        # save_raw_waysでosm_raw_ways行を用意する(road_edgesは不要)。
        way = WaySpec(osm_way_id=OSM_WAY_ID, node_ids=[1, 2], highway="residential")
        await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
        await road_graph_session.commit()
        await _seed_designation_attribute(designation_conn, OSM_WAY_ID, "emergency_transport")

        with caplog.at_level(logging.WARNING, logger="app.batch.match_designations"):
            elapsed = await _write_matches(designation_conn, candidates=[], matched=[], data_version="test")

        assert elapsed == 0.0
        assert any("候補が0件" in r.message for r in caplog.records)
        remaining = await designation_conn.fetchval(
            "SELECT count(*) FROM designation_attributes WHERE osm_way_id = $1", OSM_WAY_ID
        )
        assert remaining == 1

    async def test_replaces_existing_rows_when_candidates_present(
        self, designation_conn, road_graph_repository, road_graph_session
    ):
        way = WaySpec(osm_way_id=OSM_WAY_ID, node_ids=[1, 2], highway="residential")
        await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
        await road_graph_session.commit()
        await _seed_designation_attribute(designation_conn, OSM_WAY_ID, "emergency_transport", ratio=0.5)

        elapsed = await _write_matches(
            designation_conn,
            candidates=[(OSM_WAY_ID, "emergency_transport", 0.9)],
            matched=[(OSM_WAY_ID, "emergency_transport", 0.9)],
            data_version="buffer20m",
        )

        assert elapsed >= 0.0
        row = await designation_conn.fetchrow(
            "SELECT matched_ratio, data_version FROM designation_attributes WHERE osm_way_id = $1", OSM_WAY_ID
        )
        assert row["matched_ratio"] == pytest.approx(0.9)
        assert row["data_version"] == "buffer20m"

    async def test_rolls_back_delete_when_insert_fails_midway(
        self, designation_conn, road_graph_repository, road_graph_session, monkeypatch
    ):
        # T71と同じ観点: DELETE+executemanyの原子性が崩れていないことを確認する。
        way = WaySpec(osm_way_id=OSM_WAY_ID, node_ids=[1, 2], highway="residential")
        await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
        await road_graph_session.commit()
        await _seed_designation_attribute(designation_conn, OSM_WAY_ID, "emergency_transport", ratio=0.5)

        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(asyncpg.Connection, "executemany", _boom)

        with pytest.raises(RuntimeError):
            await _write_matches(
                designation_conn,
                candidates=[(OSM_WAY_ID, "emergency_transport", 0.9)],
                matched=[(OSM_WAY_ID, "emergency_transport", 0.9)],
                data_version="buffer20m",
            )

        row = await designation_conn.fetchrow(
            "SELECT matched_ratio, data_version FROM designation_attributes WHERE osm_way_id = $1", OSM_WAY_ID
        )
        assert row["matched_ratio"] == pytest.approx(0.5)
        assert row["data_version"] == "seed"
