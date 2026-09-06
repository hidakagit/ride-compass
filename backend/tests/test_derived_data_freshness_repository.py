"""DerivedDataFreshnessQuery（infrastructure/derived_data_freshness.py）のPostGIS統合テスト。

ridecompass_test DB（conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ）への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.domain.attributes import ElevationAttribute
from app.domain.graph import WaySpec, build_road_graph
from app.infrastructure import accident_models  # noqa: F401  Base.metadataへaccident_*テーブルを登録するためのimport
from app.infrastructure import designation_models  # noqa: F401  Base.metadataへdesignation_*テーブルを登録するためのimport
from app.infrastructure.derived_data_freshness import DerivedDataFreshnessQuery

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)


async def _insert_import_run(session, table: str, columns_sql: str, values_sql: str) -> int:
    return (
        await session.execute(text(f"INSERT INTO {table} ({columns_sql}) VALUES ({values_sql}) RETURNING id"))
    ).scalar_one()


async def _seed_one_way_and_edges(road_graph_repository, road_graph_session) -> list[str]:
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    await road_graph_session.commit()
    return sorted(graph.edges.keys())


async def test_empty_database_yields_no_stale_generations(road_graph_session):
    counts = await DerivedDataFreshnessQuery(road_graph_session).get_freshness_counts()

    assert counts.road_edges_total == 0
    assert counts.elevation_uncalculated_count == 0
    assert len(counts.generations) == 4
    for generation in counts.generations:
        assert generation.row_count == 0
    assert counts.latest_succeeded_run_id == {"accident_import_runs": None, "osm_import_runs": None}


async def test_edge_attribute_counts_reflects_fresh_generation_when_run_ids_match_latest(
    road_graph_repository, road_graph_session,
):
    edge_ids = await _seed_one_way_and_edges(road_graph_repository, road_graph_session)
    accident_run_id = await _insert_import_run(
        road_graph_session, "accident_import_runs",
        "occurred_year, file_name, status, started_at, finished_at",
        "2025, 'test.csv', 'succeeded', now(), now()",
    )
    osm_run_id = await _insert_import_run(
        road_graph_session, "osm_import_runs",
        "pbf_name, profile_hash, status, started_at, finished_at",
        "'test.pbf', 'hash', 'succeeded', now(), now()",
    )
    for edge_id in edge_ids:
        await road_graph_session.execute(
            text(
                "INSERT INTO edge_attribute_counts (edge_id, accident_count, stop_count, intersection_count, "
                "computed_at, source_accident_import_run_id, source_osm_import_run_id, algorithm_version) "
                "VALUES (:edge_id, 0, 0, 0, now(), :accident_run_id, :osm_run_id, 'v1')"
            ),
            {"edge_id": edge_id, "accident_run_id": accident_run_id, "osm_run_id": osm_run_id},
        )
    await road_graph_session.commit()

    counts = await DerivedDataFreshnessQuery(road_graph_session).get_freshness_counts()
    edge_counts = next(g for g in counts.generations if g.table_name == "edge_attribute_counts")

    assert edge_counts.row_count == 2
    assert edge_counts.source_min["source_accident_import_run_id"] == accident_run_id
    assert edge_counts.source_min["source_osm_import_run_id"] == osm_run_id
    assert edge_counts.algorithm_version_min == "v1"
    assert counts.latest_succeeded_run_id["osm_import_runs"] == osm_run_id


async def test_edge_attribute_counts_reflects_stale_generation_when_newer_osm_run_exists(
    road_graph_repository, road_graph_session,
):
    edge_ids = await _seed_one_way_and_edges(road_graph_repository, road_graph_session)
    old_osm_run_id = await _insert_import_run(
        road_graph_session, "osm_import_runs",
        "pbf_name, profile_hash, status, started_at, finished_at",
        "'old.pbf', 'hash1', 'succeeded', now(), now()",
    )
    for edge_id in edge_ids:
        await road_graph_session.execute(
            text(
                "INSERT INTO edge_attribute_counts (edge_id, accident_count, stop_count, intersection_count, "
                "computed_at, source_osm_import_run_id, algorithm_version) "
                "VALUES (:edge_id, 0, 0, 0, now(), :osm_run_id, 'v1')"
            ),
            {"edge_id": edge_id, "osm_run_id": old_osm_run_id},
        )
    await road_graph_session.commit()
    # edge_attribute_counts書き込み後に、より新しいOSM取込が成功した状態を再現する。
    new_osm_run_id = await _insert_import_run(
        road_graph_session, "osm_import_runs",
        "pbf_name, profile_hash, status, started_at, finished_at",
        "'new.pbf', 'hash2', 'succeeded', now(), now()",
    )
    await road_graph_session.commit()

    counts = await DerivedDataFreshnessQuery(road_graph_session).get_freshness_counts()
    edge_counts = next(g for g in counts.generations if g.table_name == "edge_attribute_counts")

    assert edge_counts.source_min["source_osm_import_run_id"] == old_osm_run_id
    assert counts.latest_succeeded_run_id["osm_import_runs"] == new_osm_run_id
    assert new_osm_run_id > old_osm_run_id


async def test_way_attribute_counts_null_source_run_id_is_counted(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=200, node_ids=[1, 2], highway="residential")
    await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
    await road_graph_session.commit()
    await road_graph_session.execute(
        text(
            "INSERT INTO way_attribute_counts (osm_way_id, length_m, accident_count, stop_count, "
            "intersection_count, computed_at) VALUES (200, 500.0, 0, 0, 0, now())"
        )
    )
    await road_graph_session.commit()

    counts = await DerivedDataFreshnessQuery(road_graph_session).get_freshness_counts()
    way_counts = next(g for g in counts.generations if g.table_name == "way_attribute_counts")

    assert way_counts.row_count == 1
    assert way_counts.source_min["source_osm_import_run_id"] is None
    assert way_counts.source_null_count["source_osm_import_run_id"] == 1
    assert way_counts.algorithm_version_min is None
    assert way_counts.algorithm_version_null_count == 1


async def test_designation_attributes_has_no_algorithm_version_column(road_graph_repository, road_graph_session):
    way = WaySpec(osm_way_id=300, node_ids=[1, 2], highway="residential")
    await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
    await road_graph_session.commit()
    await road_graph_session.execute(
        text(
            "INSERT INTO designation_attributes (osm_way_id, kind, matched_ratio, data_version, calculated_at) "
            "VALUES (300, 'emergency_transport', 0.9, 'v1', now())"
        )
    )
    await road_graph_session.commit()

    counts = await DerivedDataFreshnessQuery(road_graph_session).get_freshness_counts()
    designation_counts = next(g for g in counts.generations if g.table_name == "designation_attributes")

    assert designation_counts.row_count == 1
    assert designation_counts.algorithm_version_min is None
    assert designation_counts.algorithm_version_null_count == 0  # spec対象外のため常に0


async def test_elevation_completeness_counts_edges_without_a_row(road_graph_repository, road_graph_session):
    edge_ids = await _seed_one_way_and_edges(road_graph_repository, road_graph_session)
    await road_graph_repository.save_elevation_attributes(
        [
            ElevationAttribute(
                edge_id=edge_ids[0], average_grade=1.5, data_source="gsi",
                calculated_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            ),
        ]
    )
    await road_graph_session.commit()

    counts = await DerivedDataFreshnessQuery(road_graph_session).get_freshness_counts()

    assert counts.road_edges_total == 2
    assert counts.elevation_uncalculated_count == 1  # edge_ids[1]は行が無い
