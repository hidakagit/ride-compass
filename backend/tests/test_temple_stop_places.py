"""立ち寄り先の寺社を、国の文化財の建造物（ジャパンサーチの項目の形）から作る。

入口は取込（`ingest_source`。アダプタ`bunka_heritages`は本物で、手元の1行1件の JSON を読む）と派生の段
（`derive_stop_places.derive`）。項目の形の小さな見本を置き場に書き、表に入った寺社を見る。

ここで見ないもの:
- 配信元から手元へ写す取得（`scripts/fetch_bunka_heritages.py`）→ どのテストも通さない（網の向こうの API を順に
  読むだけで、判断を持たない）
- Overture の地点の群とまとめ → `test_stop_places.py`
"""

import json

import pytest

from app.batch import derive_stop_places
from app.batch.ingest import ingest_source
from app.batch.source_adapters import bunka_heritages
from app.batch.source_profile import load_source_profile
from app.domain.geo import km_per_degree_longitude
from app.infrastructure.source_models import Source

pytestmark = pytest.mark.asyncio(loop_scope="module")

PROFILE = load_source_profile(None)
ROWS: bunka_heritages.BunkaHeritageRows = PROFILE.source(Source.BUNKA_HERITAGE).rows

LON = 139.70
LAT = 35.65
#: 経度の1mの度。
M = 1 / (km_per_degree_longitude(LAT) * 1000)
#: 見本の寺社どうしを、まとめる距離（1,000m）より十分に離す間。
APART = 5000 * M

BUILDING = "重要文化財"


def _item(item_id: str, lon: float, owners: str | None, *, designation: str = BUILDING, lat: float = LAT,
          located: bool = True) -> dict:
    """ジャパンサーチの文化遺産オンラインの項目の形（取込と派生が読む項目だけ）。"""
    item: dict = {"id": item_id, "common": {"title": item_id}, "bunka-11-s": designation}
    if located:
        item["common"]["coordinates"] = {"lat": lat, "lon": lon}
    if owners is not None:
        item["bunka-14-s"] = owners
    return item


@pytest.fixture
def bunka_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(bunka_heritages, "DATA_DIR", tmp_path)
    return tmp_path


async def _temples(conn, items: list[dict]) -> list[tuple[str, float, float]]:
    """見本を取り込んで立ち寄り先を作り直し、入った寺社の（名前・経度・緯度）を名前と経度の順で返す。"""
    path = bunka_heritages.heritages_path(ROWS.snapshot)
    path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items), encoding="utf-8")
    await ingest_source(conn, PROFILE, Source.BUNKA_HERITAGE)
    await derive_stop_places.derive(conn)
    rows = await conn.fetch(
        "SELECT name, place_group, source, confidence, ST_X(geom) AS lon, ST_Y(geom) AS lat FROM stop_places")
    assert {(row["place_group"], row["source"], row["confidence"]) for row in rows} <= {
        ("temple_shrine", "bunka_heritage", 1.0)}
    return sorted((row["name"], row["lon"], row["lat"]) for row in rows)


async def test_only_buildings_owned_by_temples_and_shrines_become_temples(derive_conn, bunka_dir):
    """所有者の名前が寺社の語で終わる建物だけが寺社になる。宗教法人の印・括弧書き・空白は名前から除き、所有者が
    複数なら1人ずつ見る。教会・新しい宗教団体・学校・会社・自治体・所有者の書かれていない建物は入らない。"""
    owners = {
        "浅草寺": "浅草寺",
        "宗教法人神田神社": "神田神社",
        "（宗教法人）總持寺": "總持寺",
        "宗教法人　鶴岡八幡宮（鎌倉）": "鶴岡八幡宮",
        "宗教法人神明社": "神明社",
        "宗教法人可睡斎": "可睡斎",
        "宮代町\n玉村八幡宮": "玉村八幡宮",
        "宇都宮市、二荒山神社": "二荒山神社",
        "宗教法人日本基督教団本郷中央教会": None,
        "宗教法人カトリック東京大司教区": None,
        "宗教法人世界救世教": None,
        "学校法人学習院": None,
        "株式会社寺田本家": None,
        "財団法人浅香山病院": None,
        "宇都宮市": None,
        None: None,
    }

    items = [_item(f"bunka-{i}", LON + i * APART, owner) for i, owner in enumerate(owners)]

    assert [name for name, _, _ in await _temples(derive_conn, items)] == sorted(name for name in owners.values() if name)


async def test_buildings_of_one_temple_become_one_place_at_the_building_nearest_their_center(derive_conn, bunka_dir):
    """同じ名前（表記の揺れを除いた形）の建物は、まとめる距離の中で連なれば1つの寺社になる。同じ名前でも離れていれば
    別の寺社。位置はまとまりの重心に最も近い建物。"""
    items = [
        # 本堂・山門・宝蔵が 400m おきに並ぶ（端どうしは 800m）。宗教法人の印の有無・全角で書き分けられている
        _item("bunka-1", LON, "宗教法人金剛寺"),
        _item("bunka-2", LON + 400 * M, "金剛寺"),
        _item("bunka-3", LON + 800 * M, "宗教法人　金剛寺"),
        # 同じ名前の別の寺
        _item("bunka-4", LON + 3 * APART, "金剛寺", lat=LAT + 0.1),
        # 別の名前の寺は隣り合っても別
        _item("bunka-5", LON + 50 * M, "輪王寺"),
    ]

    assert await _temples(derive_conn, items) == [
        ("輪王寺", pytest.approx(LON + 50 * M), pytest.approx(LAT)),
        ("金剛寺", pytest.approx(LON + 400 * M), pytest.approx(LAT)),
        ("金剛寺", pytest.approx(LON + 3 * APART), pytest.approx(LAT + 0.1)),
    ]


async def test_buildings_outside_the_declared_population_are_not_taken(derive_conn, bunka_dir):
    """取込は、範囲の外・宣言に無い指定の別（史跡等の建物でない指定）・位置の無い項目を落とす。"""
    min_lat = PROFILE.target.bbox[0]
    items = [
        _item("bunka-1", LON, "浅草寺"),
        _item("bunka-2", LON + APART, "建長寺", lat=min_lat - 0.01),
        _item("bunka-3", LON + 2 * APART, "円覚寺", designation="史跡名勝天然記念物"),
        _item("bunka-4", LON + 3 * APART, "鶴岡八幡宮", located=False),
    ]

    assert [name for name, _, _ in await _temples(derive_conn, items)] == ["浅草寺"]
