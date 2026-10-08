"""点のタイル（`infrastructure/point_tile_layers.py: POINT_TILE_LAYERS`）が焼く中身。

レイヤーのSQLを読み出しの口（`RoadGraphRepository.get_tile_mvt`）で流し、タイルに出る点を見る。生データは取込の
入口（`tests/source_ingest.py: ingest_records`）から入れ、POIの種別は派生の段（`derive_node_materials`）を本物のまま
流して付ける。

ここで見ないもの:
- 取り込んだ範囲の判定そのもの（どのrunの範囲か・範囲の境目） → `test_ingested_area.py`
- タグから種別への引き当て・信号とみなす半径 → `test_derive_node_materials.py`
- 宣言どうしの関係（一次属性の指す系統・世代・source-layer名の重なり） → `test_point_tile_layers.py`
- 配信（キャッシュ・空タイル・DB障害・未知のレイヤー） → `test_region_service.py`・`test_region_routes.py`
- 範囲の中で点の無いタイルを空のバイト列にすること → `test_road_graph_repository_contracts.py`
- 自転車・死亡の判定の両側（自転車ではない軽車両・死者0） → `test_derive_counts.py`（同じ式で数える）
- 立ち寄り先の群・絞り・まとめ → `test_stop_places.py`
"""

from collections import Counter

import mapbox_vector_tile
import pytest

from app.batch import derive_node_materials, derive_stop_places
from app.domain.region import BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from app.domain.tuning import TUNING_PARAMETERS_BY_ID
from app.infrastructure.point_tile_layers import POINT_TILE_LAYERS
from app.infrastructure.road_graph_repository import RoadGraphRepository
from tests.conftest import raw_connection
from tests.source_ingest import ingest_records, point_record

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

Z = 16
[(X, Y)] = tiles_covering_bbox(
    BoundingBox(min_latitude=35.6501, min_longitude=139.7001, max_latitude=35.6502, max_longitude=139.7002), Z)
TILE = tile_bounds_lonlat(Z, X, Y)
LON = (TILE.min_longitude + TILE.max_longitude) / 2
LAT = (TILE.min_latitude + TILE.max_latitude) / 2
#: まとめる距離（40m）より十分に近い／遠いずれ（度）。経度0.0001度は約9m、0.002度は約180m。
NEAR = 0.0001
FAR = 0.002
#: タイルを含む取込の範囲（(min_lat, min_lon, max_lat, max_lon)）と、含まない範囲。
COVERING = (35.6, 139.6, 35.7, 139.8)
ELSEWHERE = (34.6, 135.4, 34.7, 135.6)

SIGNAL = {"highway": "traffic_signals"}
CROSSING = {"highway": "crossing"}
STOP = {"highway": "stop"}
GIVE_WAY = {"highway": "give_way"}
BOLLARD = {"barrier": "bollard"}
LEVEL_CROSSING = {"railway": "level_crossing"}
RAIL_FOOT_CROSSING = {"railway": "crossing"}
TOILETS = {"amenity": "toilets"}


async def _ingest_pois(nodes: list[tuple[float, float, dict[str, str]]], road_area=COVERING) -> None:
    """道の取込（範囲の宣言）とノードを取り込み、種別を付ける派生の段を流す。"""
    await ingest_records("osm_way", [], bbox=road_area)
    await ingest_records("osm_node", [point_record(i, lon, lat, tags) for i, (lon, lat, tags) in enumerate(nodes, 1)])
    async with raw_connection() as conn:
        await derive_node_materials.derive(conn, TUNING_PARAMETERS_BY_ID["signal.match_radius_m"].default)


async def _tile(repository: RoadGraphRepository, name: str, x: int = X) -> bytes | None:
    layer = POINT_TILE_LAYERS[name]
    return await repository.get_tile_mvt(layer.sql, layer.source_layer, Z, x, Y, tile_bounds_lonlat(Z, x, Y))


def _features(tile: bytes | None, name: str) -> list[dict]:
    assert tile is not None
    decoded = mapbox_vector_tile.decode(tile)
    assert list(decoded) == [POINT_TILE_LAYERS[name].source_layer]
    return decoded[POINT_TILE_LAYERS[name].source_layer]["features"]


