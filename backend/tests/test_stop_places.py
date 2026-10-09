"""立ち寄り先の表（`stop_places`）を、Overture の地点の配布の形から作る。

入口は取込（`ingest_source`。アダプタ`overture_places`は本物で、手元の Parquet を読む）と派生の段
（`derive_stop_places.derive`）。配布の形の小さな見本を Parquet に書いて置き場に置き、表に入った地点を見る。

ここで見ないもの:
- 配布元から手元へ写す取得（`scripts/fetch_overture_places.py`）→ どのテストも通さない（網の向こうの S3 を読むだけで、
  判断を持たない）
- 表を焼いた点のタイル → `test_point_tiles.py`
- 地点の辺り（住所の辞書の逆引き） → `test_place_search_route.py`
"""

from pathlib import Path

import duckdb
import pytest

from app.batch import derive_stop_places
from app.batch.ingest import ingest_source
from app.batch.source_adapters import overture_places
from app.batch.source_profile import load_source_profile
from app.domain.geo import KM_PER_DEGREE_LATITUDE, km_per_degree_longitude
from app.infrastructure.source_models import Source

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
    # 派生の段が、入れた地点の辺りを住所の辞書で引く。
    pytest.mark.usefixtures("placed_address_dictionary"),
]

PROFILE = load_source_profile(None)
ROWS: overture_places.OverturePlaceRows = PROFILE.source(Source.OVERTURE_PLACE).rows

LON = 139.70
LAT = 35.65
#: 経度の1mの度。
M = 1 / (km_per_degree_longitude(LAT) * 1000)
#: 緯度の1mの度。
M_LAT = 1 / (KM_PER_DEGREE_LATITUDE * 1000)
#: 見本どうしを、まとめる距離（30m）より十分に離す間。
APART = 1000 * M

FOOD = ["food_and_drink", "restaurant", "asian_restaurant"]
STORE = ["shopping", "convenience_store"]


def _place(place_id: str, lon: float, hierarchy: list[str], *, confidence: float = 0.9,
           brand: str | None = None, lat: float = LAT) -> dict:
    return {"id": place_id, "lon": lon, "lat": lat, "confidence": confidence, "name": place_id,
            "brand": brand, "hierarchy": hierarchy}


def _write_parquet(path: Path, places: list[dict]) -> None:
    """配布の列の形（公式のスキーマの places の place）のうち、取込が読む列で書く。"""
    with duckdb.connect() as conn:
        conn.execute(
            "CREATE TABLE p (id VARCHAR, geometry GEOMETRY,"
            " bbox STRUCT(xmin DOUBLE, xmax DOUBLE, ymin DOUBLE, ymax DOUBLE), confidence DOUBLE,"
            ' names STRUCT("primary" VARCHAR), brand STRUCT(names STRUCT("primary" VARCHAR)),'
            ' taxonomy STRUCT("primary" VARCHAR, hierarchy VARCHAR[]))')
        for p in places:
            conn.execute(
                "INSERT INTO p VALUES (?, ?::GEOMETRY, {'xmin': ?, 'xmax': ?, 'ymin': ?, 'ymax': ?}, ?,"
                " {'primary': ?}, {'names': {'primary': ?}}, {'primary': ?, 'hierarchy': ?::VARCHAR[]})",
                [p["id"], f"POINT ({p['lon']} {p['lat']})", p["lon"], p["lon"], p["lat"], p["lat"], p["confidence"],
                 p["name"], p["brand"], p["hierarchy"][-1], p["hierarchy"]])
        conn.execute(f"COPY p TO '{path}' (FORMAT parquet)")


@pytest.fixture
def overture_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(overture_places, "DATA_DIR", tmp_path)
    return tmp_path


async def _stop_places(conn, overture_dir: Path, places: list[dict]) -> dict[str, str]:
    """見本を取り込んで立ち寄り先を作り直し、入った地点の 名前 → 群 を返す。"""
    _write_parquet(overture_places.places_path(ROWS.release), places)
    await ingest_source(conn, PROFILE, Source.OVERTURE_PLACE)
    await derive_stop_places.derive(conn)
    return {row["name"]: row["place_group"]
            for row in await conn.fetch("SELECT name, place_group FROM stop_places")}


