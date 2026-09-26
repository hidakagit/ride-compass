"""`domain/wind_grid.py`——風・降水の格子点マップの座標（固定の原点からの格子・詳細格子）。

ここで見ないもの:
- 格子点の値の取得 → `services/weather_service.py`（`test_weather_route.py`等）
- 詳細格子の点数の上限の検査 → `api/routers/weather.py`

格子点マップは宣言した範囲と間隔そのもので確かめる。詳細格子はテストが小さな範囲を与える——原点を
モジュールの範囲（`WIND_GRID_BBOX`）から取るため、その範囲を差し替える。
"""

import pytest

from app.domain import wind_grid
from app.domain.route import Coordinates

# (min_lon, min_lat, max_lon, max_lat)。幅0.35度は0.1度の整数倍ではない
BBOX = (139.0, 35.0, 139.35, 35.2)


def _pairs(points: list[Coordinates]) -> set[tuple[float, float]]:
    return {(p.latitude, p.longitude) for p in points}


# ---- 格子点マップ ----


def _grid_lines() -> tuple[list[float], list[float]]:
    points = _pairs(wind_grid.generate_wind_grid_points())
    lats = sorted({lat for lat, _ in points})
    lons = sorted({lon for _, lon in points})
    assert len(points) == len(lats) * len(lons)
    return lats, lons


def test_the_grid_starts_at_the_south_west_corner_and_stops_inside_the_bbox():
    lats, lons = _grid_lines()
    min_lon, min_lat, max_lon, max_lat = wind_grid.WIND_GRID_BBOX

    assert (lats[0], lons[0]) == (min_lat, min_lon)
    # 端点を越えない最後の格子点で止まる（端が格子線ちょうどのとき、割り算の丸めで最後の1本が
    # 落ちうることは実装が許容と明記している）
    spacing = wind_grid.WIND_GRID_SPACING_DEG
    assert lats[-1] <= max_lat and max_lat - lats[-1] <= spacing + 1e-9
    assert lons[-1] <= max_lon and max_lon - lons[-1] <= spacing + 1e-9


def test_grid_coordinates_carry_no_floating_point_drift():
    lats, lons = _grid_lines()

    # 足し算を重ねた誤差（139.29999999…）が残らず、隣どうしの間隔が揃う
    for line in (lats, lons):
        assert all(value == round(value, 4) for value in line)
        assert [round(b - a, 4) for a, b in zip(line, line[1:])] == [wind_grid.WIND_GRID_SPACING_DEG] * (len(line) - 1)


# ---- 詳細格子 ----


@pytest.fixture
def area(monkeypatch):
    monkeypatch.setattr(wind_grid, "WIND_GRID_BBOX", BBOX)


def test_detail_points_of_overlapping_views_share_the_same_coordinates(area):
    left = _pairs(wind_grid.generate_wind_grid_detail_points((139.013, 35.013, 139.071, 35.061), 0.02))
    right = _pairs(wind_grid.generate_wind_grid_detail_points((139.037, 35.029, 139.099, 35.087), 0.02))

    # 見ている範囲の角ではなく、固定の原点から数えた格子なので、重なる範囲では同じ点になる
    assert left & right
    assert all(round((lat - 35.0) / 0.02, 6).is_integer() for lat, _ in left | right)
    assert all(round((lon - 139.0) / 0.02, 6).is_integer() for _, lon in left | right)


def test_detail_points_include_the_grid_line_at_or_before_the_view_edge(area):
    points = _pairs(wind_grid.generate_wind_grid_detail_points((139.05, 35.05, 139.105, 35.105), 0.02))

    assert sorted({lon for _, lon in points}) == [139.04, 139.06, 139.08, 139.1]


def test_detail_points_are_clipped_to_the_service_area(area):
    points = _pairs(wind_grid.generate_wind_grid_detail_points((138.0, 34.0, 139.04, 35.04), 0.02))

    assert min(lat for lat, _ in points) == 35.0
    assert min(lon for _, lon in points) == 139.0


def test_detail_points_are_clipped_at_the_far_edge_too(area):
    points = _pairs(wind_grid.generate_wind_grid_detail_points((139.3, 35.15, 140.0, 36.0), 0.02))

    assert points
    assert max(lat for lat, _ in points) <= 35.2
    assert max(lon for _, lon in points) <= 139.35


def test_detail_points_are_not_capped_here(area):
    # 点数の上限は呼び出し側が確かめる。ここで黙って間引くと、画面の一部だけ風が出なくなる
    points = wind_grid.generate_wind_grid_detail_points(BBOX, wind_grid.WIND_GRID_DETAIL_MIN_SPACING_DEG)

    assert len(points) > wind_grid.WIND_GRID_DETAIL_MAX_POINTS


# 下限と、下限より粗い任意の間隔
@pytest.mark.parametrize("spacing", [wind_grid.WIND_GRID_DETAIL_MIN_SPACING_DEG, 0.003, 0.0137, 0.02])
@pytest.mark.parametrize(
    "view",
    [
        (139.013, 35.013, 139.071, 35.061),  # 範囲の内側
        (139.04, 35.04, 139.1, 35.1),  # 縁が格子線ちょうど
        (138.0, 34.0, 139.04, 35.04),  # 南西でクリップされる
        (139.3, 35.15, 140.0, 36.0),  # 北東でクリップされる
        (138.0, 34.0, 140.0, 36.0),  # 範囲全体を覆う
        (139.35, 35.0, 140.0, 35.2),  # 東の縁に接するだけ
    ],
)
def test_the_counted_detail_points_are_the_generated_ones(area, view, spacing):
    # 呼び出し側は数えた点数で上限を確かめてから点を作るので、数と実物がずれると上限の判定がずれる
    counted = wind_grid.count_wind_grid_detail_points(view, spacing)

    assert counted == len(wind_grid.generate_wind_grid_detail_points(view, spacing))


@pytest.mark.parametrize(
    "view",
    [
        (140.0, 36.0, 141.0, 37.0),  # 範囲の外
        (139.35, 35.0, 140.0, 35.2),  # 東の縁に接するだけ
        (139.1, 35.2, 139.2, 36.0),  # 北の縁に接するだけ
    ],
)
def test_a_view_that_does_not_overlap_the_service_area_has_no_detail_points(area, view):
    assert wind_grid.generate_wind_grid_detail_points(view, 0.02) == []
    assert wind_grid.count_wind_grid_detail_points(view, 0.02) == 0
