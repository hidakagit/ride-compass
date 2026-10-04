"""`scripts/fetch_jma_area_boundaries.py`——配布元のzip（シェープファイル）から区域の境界を作り、置き場へ置く。

入口は`main`（デプロイが呼ぶ）と、zipから区域を読む`read_areas`。配布元は`respx_mock`で代わりのzipを返し、
置き場（`BOUNDARY_PATH`）は`tmp_path`へ移す。作った境界は`jma_area_boundaries.find_class20_code`で引いて確かめる。
見るのは、置き場に今の版があれば取りに行かないこと・取得から書き込みまで・取得の失敗で置き場を作らないこと・
他の版の掃除・コードの空の図形を落とすこと・同じコードの図形をまとめること・簡略化。

ここで見ないもの:
- 一時ファイル経由の取得と、落としたものを開いて確かめる手順（`app/batch/_common.py: fetch_verified`）→ 同じ手順を使う
  取得の道具のテスト（例: `test_fetch_osm_pbf.py`）
- 置き場の境界から地点の区域を引く規則（含む・寄せる・区域なし）→ `test_jma_area_boundaries.py`
"""

import io
import zipfile

import pytest
import shapefile
import shapely

from app.infrastructure import jma_area_boundaries
from scripts import fetch_jma_area_boundaries


def _ring(west: float, south: float, east: float, north: float) -> list[tuple[float, float]]:
    """シェープファイルの外周は時計回り。"""
    return [(west, south), (west, north), (east, north), (east, south), (west, south)]


def _archive(areas: list[tuple[str, list[list[tuple[float, float]]]]]) -> bytes:
    """配布元と同じ形のzip。中のファイル名は日本語で、使わない付属ファイルも入る。"""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON, encoding="utf-8") as writer:
        writer.field("regioncode", "C", size=10)
        writer.field("name", "C", size=40)
        for code, rings in areas:
            writer.poly(rings)
            writer.record(regioncode=code, name="区域")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        stem = "市町村等（気象警報等）"
        archive.writestr(f"{stem}.shp", shp.getvalue())
        archive.writestr(f"{stem}.shx", shx.getvalue())
        archive.writestr(f"{stem}.dbf", dbf.getvalue())
        archive.writestr(f"{stem}.prj", "GEOGCS[]")
    return buffer.getvalue()


#: 区域「0000010」は1つの図形、「0000020」は離れた2つの図形（島）、コードの空の図形は1つ。
#: どの図形も互いに寄せる距離より遠い。
DISTRIBUTED = [
    ("0000010", [_ring(139.0, 35.0, 139.1, 35.1)]),
    ("0000020", [_ring(139.5, 35.0, 139.6, 35.1)]),
    ("0000020", [_ring(140.0, 35.0, 140.1, 35.1)]),
    ("", [_ring(145.0, 43.0, 145.1, 43.1)]),
]


@pytest.fixture
def destination(monkeypatch, tmp_path):
    path = tmp_path / "jma_area" / "current.json"
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", path)
    return path


async def test_fetches_and_places_the_boundaries_of_each_area(destination, respx_mock):
    respx_mock.get(jma_area_boundaries.SOURCE_URL).respond(content=_archive(DISTRIBUTED))

    assert fetch_jma_area_boundaries.main() == 0

    assert await jma_area_boundaries.find_class20_code(35.05, 139.05) == "0000010"
    assert await jma_area_boundaries.find_class20_code(35.05, 139.55) == "0000020"
    assert await jma_area_boundaries.find_class20_code(35.05, 140.05) == "0000020"
    assert await jma_area_boundaries.find_class20_code(43.05, 145.05) is None


def test_other_versions_and_the_archive_are_removed_after_placing(destination, respx_mock):
    respx_mock.get(jma_area_boundaries.SOURCE_URL).respond(content=_archive(DISTRIBUTED))
    destination.parent.mkdir(parents=True)
    (destination.parent / "older.json").write_text("{}", encoding="utf-8")

    fetch_jma_area_boundaries.main()

    assert list(destination.parent.iterdir()) == [destination]


def test_present_version_is_not_fetched_again_but_other_versions_are_removed(destination, respx_mock):
    """置き場に今の版があれば配布元へ問い合わせない（代役に経路が無いので、問い合わせれば落ちる）。"""
    destination.parent.mkdir(parents=True)
    destination.write_text("{}", encoding="utf-8")
    (destination.parent / "older.json").write_text("{}", encoding="utf-8")

    assert fetch_jma_area_boundaries.main() == 0

    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"status_code": 503}, id="配布元の失敗"),
        pytest.param({"content": b"<html>maintenance</html>"}, id="zipでない"),
    ],
)
def test_failed_fetch_places_nothing(destination, respx_mock, response):
    respx_mock.get(jma_area_boundaries.SOURCE_URL).respond(**response)

    assert fetch_jma_area_boundaries.main() == 1

    assert not destination.exists()


def test_boundaries_are_simplified_within_the_tolerance(tmp_path):
    """頂点の細かい境界は、許容誤差の内側の頂点が落ちて軽くなる。"""
    tolerance = fetch_jma_area_boundaries.SIMPLIFY_TOLERANCE_DEG
    west, south, east, north = 139.0, 35.0, 139.1, 35.1
    step = tolerance / 10
    # 西の辺を、許容誤差より小さく左右へ振れる頂点で細かく刻む（時計回りに南西から北へ）。
    western_edge = [(west + (step if i % 2 else 0.0), south + i * step) for i in range(int((north - south) / step))]
    ring = [*western_edge, (west, north), (east, north), (east, south), (west, south)]
    archive_path = tmp_path / "areas.zip"
    archive_path.write_bytes(_archive([("0000010", [ring])]))

    areas = fetch_jma_area_boundaries.read_areas(archive_path)

    assert shapely.get_num_coordinates(areas["0000010"]) < len(ring) / 100
    assert areas["0000010"].hausdorff_distance(shapely.Polygon(ring)) <= tolerance
