"""上下線が分かれた道の片側か（`batch/derive_way_directions.py`が書く`way_directions.divided`）。

判定の3条件（`carriageway`の申告・同じ名前の対向一方通行・寄り添う対向一方通行）それぞれに、
当たる入力と、条件の外にある入力を1組ずつ置く。生データから派生の段を本物のまま通す。

ここで見ないもの:
- 申告とみなす`carriageway`の値の一つずつ（`dual`のほか）——値の並び（`domain/divided_carriageway.py:
  TAG_VALUES`）の書き写しになる
- 通行方向をタグから決める規則 → `test_resolve_direction.py`
"""

from typing import NamedTuple

import pytest
import pytest_asyncio

from app.batch import derive_topology, derive_way_directions
from app.domain.divided_carriageway import GEOMETRIC_GAP_M, NAMED_GAP_M
from app.domain.geo import KM_PER_DEGREE_LATITUDE
from tests.source_ingest import ingest_records, way_record

# road_graph_session（conftest.py）と同じDBを使うため、.claude/rules/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

BASE_LON, BASE_LAT = 139.70, 35.68
#: 道の長さ（経度、約180m）。
LENGTH = 0.002
#: 場面どうしの間隔（緯度、約1.1km）。どの距離のしきい値よりも十分に遠い。
SPACING = 0.01

ONEWAY = {"highway": "primary", "oneway": "yes"}


class Scene(NamedTuple):
    """1つの場面。`partner`はNoneなら道1本だけ、あれば北へ`gap_m`離して並べる2本目のタグ。"""

    tags: dict[str, str]
    partner: dict[str, str] | None
    gap_m: float
    opposite: bool
    divided: bool


SCENES: dict[str, Scene] = {
    "carriageway を申告した一方通行": Scene(
        {**ONEWAY, "carriageway": "dual"}, None, 0.0, False, True),
    "carriageway を申告した両方向の道": Scene(
        {"highway": "primary", "carriageway": "dual"}, None, 0.0, False, False),
    "同じ名前の対向一方通行が名前の距離の内側": Scene(
        {**ONEWAY, "name": "A"}, {**ONEWAY, "name": "A"}, NAMED_GAP_M - 10, True, True),
    "同じ名前の対向一方通行が名前の距離の外側": Scene(
        {**ONEWAY, "name": "A"}, {**ONEWAY, "name": "A"}, NAMED_GAP_M + 10, True, False),
    "無名の対向一方通行が寄り添う": Scene(
        ONEWAY, ONEWAY, GEOMETRIC_GAP_M - 5, True, True),
    "無名の対向一方通行が寄り添う距離の外側": Scene(
        ONEWAY, ONEWAY, GEOMETRIC_GAP_M + 10, True, False),
    "同じ向きの一方通行が寄り添う": Scene(
        ONEWAY, ONEWAY, GEOMETRIC_GAP_M - 5, False, False),
    "種別の違う対向一方通行が寄り添う": Scene(
        ONEWAY, {**ONEWAY, "highway": "secondary"}, GEOMETRIC_GAP_M - 5, True, False),
    "名前の違う対向一方通行が寄り添う": Scene(
        {**ONEWAY, "name": "A"}, {**ONEWAY, "name": "B"}, GEOMETRIC_GAP_M - 5, True, False),
}


def _ways() -> dict[str, list[tuple[int, dict[str, str], list[tuple[float, float]]]]]:
    """場面ごとの (wayのid, タグ, 頂点の(経度, 緯度)列)。"""
    ways = {}
    for i, (name, scene) in enumerate(SCENES.items()):
        lat = BASE_LAT + SPACING * i
        east = [(BASE_LON, lat), (BASE_LON + LENGTH, lat)]
        ways[name] = [(i * 10 + 1, scene.tags, east)]
        if scene.partner is not None:
            partner_lat = lat + scene.gap_m / (KM_PER_DEGREE_LATITUDE * 1000.0)
            line = [(lon, partner_lat) for lon, _ in east]
            ways[name].append(
                (i * 10 + 2, scene.partner, line[::-1] if scene.opposite else line))
    return ways


WAYS = _ways()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def divided_conn(derive_conn):
    """場面ごとの道を取り込み、区間と道の性質まで作った状態。"""
    conn = derive_conn
    await ingest_records("osm_way", [
        way_record(way_id, points, [way_id * 10 + k for k in range(len(points))], tags)
        for ways in WAYS.values() for way_id, tags, points in ways], conn=conn)
    await derive_topology.derive(conn)
    await derive_way_directions.derive(conn)
    return conn


@pytest.mark.parametrize("scene", SCENES)
async def test_a_way_is_one_side_of_a_divided_road_only_under_its_conditions(divided_conn, scene):
    way_ids = [way_id for way_id, _tags, _points in WAYS[scene]]
    rows = await divided_conn.fetch(
        "SELECT osm_way_id, divided FROM way_directions WHERE osm_way_id = ANY($1)", way_ids)
    assert {r["osm_way_id"]: r["divided"] for r in rows} == dict.fromkeys(
        way_ids, SCENES[scene].divided)