async def test_each_place_goes_to_the_group_of_its_category(derive_conn, overture_dir):
    """群は分類の道筋のどこかの語で決まる。名所の城は、名所に入れない`historic_site`の下にあっても名所に入る。"""
    samples = {
        "restaurant": (FOOD, "eat_drink"),
        "onsen": (["lifestyle_services", "wellness_service", "public_bath_house", "onsen"], "bath"),
        "bike_rental": (["sports_and_recreation", "recreational_equipment_rental", "bike_rental"], "bicycle"),
        "castle": (["cultural_and_historic", "historic_site", "castle"], "scenic"),
        "hotel": (["lodging", "hotel"], "lodging"),
        "ローソン": (STORE, "convenience"),
    }

    places = [_place(name, LON + i * APART, hierarchy) for i, (name, (hierarchy, _)) in enumerate(samples.items())]

    assert await _stop_places(derive_conn, overture_dir, places) == {
        name: group for name, (_, group) in samples.items()}


async def test_places_outside_the_groups_are_not_taken(derive_conn, overture_dir):
    """寺社は文化財の一覧から、補給の点のうちコンビニ以外は OpenStreetMap から出すので、Overture からは取らない。
    群の語の上の段だけの分類（エステの`spa`・マンションの多い`historic_site`・寮の多い`lodging`だけ）も取らない。"""
    outside = [
        ["cultural_and_historic", "place_of_worship", "buddhist_place_of_worship"],
        ["cultural_and_historic", "religious_organization"],
        ["community_and_government", "public_facility", "public_restroom"],
        ["travel_and_transportation", "parking", "bike_parking"],
        ["lifestyle_services", "wellness_service", "spa"],
        ["cultural_and_historic", "historic_site"],
        ["lodging"],
    ]

    places = [_place(f"outside{i}", LON + i * APART, hierarchy) for i, hierarchy in enumerate(outside)]

    assert await _stop_places(derive_conn, overture_dir, [*places, _place("kept", LON - APART, FOOD)]) == {
        "kept": "eat_drink"}


async def test_places_less_confident_than_the_declared_bound_are_not_taken(derive_conn, overture_dir):
    places = [
        _place("at_bound", LON, FOOD, confidence=ROWS.min_confidence),
        _place("below", LON + APART, FOOD, confidence=ROWS.min_confidence - 0.01),
    ]

    assert await _stop_places(derive_conn, overture_dir, places) == {"at_bound": "eat_drink"}


async def test_places_outside_the_import_area_are_not_taken(derive_conn, overture_dir):
    min_lat = PROFILE.target.bbox[0]
    places = [_place("inside", LON, FOOD), _place("south_of_area", LON, FOOD, lat=min_lat - 0.01)]

    assert await _stop_places(derive_conn, overture_dir, places) == {"inside": "eat_drink"}


async def test_the_same_chain_close_together_in_a_group_becomes_its_most_confident_place(derive_conn, overture_dir):
    """同じ店が出どころごとに表記を変えて少しずれて入っているのを1つにする。別の店（チェーンが違う・分からない・
    群が違う・遠い）は残す。"""
    store = STORE
    places = [
        # 表記の揺れ（ハイフン・店名の有無）で20m → 確からしさの高いほうだけ
        _place("セブン-イレブン", LON, store, confidence=0.8),
        _place("セブンイレブン 南浦和駅西口店", LON + 20 * M, store, confidence=0.95),
        # ブランドの列（英字）と名前（かな）で20m → 1つ
        _place("ファミリーマート 東上野店", LON + APART, store, confidence=0.95),
        _place("FM", LON + APART + 20 * M, store, brand="FamilyMart", confidence=0.8),
        # 表に無いチェーンはブランドの一致で見る
        _place("Cafe A 1", LON + 2 * APART, FOOD, brand="Cafe A", confidence=0.8),
        _place("Cafe A 2", LON + 2 * APART + 20 * M, FOOD, brand="CAFE A", confidence=0.95),
        # 南北に20m → 1つ
        _place("ミニストップ 1", LON + 7 * APART, store, confidence=0.95),
        _place("ミニストップ 2", LON + 7 * APART, store, confidence=0.8, lat=LAT + 20 * M_LAT),
        # 同じチェーンで40m → 両方
        _place("ローソン 1", LON + 3 * APART, store),
        _place("ローソン 2", LON + 3 * APART + 40 * M, store),
        # 違うチェーンで20m（`ローソン`を含む別のチェーン） → 両方
        _place("ローソン 3", LON + 4 * APART, store),
        _place("ローソンストア100 3", LON + 4 * APART + 20 * M, store),
        # チェーンの分からない店で20m → 両方
        _place("個店1", LON + 5 * APART, FOOD),
        _place("個店2", LON + 5 * APART + 20 * M, FOOD),
        # 同じチェーンで違う群で20m → 両方
        _place("セブン-イレブン ホテル", LON + 6 * APART, ["lodging", "hotel"]),
        _place("セブン-イレブン 店", LON + 6 * APART + 20 * M, store),
    ]

    assert set(await _stop_places(derive_conn, overture_dir, places)) == {
        "セブンイレブン 南浦和駅西口店", "ファミリーマート 東上野店", "Cafe A 2", "ローソン 1", "ローソン 2", "ローソン 3",
        "ローソンストア100 3", "個店1", "個店2", "セブン-イレブン ホテル", "セブン-イレブン 店", "ミニストップ 1"}


