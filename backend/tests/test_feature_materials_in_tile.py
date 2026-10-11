"""地図の配信が評価するタイルの材料（`infrastructure/road_graph_repository.py: RoadGraphRepository.get_feature_materials_in_tile`）が、
区間単位のズームで、探索が同じ区間に読む材料（`RoadGraphRepository.get_edge_material_arrays`）と同じ値になること。道1本の
ズームで読む区間の材料（`RoadGraphRepository.get_feature_segments_in_tile`）も同じ。

区間は道路網の形の導出（`batch/derive_topology.py`）が切り、勾配・密度の件数は派生の段（`batch/derive_elevation.py`・
`batch/derive_counts.py`）が出したものを使う——区間と区間の値の行を手で書くと、2つの読み出しが同じ表を読むという前提を
テストが書き写すことになる。密度は区間の長さで割るので、件数の付いた区間を置く（長さを道1本から取り違えると値が変わる）。

ここで見ないもの:
- 材料ごとの値式が返す値 → `test_material_values.py`
- 取込範囲の外・式が実在の列だけを読むこと → `test_material_values.py`（読み出しの経路の節）
- 読んだ材料のキャッシュ → `test_feature_materials.py`
- 区間の材料から道1本の値を畳むこと → `test_dynamic_way_values.py`
"""

import numpy as np
import pytest

from app.batch import derive_counts, derive_elevation, derive_nodes, derive_topology
from app.batch.dem_tile_store import PRODUCT_PRIORITY
from app.domain.attributes import CategoricalColumn
from app.domain.material_catalog import segment_material_ids
from app.domain.region import EDGE_UNIT_MIN_ZOOM, BoundingBox
from app.domain.tuning import TUNING_PARAMETERS_BY_ID
from tests.conftest import raw_connection
from tests.source_ingest import dem_tile_records, ingest_records, point_record, way_record

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

AREA = BoundingBox(min_latitude=35.67, min_longitude=139.69, max_latitude=35.69, max_longitude=139.72)
ACCIDENT_YEARS = 1


def _climbing_north(lon: float, lat: float) -> float:
    return 100.0 + (lat - AREA.min_latitude) * 111_000 * 0.4


async def _derive_world() -> None:
    await ingest_records("osm_way", [
        way_record(1, [(139.700, 35.680), (139.705, 35.6805), (139.6995, 35.681)], [1, 2, 3],
                   {"highway": "secondary", "surface": "asphalt", "lit": "yes", "maxspeed": "40"}),
        way_record(2, [(139.705, 35.6805), (139.706, 35.6795)], [2, 9], {"highway": "track", "tracktype": "grade3"}),
    ], bbox=(AREA.min_latitude, AREA.min_longitude, AREA.max_latitude, AREA.max_longitude))
    await ingest_records("osm_node", [point_record(3, 139.6995, 35.681, {"highway": "crossing"})])
    await ingest_records("dem", dem_tile_records(PRODUCT_PRIORITY[0], 15, AREA, _climbing_north))
    async with raw_connection() as conn:
        await derive_topology.derive(conn)
        await derive_elevation.derive(conn, previous=None)
        await derive_nodes.derive(conn, TUNING_PARAMETERS_BY_ID["signal.match_radius_m"].default)
        await derive_counts.derive(conn)


async def test_a_segment_on_the_map_has_the_materials_the_search_reads_for_it(road_graph_repository):
    """違うと、地図で良く見えた道を探索が避ける（同じ道に別の得点が付く）。"""
    await _derive_world()

    tile = await road_graph_repository.get_feature_materials_in_tile(EDGE_UNIT_MIN_ZOOM, 0, 0, AREA, ACCIDENT_YEARS)

    assert tile is not None
    segments = [tuple(map(int, key.split("-"))) for key in tile.feature_keys]
    assert len(segments) == 3
    search = await road_graph_repository.get_edge_material_arrays(
        [way for way, _ in segments], [index for _, index in segments], [True] * len(segments), ACCIDENT_YEARS)
    expected = search.columns()
    assert set(tile.columns) == set(expected)
    assert np.nanmax(expected["poi_crossing_per_km"]) > 0
    categorical = {material_id: column for material_id, column in tile.columns.items()
                   if isinstance(column, CategoricalColumn)}
    numeric = {material_id: column for material_id, column in tile.columns.items() if material_id not in categorical}
    assert categorical and numeric
    rows = range(len(segments))
    assert {material_id: [column.value_at(row) for row in rows] for material_id, column in categorical.items()} == {
        material_id: [expected[material_id].value_at(row) for row in rows] for material_id in categorical}
    for material_id, column in numeric.items():
        np.testing.assert_array_equal(column, expected[material_id], err_msg=material_id)


def _rows(distance_m, columns: dict, rows) -> list[tuple]:
    """区間の長さと材料の値の組を、並びに依らずに比べられるように並べる（値の無い材料は-infで並べる）。"""
    return sorted(tuple(float(column[row]) if not np.isnan(column[row]) else -np.inf
                        for column in [distance_m, *columns.values()]) for row in rows)


async def test_segments_of_a_way_on_the_zoomed_out_map_have_the_materials_the_search_reads_for_them(
    road_graph_repository,
):
    """引いた地図の道1本の値は、その道の区間の材料を探索と同じ値で読んで畳む。違うと、地図の道の色とその道を走った
    ルートの値が食い違う。区間の向きは道1本の勾配の配信と同じ方位で付ける。"""
    await _derive_world()
    async with raw_connection() as conn:
        edges = await conn.fetch("SELECT osm_way_id, segment_index FROM road_edges ORDER BY osm_way_id, segment_index")
    z = EDGE_UNIT_MIN_ZOOM - 1

    segments = await road_graph_repository.get_feature_segments_in_tile(z, 0, 0, AREA, ACCIDENT_YEARS)

    assert segments is not None
    search = await road_graph_repository.get_edge_material_arrays(
        [edge["osm_way_id"] for edge in edges], [edge["segment_index"] for edge in edges], [True] * len(edges),
        ACCIDENT_YEARS)
    expected = search.columns()
    assert set(segments.columns) == segment_material_ids()
    assert np.nanmax(segments.columns["gradient_percent"]) > 0
    for way in {edge["osm_way_id"] for edge in edges}:
        mine = [row for row, key in enumerate(segments.feature_keys) if key == str(way)]
        theirs = [row for row, edge in enumerate(edges) if edge["osm_way_id"] == way]
        assert _rows(segments.distance_m, segments.columns, mine) == _rows(
            search.distance_m, {material_id: expected[material_id] for material_id in segments.columns}, theirs)
    gradient_inputs = await road_graph_repository.get_feature_gradient_inputs_in_tile(z, 0, 0, AREA)
    assert {key: bearing for key, bearing in zip(segments.feature_keys, segments.feature_bearing_deg)} == {
        key: bearing for key, (_, bearing) in gradient_inputs.items()}