def _overture_place(key: int, lon: float, name: str, hierarchy: tuple[str, ...] = ("food_and_drink", "cafe"),
                    lat: float = LAT) -> object:
    return point_record(key, lon, lat, {
        "names": {"primary": name}, "confidence": 0.75,
        "brand": {"names": {"primary": None}}, "taxonomy": {"hierarchy": list(hierarchy)}})


async def _ingest_stop_places(places: list[object]) -> None:
    """Overture の地点を取り込み、立ち寄り先の表を作る派生の段を流す。"""
    await ingest_records("overture_place", places)
    async with raw_connection() as conn:
        await derive_stop_places.derive(conn)


def _kinds(tile: bytes | None) -> Counter[str]:
    return Counter(f["properties"]["kind"] for f in _features(tile, "poi"))


# --- POI ---------------------------------------------------------------------


async def test_a_poi_tile_outside_the_imported_roads_is_not_baked(road_graph_repository):
    """道を取り込んでいない所の点は、範囲の外として空タイルへ回る（一部だけ取得済みの範囲で、無いと誤読させない）。"""
    await _ingest_pois([(LON, LAT, STOP)], road_area=ELSEWHERE)

    assert await _tile(road_graph_repository, "poi") is None


async def test_each_poi_is_a_point_named_by_its_kind(road_graph_repository):
    await _ingest_pois([
        (LON, LAT, SIGNAL),
        (LON + FAR, LAT, CROSSING),
        (LON - FAR, LAT, STOP),
        (LON, LAT + FAR, TOILETS),
        (LON, LAT - FAR, {"name": "種別の付かないノード"}),
    ])

    assert _kinds(await _tile(road_graph_repository, "poi")) == Counter(
        {"traffic_signals": 1, "crossing": 1, "stop": 1, "toilets": 1})


async def test_a_crossing_beside_a_signal_is_drawn_as_the_signal(road_graph_repository):
    """信号の付いた交差点の横断歩道は信号として数えるので、地図でも信号の点に入る。"""
    await _ingest_pois([(LON, LAT, SIGNAL), (LON + NEAR, LAT, CROSSING)])

    assert _kinds(await _tile(road_graph_repository, "poi")) == Counter({"traffic_signals": 1})


async def test_nearby_stop_pois_merge_only_within_the_same_legend_row(road_graph_repository):
    """凡例の同じ行（車道の踏切と歩道の踏切）は見分けられないので1点、別の行（一時停止と徐行）は近くても別の点。"""
    await _ingest_pois([
        (LON, LAT, LEVEL_CROSSING),
        (LON + NEAR, LAT, RAIL_FOOT_CROSSING),
        (LON + FAR, LAT, STOP),
        (LON + FAR + NEAR, LAT, GIVE_WAY),
    ])

    assert _kinds(await _tile(road_graph_repository, "poi")) == Counter(
        {"level_crossing": 1, "stop": 1, "give_way": 1})


async def test_stop_pois_farther_apart_than_the_merging_distance_stay_separate(road_graph_repository):
    await _ingest_pois([(LON, LAT, BOLLARD), (LON + FAR, LAT, BOLLARD)])

    assert _kinds(await _tile(road_graph_repository, "poi")) == Counter({"barrier": 2})


async def test_supply_pois_are_never_merged(road_graph_repository):
    """補給の点は別々の実体なので、隣り合っていても1つずつ出す。"""
    await _ingest_pois([(LON, LAT, TOILETS), (LON + NEAR, LAT, TOILETS)])

    assert _kinds(await _tile(road_graph_repository, "poi")) == Counter({"toilets": 2})


@pytest.mark.usefixtures("placed_address_dictionary")
async def test_convenience_stores_come_from_the_stop_places_and_not_from_openstreetmap(road_graph_repository):
    """補給の点のコンビニは立ち寄り先の群「コンビニ」の行から出し、OpenStreetMap の`shop=convenience`は出さない。
    ほかの群の立ち寄り先は補給の点に出ない。"""
    await _ingest_pois([(LON, LAT, {"shop": "convenience"}), (LON + FAR, LAT, TOILETS)])
    await _ingest_stop_places([
        _overture_place(1, LON - FAR, "ローソン 渋谷店", ("shopping", "convenience_store")),
        _overture_place(2, LON, "店2", lat=LAT + FAR),
    ])

    assert _kinds(await _tile(road_graph_repository, "poi")) == Counter({"convenience": 1, "toilets": 1})


