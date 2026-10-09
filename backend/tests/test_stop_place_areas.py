"""立ち寄り先の辺り（`stop_places.area`）を、住所の区画と小地域の境界から決める。

入口は取込（`tests/source_ingest.py: ingest_records`）と派生の段（`derive_addresses.derive` → `derive_stop_places.derive`）。
住所の生データ（都道府県・市区町村・町字）・小地域の境界・Overture の地点を取り込み、2つの段を作り直しと同じ順に流して、表に
入った辺りを見る。住所の辞書の置き場は空にしておく——立ち寄り先の段は辞書を読まない。

ここで見ないもの:
- 境界と区画の結び付け方（名前・頭・お尻・中の代表点） → `test_address_areas.py`
- 地点の検索の候補に辺りを添えること → `test_place_search_route.py`
"""

import pytest

from app.batch import derive_addresses, derive_stop_places
from tests.source_ingest import (
    abr_city_record,
    abr_prefecture_record,
    abr_town_record,
    estat_small_area_record,
    ingest_records,
    point_record,
)

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
    pytest.mark.usefixtures("address_dictionary_dir"),
]

#: 道路の取込の範囲（min_lat, min_lon, max_lat, max_lon）。住所の区画はこの中の代表点の町字とその祖先。
BBOX = (35.40, 139.40, 36.10, 140.00)

SHINJUKU = ("東京都", "新宿区", "")
IWATSUKI = ("埼玉県", "さいたま市", "岩槻区")
ADDRESSES = [
    abr_prefecture_record("130001", "東京都", 139.69, 35.69),
    abr_prefecture_record("110001", "埼玉県", 139.65, 35.86),
    abr_city_record("131041", "東京都", "新宿区", 139.70, 35.69),
    abr_city_record("111007", "埼玉県", "さいたま市", 139.645, 35.86),
    abr_city_record("111104", "埼玉県", "さいたま市", 139.69, 35.95, ward="岩槻区"),
    abr_town_record("131041", "0024000", "1", SHINJUKU, 139.690, 35.690, oaza="西新宿"),
    abr_town_record("131041", "0024002", "2", SHINJUKU, 139.6915, 35.6885, oaza="西新宿", chome="二丁目"),
    abr_town_record("131041", "0024003", "2", SHINJUKU, 139.6945, 35.6885, oaza="西新宿", chome="三丁目"),
    abr_town_record("111104", "0001000", "1", IWATSUKI, 139.700, 35.950, oaza="本町"),
]


def _square(west: float, south: float, east: float, north: float) -> list[tuple[float, float]]:
    return [(west, south), (west, north), (east, north), (east, south), (west, south)]


#: 西新宿二丁目と三丁目の境界は経度 139.693 の辺を分け合う。「無関係」は名前でも中の代表点でも区画に結べない。
BOUNDARIES = [
    estat_small_area_record("13104002402", "西新宿２丁目", _square(139.690, 35.687, 139.693, 35.690)),
    estat_small_area_record("13104002403", "西新宿３丁目", _square(139.693, 35.687, 139.696, 35.690)),
    estat_small_area_record("11110000100", "本町", _square(139.695, 35.945, 139.705, 35.955)),
    estat_small_area_record("13104009900", "無関係", _square(139.750, 35.750, 139.760, 35.760)),
]


async def _areas(conn, places: dict[str, tuple[float, float]]) -> dict[str, str | None]:
    """住所と境界と地点（鍵 → (経度, 緯度)）を取り込み、住所の段と立ち寄り先の段を流して、地点ごとの辺りを返す。"""
    await ingest_records("osm_way", [], conn=conn, bbox=BBOX)
    await ingest_records("abr", ADDRESSES, conn=conn)
    await ingest_records("estat_small_area", BOUNDARIES, conn=conn)
    await ingest_records("overture_place", [
        point_record(key, lon, lat, {"names": {"primary": f"喫茶{key}"}, "confidence": 0.75,
                                     "brand": {"names": {"primary": None}},
                                     "taxonomy": {"hierarchy": ["food_and_drink", "cafe"]}})
        for key, (lon, lat) in places.items()], conn=conn)
    await derive_addresses.derive(conn)
    await derive_stop_places.derive(conn)
    return {row["source_key"]: row["area"] for row in await conn.fetch("SELECT source_key, area FROM stop_places")}


async def test_a_place_inside_a_boundary_has_the_area_linked_to_it_from_the_city(derive_conn):
    """辺りは境界に結んだ町字の、市区町村から先の名前（都道府県は持たず、政令市は市と区をつなぐ）。"""
    areas = await _areas(derive_conn, {"chome": (139.6912, 35.6881), "oaza": (139.701, 35.951)})

    assert areas == {"chome": "新宿区西新宿二丁目", "oaza": "さいたま市岩槻区本町"}


async def test_a_place_on_the_edge_of_two_boundaries_has_the_area_of_the_smaller_key(derive_conn):
    areas = await _areas(derive_conn, {"edge": (139.693, 35.6885)})

    assert areas == {"edge": "新宿区西新宿二丁目"}


async def test_a_place_outside_the_boundaries_linked_to_an_area_has_no_area(derive_conn):
    """境界の外（海の上等）と、区画に結べなかった境界の中は、辺りを持たない。"""
    areas = await _areas(derive_conn, {"sea": (139.80, 35.55), "unlinked": (139.755, 35.755)})

    assert areas == {"sea": None, "unlinked": None}
