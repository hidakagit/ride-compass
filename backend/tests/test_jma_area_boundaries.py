"""`infrastructure/jma_area_boundaries.py`——置き場の区域の境界から、地点が属する区域（area.jsonのclass20）のコードを引く。

入口は`find_class20_code`で、境界は`write_boundaries`で置き場（`BOUNDARY_PATH`を`tmp_path`へ移す）に書いたものを
本物の読み込みで読む。区域は架空のコードと矩形で作る。見るのは、境界を一度だけ読んで持つことと、境界を読めない
とき（区域なしとは別の例外とWARNING）。地点から区域を引く規則（含む区域・寄せる距離の内側の最寄りの区域・
どこにも入らない地点のNone）は、境界を直接与えた`AreaBoundaries.find`の性質で見る。

ここで見ないもの:
- 配布元のシェープファイルから境界を作る・置き場の版の入れ替え → `test_fetch_jma_area_boundaries.py`
- 区域のコードから警報エリアを辿る → `test_jma_area.py`
- 区域を引けない・境界を読めないときの警報・洪水予報の応答 → `test_warning_service.py`・`test_flood_service.py`
"""

import logging

import pytest
import shapely
from hypothesis import assume, given
from hypothesis import strategies as st
from shapely.geometry import box

from app.infrastructure import jma_area_boundaries

LIMIT = jma_area_boundaries.NEAREST_LIMIT_DEG

#: 経度方向に長い矩形（緯度35.6〜35.7・経度139.6〜139.9）を東西に分けた区域。緯度と経度を取り違えると外れる。
WEST = box(139.6, 35.6, 139.75, 35.7)
EAST = box(139.75 + LIMIT, 35.6, 139.9, 35.7)


@pytest.fixture
def boundary_path(monkeypatch, tmp_path):
    path = tmp_path / "jma_area" / "boundaries.json"
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", path)
    return path


@pytest.fixture
def two_areas(boundary_path):
    jma_area_boundaries.write_boundaries(boundary_path, {"0000010": WEST, "0000020": EAST})
    return boundary_path


#: 寄せる距離と同じ程度の大きさの区域を、寄せる距離ちょうどの隙間で並べた架空の区域。区域の中・隙間・
#: 寄せる距離の内外が、どれも乱数で十分に引かれる大きさにする。経度方向に長いので、緯度と経度を取り違えると外れる。
_SMALL_AREAS = {
    "0000110": box(139.0, 35.0, 139.0 + 2 * LIMIT, 35.0 + LIMIT),
    "0000120": box(139.0 + 3 * LIMIT, 35.0, 139.0 + 5 * LIMIT, 35.0 + LIMIT),
}


@given(
    lat=st.floats(min_value=35.0 - 2 * LIMIT, max_value=35.0 + 3 * LIMIT),
    lon=st.floats(min_value=139.0 - 2 * LIMIT, max_value=139.0 + 7 * LIMIT),
)
def test_point_gets_the_nearest_area_within_the_limit(lat, lon):
    """含む区域があればそれ、無ければ寄せる距離の内側で最も近い区域、どれも遠ければNone。
    全区域との距離を測った答えと比べる。"""
    point = shapely.Point(lon, lat)
    distances = {code: geometry.distance(point) for code, geometry in _SMALL_AREAS.items()}
    nearest = min(distances.values())
    assume(abs(nearest - LIMIT) > 1e-12)

    found = jma_area_boundaries.AreaBoundaries(list(_SMALL_AREAS), list(_SMALL_AREAS.values())).find(lat, lon)

    if nearest > LIMIT:
        assert found is None
    else:
        assert found is not None
        assert distances[found] <= nearest + 1e-12


async def test_boundaries_are_read_once_and_kept(two_areas):
    """一度読んだ境界はプロセス内に持ち、置き場を読み直さない。"""
    await jma_area_boundaries.find_class20_code(35.65, 139.7)
    two_areas.unlink()

    assert await jma_area_boundaries.find_class20_code(35.65, 139.85) == "0000020"


async def test_missing_boundaries_raise_and_warn_until_they_are_written(boundary_path, caplog):
    """置き場に無ければ、区域なし（None）ではなく読めない例外とWARNING。置いたあとは再起動せずに引ける。"""
    with caplog.at_level(logging.WARNING, logger="ridecompass.jma_area_boundaries"):
        with pytest.raises(jma_area_boundaries.AreaBoundariesUnavailableError):
            await jma_area_boundaries.find_class20_code(35.65, 139.7)
    assert [record.levelno for record in caplog.records] == [logging.WARNING]

    jma_area_boundaries.write_boundaries(boundary_path, {"0000010": WEST})

    assert await jma_area_boundaries.find_class20_code(35.65, 139.7) == "0000010"


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("{", id="JSONでない"),
        pytest.param('{"0000010": "0101"}', id="境界でない"),
    ],
)
async def test_unreadable_boundaries_raise(boundary_path, content):
    boundary_path.parent.mkdir(parents=True)
    boundary_path.write_text(content, encoding="utf-8")

    with pytest.raises(jma_area_boundaries.AreaBoundariesUnavailableError):
        await jma_area_boundaries.find_class20_code(35.65, 139.7)
