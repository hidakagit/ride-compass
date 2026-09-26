"""`infrastructure/jma_area_boundaries.py`——地点から、それが属する区域（class20）のコードを引く。

境界は小さな正方形の区域を`write_boundaries`でディスクへ書き、置き場だけを差し替えて本物を読む。
配布元の境界からこの形へ移す側は`test_fetch_jma_area_boundaries.py`が持つ。
"""

import logging

import pytest
from shapely.geometry import box

from app.infrastructure import jma_area_boundaries
from app.infrastructure.jma_area_boundaries import NEAREST_LIMIT_DEG, find_class20_code, write_boundaries

WEST = "1310100"
EAST = "1310200"
#: 西と東の区域の間に、簡略化でできるような細い隙間を空けておく。
GAP = (139.7500, 139.7502)


@pytest.fixture
def boundaries(tmp_path, monkeypatch):
    path = tmp_path / "boundaries.json"
    write_boundaries(path, {
        WEST: box(139.70, 35.65, GAP[0], 35.70),
        EAST: box(GAP[1], 35.65, 139.80, 35.70),
    })
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", path)
    return path


@pytest.mark.parametrize(("lat", "lon", "expected"), [
    (35.68, 139.72, WEST),
    (35.68, 139.78, EAST),
    # 隙間の中は、近いほうの区域へ寄せる。
    (35.68, GAP[1] - 0.00001, EAST),
    # 岸壁・橋のように区域の外へわずかに出た地点も、最寄りの区域として引く。
    (35.70 + NEAREST_LIMIT_DEG / 2, 139.72, WEST),
])
async def test_a_point_resolves_to_the_area_containing_or_nearest_to_it(boundaries, lat, lon, expected):
    assert await find_class20_code(lat, lon) == expected


async def test_a_point_farther_than_the_limit_from_every_area_is_none(boundaries):
    """最寄りの区域へ無制限に寄せると、遠い海上の地点に陸の区域の警報が出る。"""
    assert await find_class20_code(35.70 + NEAREST_LIMIT_DEG * 2, 139.72) is None


async def test_missing_boundaries_are_none_with_a_warning(tmp_path, monkeypatch, caplog):
    """境界が無いまま「区域なし」を黙って返すと、警報が出ないことに誰も気づけない。"""
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", tmp_path / "missing.json")

    with caplog.at_level(logging.WARNING, logger="ridecompass.jma_area_boundaries"):
        assert await find_class20_code(35.68, 139.72) is None

    assert "区域の境界を読めない" in caplog.text
