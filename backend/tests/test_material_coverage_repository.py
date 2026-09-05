"""MaterialCoverageQuery（infrastructure/material_coverage.py）のPostGIS統合テスト。

ridecompass_test DB（conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ）への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import insert

from app.domain.attributes import ElevationAttribute
from app.domain.graph import WaySpec, build_road_graph
from app.infrastructure import accident_models  # noqa: F401  Base.metadataへaccident_*テーブルを登録するためのimport
from app.infrastructure import designation_models  # noqa: F401  Base.metadataへdesignation_*テーブルを登録するためのimport
from app.infrastructure.material_coverage import MATERIAL_COVERAGE_SPECS, MaterialCoverageQuery
from app.infrastructure.road_graph_models import EdgeAttributeCountsRow

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)


async def test_empty_database_yields_zero_totals(road_graph_session):
    counts = await MaterialCoverageQuery(road_graph_session).get_material_coverage_counts()

    assert counts.way_total == 0
    assert counts.edge_total == 0
    assert set(counts.missing_by_material) == set(MATERIAL_COVERAGE_SPECS)
    assert all(v == 0 for v in counts.missing_by_material.values())


async def test_way_materials_are_counted_over_all_raw_ways(road_graph_repository, road_graph_session):
    ways = [
        # 全部そろっている
        WaySpec(
            osm_way_id=300, node_ids=[1, 2], highway="residential", surface=" Asphalt ",
            tags={
                "smoothness": "good", "tracktype": "grade1", "maxspeed": "30", "lanes": "2",
                "lit": "yes", "tunnel": "yes", "bridge": "yes", "motor_vehicle": "no",
                "cycleway:left": "lane", "bicycle": "yes",
            },
        ),
        # surfaceは値があるが良否分類に無い（surfaceは値あり、surface_goodは欠損）。
        # maxspeed/lanesは数値として解釈できない（欠損扱い）。
        WaySpec(
            osm_way_id=301, node_ids=[1, 2], highway="primary", surface="mystery_surface",
            tags={"maxspeed": "30 mph", "lanes": "0"},
        ),
        # タグを一切持たない
        WaySpec(osm_way_id=302, node_ids=[1, 2], highway="track"),
        # highwayすら無い
        WaySpec(osm_way_id=303, node_ids=[1, 2]),
    ]
    await road_graph_repository.save_raw_ways(ways, {1: NODE1, 2: NODE2})
    await road_graph_session.commit()

    counts = await MaterialCoverageQuery(road_graph_session).get_material_coverage_counts()
    missing = counts.missing_by_material

    assert counts.way_total == 4
    assert missing["highway"] == 1
    assert missing["surface"] == 2
    assert missing["surface_good"] == 3
    assert missing["smoothness"] == 3
    assert missing["tracktype"] == 3
    assert missing["maxspeed_kmh"] == 3
    assert missing["lanes_count"] == 3
    assert missing["lit"] == 3
    assert missing["no_lit"] == 3
    assert missing["has_tunnel"] == 3
    assert missing["bridge"] == 3
    assert missing["motor_vehicle_no"] == 3
    assert missing["highway_is_cycleway"] == 1
    assert missing["cycleway_has_track"] == 3
    assert missing["cycleway_has_lane"] == 3
    assert missing["cycleway_has_shared"] == 3
    assert missing["shared_pedestrian_path"] == 3


async def test_edge_materials_are_counted_over_road_edges_using_derived_table_rows(
    road_graph_repository, road_graph_session,
):
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    nodes = {1: NODE1, 2: NODE2}
    await road_graph_repository.save_raw_ways([way], nodes)
    graph = build_road_graph([way], nodes, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    edge_ids = sorted(graph.edges.keys())
    assert len(edge_ids) == 2  # 双方向

    # 勾配: 片方のEdgeは行あり、もう片方は行はあるがaverage_gradeがNULL（どちらも「値あり」は1件）。
    await road_graph_repository.save_elevation_attributes(
        [
            ElevationAttribute(
                edge_id=edge_ids[0], average_grade=1.5, data_source="gsi",
                calculated_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            ),
            ElevationAttribute(
                edge_id=edge_ids[1], average_grade=None, data_source="gsi",
                calculated_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            ),
        ]
    )
    # 事前集計: 片方のEdgeにのみ行がある。
    await road_graph_session.execute(
        insert(EdgeAttributeCountsRow).values(
            edge_id=edge_ids[0], accident_count=0.0, stop_count=0, intersection_count=0,
            computed_at=datetime.now(timezone.utc),
        )
    )
    await road_graph_session.commit()

    counts = await MaterialCoverageQuery(road_graph_session).get_material_coverage_counts()
    missing = counts.missing_by_material

    assert counts.way_total == 1
    assert counts.edge_total == 2
    assert missing["gradient_percent"] == 1
    assert missing["stop_count_per_km"] == 1
    assert missing["intersection_count_per_km"] == 1
    assert missing["accident_count_per_km_year"] == 1
