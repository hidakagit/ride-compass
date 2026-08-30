"""app/batch/precompute_way_attribute_counts.pyの純粋ロジック（チャンク分割）の検証
（改善計画T331、兄弟モジュールprecompute_edge_attribute_counts.pyのtest_chunked相当）。
DB接続自体は実DBが要るため対象外（他のbatchスクリプトのテストと同じ切り分け方針）。

TestSourceTracking（改善計画T351）は派生データの系譜追跡カラムの書き込みを検証する
結合テストで、ridecompass_test DB（conftest.pyのroad_graph_session/road_graph_repository
フィクスチャ）への実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import pytest
from sqlalchemy import select, text

from app.batch.precompute_way_attribute_counts import ALGORITHM_VERSION, _chunked, run
from app.domain.graph import WaySpec
from app.infrastructure.road_graph_models import WayAttributeCountsRow
from tests.conftest import TEST_DATABASE_URL


def test_chunked_splits_into_fixed_size_groups():
    assert _chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunked_single_chunk_when_smaller_than_size():
    assert _chunked([1, 2], 10) == [[1, 2]]


def test_chunked_empty_list_returns_empty():
    assert _chunked([], 5) == []


NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)
OSM_WAY_ID = 100


class TestSourceTracking:
    """派生データの系譜追跡（改善計画T351）: recompute_way_attribute_countsが書き込む
    source_*_import_run_id/algorithm_versionの検証。edge単位版
    （test_precompute_edge_attribute_counts.py: test_source_run_ids_reflect_latest_succeeded_runs）
    と同じ観点。"""

    pytestmark = [
        pytest.mark.asyncio(loop_scope="module"),
        pytest.mark.xdist_group(name="postgis"),
        pytest.mark.postgis,
    ]

    async def test_source_run_ids_and_algorithm_version_are_written(
        self, road_graph_repository, road_graph_session
    ):
        way = WaySpec(osm_way_id=OSM_WAY_ID, node_ids=[1, 2], highway="residential")
        await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
        accident_run_id = (
            await road_graph_session.execute(
                text(
                    "INSERT INTO accident_import_runs (occurred_year, file_name, status, started_at, finished_at) "
                    "VALUES (2025, 'test.csv', 'succeeded', now(), now()) RETURNING id"
                )
            )
        ).scalar_one()
        osm_run_id = (
            await road_graph_session.execute(
                text(
                    "INSERT INTO osm_import_runs (pbf_name, profile_hash, status, started_at, finished_at) "
                    "VALUES ('test.pbf', 'hash', 'succeeded', now(), now()) RETURNING id"
                )
            )
        ).scalar_one()
        await road_graph_session.commit()

        assert await run(TEST_DATABASE_URL, dry_run=False) == 0

        row = (
            await road_graph_session.execute(
                select(WayAttributeCountsRow).where(WayAttributeCountsRow.osm_way_id == OSM_WAY_ID)
            )
        ).scalar_one()
        assert row.source_accident_import_run_id == accident_run_id
        assert row.source_osm_import_run_id == osm_run_id
        assert row.algorithm_version == ALGORITHM_VERSION
