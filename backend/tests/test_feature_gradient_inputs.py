"""地図の勾配の色の入力（`infrastructure/road_graph_repository.py: RoadGraphRepository.get_feature_gradient_inputs_in_tile`）が、
フィーチャーごとに返す勾配の値。

区間は道路網の形の導出（`batch/derive_topology.py`）が切ったものを使う——way丸ごとの値が両端の標高差になるのは、
区間が道の並びの順に切られ、どの区間の勾配も道と同じ向きを正とするからで、区間の行を手で書くとその前提を
テストが書き写すことになる。区間の勾配そのもの（`edge_materials.average_grade`）は標高の派生の段の責務なので、値で与える。

ここで見ないもの:
- 走行方位で符号を決める・直角に近い道を値なしにする → `test_gradient_way_service.py`
- 取込範囲の外・結果の形 → `test_road_graph_repository_contracts.py`
"""

import asyncpg
import pytest
from sqlalchemy import text

from app.batch import derive_topology
from app.batch.common import asyncpg_dsn
from app.domain.region import BoundingBox
from app.infrastructure.road_graph_repository import EDGE_UNIT_MIN_ZOOM
from tests.conftest import postgis_database_url
from tests.source_ingest import ingest_records, way_record

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
#: 区間ごとの勾配（%）。どちらも区間の向き（＝道の向き）に登る。
SEGMENT_GRADES = {0: 4.0, 1: 6.0}


async def _ingest_switchback(session) -> dict[int, float]:
    """つづら折りの道を取り込んで区間に切り、区間に勾配を与える。区間ごとの長さ（m）を返す。"""
    await ingest_records("osm_way", [
        way_record(SWITCHBACK_WAY_ID, SWITCHBACK, [1, 2, 3]),
        way_record(2, [SWITCHBACK[1], (139.706, 35.6795)], [2, 9]),
    ], bbox=(AREA.min_latitude, AREA.min_longitude, AREA.max_latitude, AREA.max_longitude))
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        await derive_topology.derive(conn)
    finally:
        await conn.close()
    for segment_index, grade in SEGMENT_GRADES.items():
        await session.execute(
            text("UPDATE edge_materials SET average_grade = :grade WHERE osm_way_id = :way AND segment_index = :seg"),
            {"grade": grade, "way": SWITCHBACK_WAY_ID, "seg": segment_index})
    rows = await session.execute(
        text("SELECT segment_index, distance_m FROM road_edges WHERE osm_way_id = :way"), {"way": SWITCHBACK_WAY_ID})
    return dict(rows.all())


async def test_a_whole_way_feature_climbs_by_its_rise_over_its_length_even_on_a_switchback(
        road_graph_session, road_graph_repository):
    lengths = await _ingest_switchback(road_graph_session)
    rise_m = sum(SEGMENT_GRADES[i] / 100 * length for i, length in lengths.items())

    inputs = await road_graph_repository.get_feature_gradient_inputs_in_tile(EDGE_UNIT_MIN_ZOOM - 1, 0, 0, AREA)

    assert inputs[str(SWITCHBACK_WAY_ID)][0] == pytest.approx(rise_m / sum(lengths.values()) * 100, abs=0.01)


async def test_a_segment_feature_has_its_own_gradient(road_graph_session, road_graph_repository):
    await _ingest_switchback(road_graph_session)

    inputs = await road_graph_repository.get_feature_gradient_inputs_in_tile(EDGE_UNIT_MIN_ZOOM, 0, 0, AREA)

    assert {key: grade for key, (grade, _) in inputs.items()} == {
        f"{SWITCHBACK_WAY_ID}-{i}": grade for i, grade in SEGMENT_GRADES.items()}