async def test_only_a_convenience_store_carries_its_name(road_graph_repository):
    """コンビニは押すと店の名前で外の地図を開けるように名前を持つ。OpenStreetMap の点は名前を焼かない。"""
    await _ingest_pois([(LON + FAR, LAT, {**TOILETS, "name": "公園のトイレ"})])
    await _ingest_stop_places([_overture_place(1, LON - FAR, "ローソン 渋谷店", ("shopping", "convenience_store"))])

    names = {f["properties"]["kind"]: f["properties"].get("name") for f in _features(
        await _tile(road_graph_repository, "poi"), "poi")}

    assert names == {"convenience": "ローソン 渋谷店", "toilets": None}


async def test_a_merged_point_on_a_tile_edge_is_drawn_once(road_graph_repository):
    """タイルの境目をまたぐ塊は、両側のタイルで別々の点にならず、真ん中が入るタイルにだけ1点出る。
    まとめない点は、それぞれ自分の入るタイルにだけ出る。"""
    edge = TILE.max_longitude
    await _ingest_pois([
        (edge - NEAR / 2, LAT, BOLLARD),
        (edge + NEAR * 1.5, LAT, BOLLARD),
        (edge - NEAR / 2, LAT + FAR, TOILETS),
        (edge + NEAR / 2, LAT + FAR, TOILETS),
    ])

    assert _kinds(await _tile(road_graph_repository, "poi")) == Counter({"toilets": 1})
    assert _kinds(await _tile(road_graph_repository, "poi", X + 1)) == Counter({"barrier": 1, "toilets": 1})


# --- 事故 --------------------------------------------------------------------


def _accident(key: int, lon: float, lat: float, *, party_a: str = "03", party_b: str = "03",
              deaths: str = "00", year: str = "2023") -> object:
    return point_record(key, lon, lat, {
        "当事者種別（当事者A）": party_a, "当事者種別（当事者B）": party_b,
        "死者数": deaths, "発生日時　　年": year,
    })


async def test_accident_tiles_do_not_depend_on_the_imported_roads(road_graph_repository):
    """事故は対象範囲を一括で取り込むので、道を取り込んでいない所でも範囲の外にしない。タイルの外の事故は出ない。"""
    await ingest_records("accident", [_accident(1, LON, LAT), _accident(2, LON + 10 * FAR, LAT)])

    assert len(_features(await _tile(road_graph_repository, "accident"), "accident")) == 1


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (dict(party_a="51"), dict(involves_bicycle=True, fatal=False)),
        (dict(party_b="52"), dict(involves_bicycle=True, fatal=False)),
        (dict(deaths="01"), dict(involves_bicycle=False, fatal=True)),
    ],
    ids=["bicycle_as_party_a", "e_bike_as_party_b", "fatal"],
)
async def test_an_accident_point_carries_bicycle_fatal_and_year(road_graph_repository, record, expected):
    await ingest_records("accident", [_accident(1, LON, LAT, year="2021", **record)])

    [feature] = _features(await _tile(road_graph_repository, "accident"), "accident")

    assert feature["properties"] == {**expected, "occurred_year": 2021}


# --- 立ち寄り先 ----------------------------------------------------------------


@pytest.mark.usefixtures("placed_address_dictionary")
async def test_a_stop_place_point_carries_its_group_confidence_and_name(road_graph_repository):
    """立ち寄り先は事故と同じく対象範囲を一括で取り込むので、道を取り込んでいない所でも出す。タイルの外の地点と、
    補給の点に出す群「コンビニ」は出ない。"""
    await _ingest_stop_places([
        _overture_place(1, LON, "店1"),
        _overture_place(2, LON + 10 * FAR, "店2"),
        _overture_place(3, LON + FAR, "ローソン 渋谷店", ("shopping", "convenience_store")),
    ])

    [feature] = _features(await _tile(road_graph_repository, "stop_place"), "stop_place")

    assert feature["properties"] == {"group": "eat_drink", "confidence": 0.75, "name": "店1"}
