"""`domain/wind_grid.py`——風・降水の格子点マップの座標（固定の原点からの格子・最寄り格子点・詳細格子）。

ここで見ないもの:
- 格子点の値の取得 → `services/weather_service.py`（`test_weather_route.py`等）
- 詳細格子の点数の上限の検査 → `api/routers/weather.py`

範囲と間隔は宣言（関東の範囲・0.1度）に頼らず、テストが小さな範囲を与える。詳細格子は原点を
モジュールの範囲（`WIND_GRID_BBOX`）から取るため、その範囲を差し替える。
"""

import pytest

from app.domain import wind_grid
from app.domain.route import Coordinates

# (min_lon, min_lat, max_lon, max_lat)。幅0.35度は0.1度の整数倍ではない
BBOX = (139.0, 35.0, 139.35, 35.2)
SPACING = 0.1


def _pairs(points: list[Coordinates]) -> set[tuple[float, float]]:
    return {(p.latitude, p.longitude) for p in points}


# ---- 格子点マップ ----


def test_the_grid_starts_at_the_south_west_corner_and_stops_inside_the_bbox():
    points = _pairs(wind_grid.generate_wind_grid_points(BBOX, SPACING))

    lats = sorted({lat for lat, _ in points})
    lons = sorted({lon for _, lon in points})
    assert lats == [35.0, 35.1, 35.2]
    # 幅が間隔の整数倍でないときは、端点を越えない最後の格子点で止まる
    assert lons == [139.0, 139.1, 139.2, 139.3]
    assert len(points) == len(lats) * len(lons)


def test_grid_coordinates_carry_no_floating_point_drift():
    # 端が格子線ちょうどだと、割り算の丸めで最後の1本が落ちうる（実装が許容と明記している）ため、幅は半端にする
    points = wind_grid.generate_wind_grid_points((139.0, 35.0, 139.75, 35.0), SPACING)

    assert [p.longitude for p in points] == [139.0, 139.1, 139.2, 139.3, 139.4, 139.5, 139.6, 139.7]


# ---- 最寄り格子点 ----


@pytest.mark.parametrize(
    "point",
    [(35.04, 139.06), (35.16, 139.24), (35.2, 139.35), (35.001, 139.349)],
)
def test_the_nearest_grid_point_is_always_a_point_of_the_same_grid(point):
    grid = _pairs(wind_grid.generate_wind_grid_points(BBOX, SPACING))

    nearest = wind_grid.nearest_grid_point(Coordinates(latitude=point[0], longitude=point[1]), BBOX, SPACING)

    assert (nearest.latitude, nearest.longitude) in grid


def test_every_grid_point_is_its_own_nearest_point():
    grid = wind_grid.generate_wind_grid_points(BBOX, SPACING)
    assert grid

    for point in grid:
        assert wind_grid.nearest_grid_point(point, BBOX, SPACING) == point


def test_the_nearest_grid_point_rounds_to_the_closest():
    nearest = wind_grid.nearest_grid_point(Coordinates(latitude=35.16, longitude=139.24), BBOX, SPACING)

    assert (nearest.latitude, nearest.longitude) == (35.2, 139.2)


def test_a_point_beyond_the_last_grid_point_takes_the_last_one():
    # 139.35へ最も近いのは139.4だが、格子は139.3で終わる
    nearest = wind_grid.nearest_grid_point(Coordinates(latitude=35.0, longitude=139.35), BBOX, SPACING)

    assert nearest.longitude == 139.3


@pytest.mark.parametrize(
    ("point", "expected"),
    [((34.0, 138.0), (35.0, 139.0)), ((36.0, 140.0), (35.2, 139.3))],
)
def test_a_point_outside_the_bbox_is_clamped_to_its_edge(point, expected):
    nearest = wind_grid.nearest_grid_point(Coordinates(latitude=point[0], longitude=point[1]), BBOX, SPACING)

    assert (nearest.latitude, nearest.longitude) == expected


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
