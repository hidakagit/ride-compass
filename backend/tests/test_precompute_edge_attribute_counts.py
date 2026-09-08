"""app/batch/precompute_edge_attribute_counts.pyのrun()結合検証（改善計画T144）。
チャンク分割自体の純粋ロジック検証はtests/test_batch_common.py（改善計画T467、
_chunked実装統合に伴いテストも集約）。

TestRunOrchestration（改善計画T331残り5項目）はrun()本体・UPSERTの結合検証で、
ridecompass_test DB（conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ）への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from app.batch.precompute_edge_attribute_counts import ALGORITHM_VERSION, CHUNK_SIZE, run
from app.domain.graph import WaySpec, build_road_graph
from app.infrastructure import accident_models  # noqa: F401  road_graph_sessionの後始末対象へaccident_*テーブルを登録するためのimport
from app.infrastructure.road_graph_models import EdgeAttributeCountsRow
from app.infrastructure.road_graph_repository import MAX_BIND_PARAMS_PER_STATEMENT, RoadGraphRepository
from tests.conftest import TEST_DATABASE_URL

NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)


async def _seed_one_way(road_graph_repository, road_graph_session) -> None:
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    graph = build_road_graph([way], {1: NODE1, 2: NODE2}, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await road_graph_session.commit()


class TestRunOrchestration:
    """run()本体（edge一覧取得→3種のcount取得→UPSERT）の結合検証（改善計画T331残り5項目）。

    以前は_chunkedの純粋ロジックのみがテストされ、run()のオーケストレーション本体自体は
    CI未検証だった（手動E2Eスクリプトのみ、precompute_way_attribute_counts.pyと同型の
    カバレッジ欠落）。road_edgesを1way分だけ実DBへ用意し、run()を通しでUPSERT結果を確認する。

    road_graph_session/road_graph_repository（conftest.py）はDB接続確立コスト削減のため
    ファイル単位で1本のエンジン・イベントループを使い回す設計。run()自体は別のエンジンで
    動くが（settings.database_url/引数のdatabase_urlから毎回新規作成）、テスト側の書き込みを
    run()から見えるようにするためroad_graph_session.commit()で明示的にコミットする
    （test_match_designations.pyと同じ手法）。
    """

    pytestmark = [
        pytest.mark.asyncio(loop_scope="module"),
        pytest.mark.xdist_group(name="postgis"),
        pytest.mark.postgis,
    ]

    async def test_writes_zero_counts_when_no_related_data_seeded(self, road_graph_repository, road_graph_session):
        await _seed_one_way(road_graph_repository, road_graph_session)

        result = await run(TEST_DATABASE_URL, dry_run=False)

        assert result == 0
        rows = (await road_graph_session.execute(select(EdgeAttributeCountsRow))).scalars().all()
        assert len(rows) == 2  # 双方向2edge
        assert {r.accident_count for r in rows} == {0.0}
        assert {r.stop_count for r in rows} == {0}
        assert {r.intersection_count for r in rows} == {0}
        assert all(r.computed_at is not None for r in rows)
        # 派生データの系譜追跡（改善計画T351）: import_runsが1件も無い環境ではsource_*が
        # NULLのまま書き込まれる（呼び出し元は無条件にNoneを渡すため例外にはならない）。
        # algorithm_versionは常に埋まる。
        assert all(r.algorithm_version == ALGORITHM_VERSION for r in rows)
        assert {r.source_accident_import_run_id for r in rows} == {None}
        assert {r.source_osm_import_run_id for r in rows} == {None}

    async def test_rerun_upserts_without_duplicating(self, road_graph_repository, road_graph_session):
        await _seed_one_way(road_graph_repository, road_graph_session)

        assert await run(TEST_DATABASE_URL, dry_run=False) == 0
        assert await run(TEST_DATABASE_URL, dry_run=False) == 0  # 再実行

        rows = (await road_graph_session.execute(select(EdgeAttributeCountsRow))).scalars().all()
        assert len(rows) == 2  # 重複INSERTされない（ON CONFLICT DO UPDATE）

    async def test_dry_run_does_not_write(self, road_graph_repository, road_graph_session):
        await _seed_one_way(road_graph_repository, road_graph_session)

        result = await run(TEST_DATABASE_URL, dry_run=True)

        assert result == 0
        rows = (await road_graph_session.execute(select(EdgeAttributeCountsRow))).scalars().all()
        assert rows == []

    async def test_source_run_ids_reflect_latest_succeeded_runs(self, road_graph_repository, road_graph_session):
        """派生データの系譜追跡（改善計画T351）: accident_import_runs/osm_import_runsの
        最新成功run idがsource_*_import_run_idへ書き込まれることを確認する（高水位マーク、
        migration 0024のコメント参照）。"""
        await _seed_one_way(road_graph_repository, road_graph_session)
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

        rows = (await road_graph_session.execute(select(EdgeAttributeCountsRow))).scalars().all()
        assert {r.source_accident_import_run_id for r in rows} == {accident_run_id}
        assert {r.source_osm_import_run_id for r in rows} == {osm_run_id}


async def test_upsert_is_delegated_to_the_repository_without_batch_local_sql():
    """UPSERTはリポジトリの`save_edge_attribute_counts`（`_bulk_upsert`）へ委譲する。

    このバッチのdocstringは「新しいSQLは書かない」と宣言している。自前のINSERT文を
    持つと、パラメータ上限に応じた再分割（`road_graph_repository._bulk_chunk_rows`）の
    ような共通の保護が片方だけ効かなくなる。1文あたりのバインドパラメータ上限を守る
    こと自体の検証はtests/test_road_graph_repository.py側。
    """
    from app.batch import precompute_edge_attribute_counts as batch

    assert not hasattr(batch, "_upsert_chunk")
    assert not hasattr(batch, "_execute_upsert")
    assert "pg_insert" not in batch.__dict__
    assert hasattr(RoadGraphRepository, "save_edge_attribute_counts")


async def test_upsert_splits_statements_so_bind_parameters_stay_under_the_limit():
    """このバッチが組み立てる行をUPSERTしても、1文のバインドパラメータが
    PostgreSQLの上限（32,767個）を超えない。

    列を1つ足すと1文へ載せられる行数が減る。行数を固定にしていたため、実際に
    `poi_counts`を足したときに上限を超え、本番のバッチが最初のチャンクで落ちた。
    """
    executed: list[int] = []

    class _Session:
        async def execute(self, stmt):
            executed.append(len(stmt.compile().params))

    columns = {
        "edge_id": "e", "accident_count": 0.0, "stop_count": 0, "intersection_count": 0,
        "poi_counts": {}, "computed_at": datetime.now(timezone.utc),
        "source_accident_import_run_id": None, "source_osm_import_run_id": None,
        "algorithm_version": "v1",
    }
    rows = [dict(columns, edge_id=f"e{i}") for i in range(CHUNK_SIZE)]

    await RoadGraphRepository(_Session()).save_edge_attribute_counts(rows)

    assert executed, "1文も発行されていない"
    assert max(executed) <= MAX_BIND_PARAMS_PER_STATEMENT
    # 全行が漏れなく載っている（分割で落ちていない）。
    assert sum(n // len(columns) for n in executed) == len(rows)
