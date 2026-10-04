"""`tests/route_world.py`——ルート生成のテストが共有する3×3の格子の道路網と、道路網の倉庫の代役。

格子の引数（一方通行・高速道路・避けたい材料・値の無い材料・孤立した道）が道路網に効いていないと、経路の
テストは宣言と違う世界の上で、別の理由で緑になりうる。倉庫の代役（`NetworkRepository`）は、区間の形を
取り直す同じテストを本物の倉庫（実DB）へも流す。

ここで見ないもの:
- `Weather`（与えた値を返すだけで、本物を真似る振る舞いを持たない）
- 本物の倉庫が取込範囲の外を断ること（代役はどこでも範囲の中にする。`test_ingested_area.py`）
"""

import math

import numpy as np
import pytest

from app.batch import derive_cli
from app.domain.graph import LeanEdge, edge_key, node_key
from app.domain.material_catalog import GRADIENT_PERCENT
from app.domain.region import BoundingBox
from app.domain.traffic import stop_count_material_ids
from app.infrastructure import road_network_store
from app.infrastructure.road_graph_repository import RoadGraphRepository
from tests.conftest import postgis_database_url
from tests.route_world import (
    BAD_MATERIAL,
    COORDINATES,
    ISLAND_NODES,
    WAYS,
    NetworkRepository,
    grid_network,
)
from tests.source_ingest import ingest_records, point_record, way_record

ONEWAY, BAD, UNKNOWN, MOTORWAY, NO_GRADIENT, NO_STOP_COUNT = sorted(WAYS)[:6]


def _directions(network, way: int) -> set[tuple[int, int]]:
    rows = np.flatnonzero(network.edge_way_id == way)
    return {(int(network.node_osm_id[network.edge_from[i]]), int(network.node_osm_id[network.edge_to[i]])) for i in rows}


def _values(network, material: str, way: int) -> set[float]:
    column = network.numeric_values[:, network.numeric_ids.index(material)]
    return {-1.0 if math.isnan(v) else float(v) for v in column[network.edge_way_id == way]}


def test_the_grid_has_what_its_arguments_declare():
    network = grid_network(
        oneway_ways=(ONEWAY,), bad_ways=(BAD,), unknown_ways=(UNKNOWN,), motorway_ways=(MOTORWAY,),
        no_gradient_ways=(NO_GRADIENT,), no_stop_count_ways=(NO_STOP_COUNT,), island=True,
    )
    start, end = WAYS[ONEWAY]
    other = next(way for way in WAYS if way not in (ONEWAY, BAD, UNKNOWN, MOTORWAY, NO_GRADIENT, NO_STOP_COUNT))

    assert _directions(network, ONEWAY) == {(start, end)}
    assert _directions(network, other) == {WAYS[other], WAYS[other][::-1]}
    assert (_values(network, BAD_MATERIAL, BAD), _values(network, BAD_MATERIAL, UNKNOWN),
            _values(network, BAD_MATERIAL, other)) == ({1.0}, {-1.0}, {0.0})
    motorway = network.hard_filter_flags[:, network.hard_filter_ids.index("motorway")]
    assert set(network.edge_way_id[motorway].tolist()) == {MOTORWAY}
    assert (_values(network, GRADIENT_PERCENT, NO_GRADIENT), _values(network, GRADIENT_PERCENT, other)) == ({-1.0}, {0.0})
    for material in stop_count_material_ids():
        assert (_values(network, material, NO_STOP_COUNT), _values(network, material, other)) == ({-1.0}, {0.0})
    island = {i for i, osm in enumerate(network.node_osm_id.tolist()) if osm in ISLAND_NODES}
    touches_island = np.isin(network.edge_from, list(island)) | np.isin(network.edge_to, list(island))
    assert np.isin(network.edge_from[touches_island], list(island)).all()
    assert np.isin(network.edge_to[touches_island], list(island)).all()
    assert touches_island.any()


# --- 道路網の倉庫: 本物と代役へ同じテストを流す -------------------------------------------

WAY = sorted(WAYS)[0]
START, END = WAYS[WAY]


async def _geometry_runs_from_the_start_node_to_the_end_node(repository) -> None:
    """区間の形を取り直すと、向きごとに、始点のノードから終点のノードまでの形になる。"""
    requested = [
        LeanEdge(edge_id=edge_key(WAY, 0, forward), from_node_id=node_key(a), to_node_id=node_key(b),
                 geometry=[], distance_m=0.0, osm_way_id=WAY, segment_index=0, forward=forward)
        for forward, (a, b) in ((True, (START, END)), (False, (END, START)))
    ]
    lat, lon = COORDINATES[START]
    inside = BoundingBox(min_latitude=lat, min_longitude=lon, max_latitude=lat + 0.001, max_longitude=lon + 0.001)

    edges = await repository.get_edges_with_geometry(requested)

    assert await repository.is_covered(inside)
    for edge in requested:
        geometry = edges[edge.edge_id].geometry
        start, end = (START, END) if edge.forward else (END, START)
        assert geometry[0] == pytest.approx(list(COORDINATES[start]))
        assert geometry[-1] == pytest.approx(list(COORDINATES[end]))


async def test_the_stand_in_repository_returns_each_direction_from_its_start_to_its_end():
    await _geometry_runs_from_the_start_node_to_the_end_node(NetworkRepository(grid_network()))


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.xdist_group(name="postgis")
@pytest.mark.postgis
async def test_the_real_repository_returns_each_direction_from_its_start_to_its_end(
        road_graph_repository: RoadGraphRepository, monkeypatch, tmp_path):
    monkeypatch.setattr(road_network_store, "ROOT", tmp_path / "road_network")
    await ingest_records("osm_node", [point_record(n, COORDINATES[n][1], COORDINATES[n][0]) for n in (START, END)])
    await ingest_records("osm_way", [way_record(
        WAY, [(COORDINATES[n][1], COORDINATES[n][0]) for n in (START, END)], [START, END], {"highway": "residential"})])
    assert await derive_cli.run(postgis_database_url(), None) == 0

    await _geometry_runs_from_the_start_node_to_the_end_node(road_graph_repository)
