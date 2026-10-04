"""`infrastructure/road_graph_repository.py`の取込範囲——`RoadGraphRepository.get_ingested_area`・`is_covered`。

範囲は、成功した最新の道路の取込が記録した宣言（`profile.target.bbox`）。取込の記録は取込の入口
（`tests/source_ingest.py`）から作る。

ここで見ないもの:
- タイルの問い合わせが範囲の外をNone・範囲の内の0件を空で返すこと → `test_road_graph_repository_contracts.py`
- 範囲の外で生成を断ること → `test_graph_service.py`
"""

import pytest

from app.domain.region import BoundingBox
from tests.source_ingest import ingest_records, point_record, way_record

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


def _box(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> BoundingBox:
    return BoundingBox(min_latitude=min_lat, min_longitude=min_lon, max_latitude=max_lat, max_longitude=max_lon)


# 緯度と経度の値域が重ならない範囲。並びを取り違えると別の範囲になる。
_AREA = _box(35.0, 139.0, 36.0, 140.0)
_ELSEWHERE = _box(40.0, 141.0, 41.0, 142.0)


async def _ingest_roads(area: BoundingBox) -> None:
    await ingest_records("osm_way", [way_record(1, [(139.5, 35.5), (139.501, 35.5)], [10, 11])],
                         bbox=(area.min_latitude, area.min_longitude, area.max_latitude, area.max_longitude))


async def _fail_to_ingest_roads(area: BoundingBox) -> None:
    def records():
        raise RuntimeError("取込の途中で落ちた")
        yield

    with pytest.raises(RuntimeError):
        await ingest_records("osm_way", records(),
                             bbox=(area.min_latitude, area.min_longitude, area.max_latitude, area.max_longitude))


async def test_before_any_road_ingest_succeeds_there_is_no_area_and_nothing_is_covered(road_graph_repository):
    await ingest_records("accident", [point_record(1, 139.5, 35.5)], bbox=(35.0, 139.0, 36.0, 140.0))
    await _fail_to_ingest_roads(_AREA)

    assert await road_graph_repository.get_ingested_area() is None
    assert await road_graph_repository.is_covered(_AREA) is False


async def test_the_area_is_the_one_declared_by_the_latest_successful_road_ingest(road_graph_repository):
    await _ingest_roads(_box(30.0, 130.0, 31.0, 131.0))
    await _ingest_roads(_AREA)
    # 後で失敗した道路の取込・別のソースの取込は、手元の道路データの範囲を変えない。
    await _fail_to_ingest_roads(_ELSEWHERE)
    await ingest_records("accident", [point_record(1, 141.5, 40.5)],
                         bbox=(_ELSEWHERE.min_latitude, _ELSEWHERE.min_longitude,
                               _ELSEWHERE.max_latitude, _ELSEWHERE.max_longitude))

    assert await road_graph_repository.get_ingested_area() == _AREA
    assert await road_graph_repository.is_covered(_box(30.2, 130.2, 30.8, 130.8)) is False


@pytest.mark.parametrize(("area", "covered"), [
    (_box(35.4, 139.4, 35.6, 139.6), True),   # 内側
    (_box(34.0, 138.0, 37.0, 141.0), True),   # 取込範囲を丸ごと含む
    (_box(35.9, 139.9, 36.5, 140.5), True),   # 角が重なる
    (_box(36.0, 140.0, 36.5, 140.5), True),   # 角で接する
    (_box(36.01, 139.4, 36.5, 139.6), False),  # 北へ外れる
    (_box(35.4, 140.01, 35.6, 140.5), False),  # 東へ外れる
])
async def test_an_area_is_covered_when_it_overlaps_the_ingested_area(road_graph_repository, area, covered):
    await _ingest_roads(_AREA)

    assert await road_graph_repository.is_covered(area) is covered
