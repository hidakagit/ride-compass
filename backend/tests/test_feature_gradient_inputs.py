"""地図の勾配の色の入力（`infrastructure/road_graph_repository.py: RoadGraphRepository.get_feature_gradient_inputs_in_tile`）が、
フィーチャーごとに返す勾配の値。

区間は道路網の形の導出（`batch/derive_topology.py`）が切ったものを使う——way丸ごとの値が両端の標高差になるのは、
区間が道の並びの順に切られ、どの区間の勾配も道と同じ向きを正とするからで、区間の行を手で書くとその前提を
テストが書き写すことになる。区間の勾配そのもの（`edge_elevation.average_grade`）は、北へ登る標高のタイルから標高の
派生の段（`batch/derive_elevation.py`）が出したものを読んで期待値にする（値の出し方は`test_elevation_values.py`）。

ここで見ないもの:
- 走行方位で符号を決める・直角に近い道を値なしにする → `test_gradient_way_service.py`
- 取込範囲の外・結果の形 → `test_road_graph_repository_contracts.py`
"""

import pytest
from sqlalchemy import text

from app.batch import derive_elevation, derive_topology
from app.batch.dem_tile_store import PRODUCT_PRIORITY
from app.domain.region import EDGE_UNIT_MIN_ZOOM, BoundingBox
from tests.conftest import raw_connection
from tests.source_ingest import dem_tile_records, ingest_records, way_record

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

AREA = BoundingBox(min_latitude=35.67, min_longitude=139.69, max_latitude=35.69, max_longitude=139.72)

#: つづら折りの道1。東へ約450m登ってから折り返し、西へ約500m登る。両端を結ぶ方位は北北西で、
#: 東へ向かう区間はそこから90度より大きく離れる。折り返しのノード2を道2も通るので、道1はそこで2区間に切れる。
SWITCHBACK_WAY_ID = 1
SWITCHBACK = [(139.700, 35.680), (139.705, 35.6805), (139.6995, 35.681)]


def _climbing_north(lon: float, lat: float) -> float:
    """北へ1m進むごとに0.4m登る地形。つづら折りのどちらの区間も、区間の向き（＝道の向き）に登る。"""
    return 100.0 + (lat - AREA.min_latitude) * 111_000 * 0.4


async def _ingest_switchback(session) -> dict[int, tuple[float, float]]:
    """つづら折りの道と標高を取り込み、区間に切って標高と勾配を出す。区間ごとの (長さ（m）, 勾配（%）) を返す。"""
    await ingest_records("osm_way", [
        way_record(SWITCHBACK_WAY_ID, SWITCHBACK, [1, 2, 3]),
        way_record(2, [SWITCHBACK[1], (139.706, 35.6795)], [2, 9]),
    ], bbox=(AREA.min_latitude, AREA.min_longitude, AREA.max_latitude, AREA.max_longitude))
    await ingest_records("dem", dem_tile_records(PRODUCT_PRIORITY[0], 15, AREA, _climbing_north))
    async with raw_connection() as conn:
        await derive_topology.derive(conn)
        await derive_elevation.derive(conn, previous=None)
    rows = await session.execute(
        text("SELECT e.segment_index, e.distance_m, m.average_grade FROM road_edges e JOIN edge_elevation m"
             " USING (osm_way_id, segment_index) WHERE e.osm_way_id = :way"), {"way": SWITCHBACK_WAY_ID})
    segments = {segment_index: (length, grade) for segment_index, length, grade in rows.all()}
    # 前提: 2区間とも登り、勾配が違う（取り違えると値が変わる）。
    assert len(segments) == 2 and len({grade for _, grade in segments.values()}) == 2
    assert all(grade > 0 for _, grade in segments.values())
    return segments


async def test_a_whole_way_feature_climbs_by_its_rise_over_its_length_even_on_a_switchback(
        road_graph_session, road_graph_repository):
    segments = await _ingest_switchback(road_graph_session)
    rise_m = sum(grade / 100 * length for length, grade in segments.values())

    inputs = await road_graph_repository.get_feature_gradient_inputs_in_tile(EDGE_UNIT_MIN_ZOOM - 1, 0, 0, AREA)

    assert inputs[str(SWITCHBACK_WAY_ID)][0] == pytest.approx(
        rise_m / sum(length for length, _ in segments.values()) * 100, abs=0.01)


async def test_a_segment_feature_has_its_own_gradient(road_graph_session, road_graph_repository):
    segments = await _ingest_switchback(road_graph_session)

    inputs = await road_graph_repository.get_feature_gradient_inputs_in_tile(EDGE_UNIT_MIN_ZOOM, 0, 0, AREA)

    assert {key: inputs[key][0] for key in (f"{SWITCHBACK_WAY_ID}-{i}" for i in segments)} == {
        f"{SWITCHBACK_WAY_ID}-{i}": pytest.approx(grade, abs=0.005) for i, (_, grade) in segments.items()}