async def test_each_place_keeps_its_name_without_variations_in_notation(derive_conn, overture_dir):
    """地点の検索が名前を引く形。全角・半角・大文字・空白・ハイフン・中点の揺れを除く。"""
    await _stop_places(derive_conn, overture_dir, [_place("セブン-イレブン　新宿・西口店 ＣＡＦＥ", LON, FOOD)])

    assert await derive_conn.fetchval("SELECT search_name FROM stop_places") == "セブンイレブン新宿西口店cafe"


async def test_the_convenience_group_takes_only_convenience_chains(derive_conn, overture_dir):
    """Overture のコンビニの分類には、コンビニでない店・個人の店も入っている。群「コンビニ」はコンビニのチェーンの名前か
    ブランドに当たる店（小さなチェーン・駅の売店を含む）だけを入れる。ほかの群はチェーンを問わない。"""
    kept = [
        _place("ローソン 渋谷店", LON, STORE),
        _place("スリーエフ 平塚店", LON + APART, STORE),
        _place("トモニー 小平駅店", LON + 2 * APART, STORE),
        _place("FM", LON + 3 * APART, STORE, brand="FamilyMart"),
    ]
    dropped = [
        _place("ダイソー 渋谷店", LON + 4 * APART, STORE),
        _place("根岸屋酒店", LON + 5 * APART, STORE),
        _place("まいばすけっと 渋谷店", LON + 6 * APART, STORE),
        _place("U Co-op", LON + 7 * APART, STORE, brand="Co-op"),
    ]

    assert await _stop_places(derive_conn, overture_dir, [*kept, *dropped, _place("個店", LON - APART, FOOD)]) == {
        "ローソン 渋谷店": "convenience", "スリーエフ 平塚店": "convenience", "トモニー 小平駅店": "convenience",
        "FM": "convenience", "個店": "eat_drink"}


async def test_a_chain_name_whose_voiced_marks_turned_into_spaces_is_still_the_chain(derive_conn, overture_dir):
    """濁点が空白に化けた名前（「セフ ンイレフ ン」）も、そのチェーンとして入り、隣の同じ店とまとまる。"""
    places = [
        _place("セフ ンイレフ ン相生店", LON, STORE, confidence=0.95),
        _place("セブン-イレブン 相生店", LON + 20 * M, STORE, confidence=0.8),
        _place("テ イリーヤマサ キ 遠い店", LON + APART, STORE),
    ]

    assert await _stop_places(derive_conn, overture_dir, places) == {
        "セフ ンイレフ ン相生店": "convenience", "テ イリーヤマサ キ 遠い店": "convenience"}


async def test_an_atm_in_a_store_is_the_store(derive_conn, overture_dir):
    """店の中の ATM の地点は、名前を店の名前に直す。店の隣にあれば店とまとまり、ATM の地点しか無い店も店として残る。
    店でない所の ATM（チェーンに当たらない）は入らない。"""
    places = [
        _place("セブン銀行ATM セブン-イレブン 渋谷本町1丁目店 共同出張所", LON, STORE, confidence=0.95),
        _place("セブン-イレブン 渋谷本町1丁目店", LON + 10 * M, STORE, confidence=0.8),
        _place("銀行ATM | イーネット ファミリーマート横須賀長井一丁目 共同出張所", LON + APART, STORE),
        _place("イーネットATM ファミリーマート宇佐美246号溝の口【ASD】 共同出張所", LON + 2 * APART, STORE),
        _place("セブン銀行ATM ヤオコー 川口SKIPシティ店 共同出張所", LON + 3 * APART, STORE),
    ]

    assert await _stop_places(derive_conn, overture_dir, places) == {
        "セブン-イレブン 渋谷本町1丁目店": "convenience",
        "ファミリーマート横須賀長井一丁目": "convenience",
        "ファミリーマート宇佐美246号溝の口【ASD】": "convenience"}
