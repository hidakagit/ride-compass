"""点のレイヤー（`infrastructure/point_tile_layers.py: POINT_TILE_LAYERS`）の焼き込むSQLを、
`RoadGraphRepository.get_tile_mvt`で本物のPostGISに流したときに出るもの。

- POI: 近い点をどの単位で1点にまとめるか。地図の点は凡例の行ごとにまとめる。数える側（`batch/derive_counts.py`）が
  1回と数える組でも、凡例で分けて見せている種別は別の点のまま出る（数える側の読み替えは`test_derive_counts.py`）。
  取込範囲の外はタイルを焼かない。
- 事故: 点ごとに自転車が絡むか・死亡事故か・発生年を持ち、取込範囲を判定しない。

ここで見ないもの:
- 取込範囲外・DB障害のときに空タイルを返すこと → `test_region_service.py`
- 未知のレイヤーを断る・レイヤーごとのレート制限 → `test_region_routes.py`
"""

import mapbox_vector_tile
import pytest
from sqlalchemy import text

from app.domain.accident import BICYCLE_PARTY_TYPE_CODES
from app.domain.region import BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from app.infrastructure.point_tile_layers import POINT_TILE_LAYERS, PointTileLayer
from app.infrastructure.road_graph_repository import RoadGraphRepository
from tests.source_ingest import ingest_records, point_record

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

ZOOM = 14
BASE_LON, BASE_LAT = 139.70, 35.68
#: 経度方向に約9m。まとめる距離より十分近い。
NEAR = 0.0001
#: 緯度方向に約220m。まとめる距離より十分遠い。
FAR = 0.002

#: (osm_node_id, 経度, 緯度, 種別, 近くに信号があるか)。
NODES = (
    # 車道用と歩道・自転車道用の踏切は凡例で同じ「踏切」
    (1, BASE_LON, BASE_LAT, "level_crossing", False),
    (2, BASE_LON + NEAR, BASE_LAT, "railway_crossing", False),
    # 車止めとハンプ・狭さくは、数える側では同じ種別だが凡例では別の行
    (3, BASE_LON, BASE_LAT + FAR, "barrier", False),
    (4, BASE_LON + NEAR, BASE_LAT + FAR, "traffic_calming", False),
    # 信号のそばの横断歩道は信号
    (5, BASE_LON, BASE_LAT + 2 * FAR, "crossing", True),
    (6, BASE_LON + NEAR, BASE_LAT + 2 * FAR, "traffic_signals", True),
    # 補給休憩は別々の実体
    (7, BASE_LON, BASE_LAT + 3 * FAR, "convenience", False),
    (8, BASE_LON + NEAR, BASE_LAT + 3 * FAR, "convenience", False),
)


POI = POINT_TILE_LAYERS["poi"]
ACCIDENT = POINT_TILE_LAYERS["accident"]


def _single_tile(around: BoundingBox) -> tuple[int, int]:
    tiles = tiles_covering_bbox(around, ZOOM)
    # 前提: 全部の点が1枚のタイルに入る（境界で分かれると、まとめ方ではなく切り方を見ることになる）。
    assert len(tiles) == 1
    return tiles[0]


async def _features(session, layer: PointTileLayer, x: int, y: int) -> list[dict] | None:
    tile = await RoadGraphRepository(session).get_tile_mvt(
        layer.sql, layer.source_layer, ZOOM, x, y, tile_bounds_lonlat(ZOOM, x, y))
    if tile is None:
        return None
    return mapbox_vector_tile.decode(tile)[layer.source_layer]["features"]


async def _insert_scene(session) -> None:
    lons = [lon for _, lon, _, _, _ in NODES]
    lats = [lat for _, _, lat, _, _ in NODES]
    # 取込範囲の宣言（緯度・経度の順）。タイルはこの範囲に入るときだけ焼く。
    await ingest_records("osm_way", [], bbox=(min(lats), min(lons), max(lats), max(lons)))
    run_id = await ingest_records("osm_node", [point_record(node_id, lon, lat) for node_id, lon, lat, _, _ in NODES])
    for node_id, lon, lat, kind, signals in NODES:
        await session.execute(
            text("INSERT INTO node_materials (osm_node_id, kind, has_traffic_signals, source_run_id)"
                 " VALUES (:id, :kind, :signals, :run)"),
            {"id": node_id, "kind": kind, "signals": signals, "run": run_id})


async def test_nearby_points_merge_only_within_the_same_legend_row(road_graph_session):
    await _insert_scene(road_graph_session)
    around = BoundingBox(min_latitude=BASE_LAT, min_longitude=BASE_LON,
                         max_latitude=BASE_LAT + 3 * FAR, max_longitude=BASE_LON + NEAR)
    x, y = _single_tile(around)

    features = await _features(road_graph_session, POI, x, y)

    assert features is not None
    assert sorted(f["properties"]["kind"] for f in features) == [
        "barrier", "convenience", "convenience", "level_crossing", "traffic_calming", "traffic_signals"]


async def test_poi_tile_outside_the_imported_area_is_not_baked(road_graph_session):
    """取込範囲の外は「点が無いことを確かめた」空タイルではなく、範囲外（None）として返す。"""
    await _insert_scene(road_graph_session)
    far_east = BASE_LON + 1.0
    x, y = _single_tile(BoundingBox(min_latitude=BASE_LAT, min_longitude=far_east,
                                    max_latitude=BASE_LAT + NEAR, max_longitude=far_east + NEAR))

    assert await _features(road_graph_session, POI, x, y) is None


async def test_accident_points_carry_bicycle_fatal_and_year_without_an_imported_area(road_graph_session):
    """事故は取込範囲を判定しない（道路を取り込んでいなくても焼く）。点ごとに、自転車が絡むか・死亡事故か・
    発生年を持つ。"""
    bicycle = min(BICYCLE_PARTY_TYPE_CODES)
    other = "59"
    accidents = (
        ("bicycle-fatal", BASE_LON, BASE_LAT, bicycle, "001", "2023"),
        ("other-injury", BASE_LON + NEAR, BASE_LAT, other, "000", "2024"),
    )
    await ingest_records("accident", [
        point_record(key, lon, lat, {"当事者種別（当事者A）": party, "当事者種別（当事者B）": other,
                                     "死者数": deaths, "発生日時　　年": year})
        for key, lon, lat, party, deaths, year in accidents])
    x, y = _single_tile(BoundingBox(min_latitude=BASE_LAT, min_longitude=BASE_LON,
                                    max_latitude=BASE_LAT + NEAR, max_longitude=BASE_LON + NEAR))

    features = await _features(road_graph_session, ACCIDENT, x, y)

    assert features is not None
    assert sorted((f["properties"]["involves_bicycle"], f["properties"]["fatal"], f["properties"]["occurred_year"])
                  for f in features) == [(False, False, 2024), (True, True, 2023)]
