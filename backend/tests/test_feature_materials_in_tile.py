"""地図の配信が評価するタイルの材料（`infrastructure/road_graph_repository.py: RoadGraphRepository.get_feature_materials_in_tile`）が、
区間単位のズームで、探索が同じ区間に読む材料（`RoadGraphRepository.get_edge_material_arrays`）と同じ値になること。

区間は道路網の形の導出（`batch/derive_topology.py`）が切り、勾配・密度の件数は派生の段（`batch/derive_elevation.py`・
`batch/derive_counts.py`）が出したものを使う——区間と区間の値の行を手で書くと、2つの読み出しが同じ表を読むという前提を
テストが書き写すことになる。密度は区間の長さで割るので、件数の付いた区間を置く（長さを道1本から取り違えると値が変わる）。

ここで見ないもの:
- 材料ごとの値式が返す値 → `test_material_values.py`
- 取込範囲の外・式が実在の列だけを読むこと → `test_material_values.py`（読み出しの経路の節）
- 読んだ材料のキャッシュ → `test_feature_materials.py`
"""

import numpy as np
import pytest

from app.batch import derive_counts, derive_elevation, derive_nodes, derive_topology
from app.batch.dem_tile_store import PRODUCT_PRIORITY
from app.domain.attributes import CategoricalColumn
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


async def test_a_segment_on_the_map_has_the_materials_the_search_reads_for_it(road_graph_repository):
    """違うと、地図で良く見えた道を探索が避ける（同じ道に別の得点が付く）。"""
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
