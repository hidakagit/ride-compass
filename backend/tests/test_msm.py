"""`domain/msm.py`——MSM格子の幾何（配信元のメタ情報から導く）と、地点への双一次補間・風速風向。

ここで見ないもの:
- チャンクの同期と読み出し → `infrastructure/msm_client.py`のテスト
- 格子点マップの座標 → `test_wind_grid.py`

格子は配信元の実際の値（緯度0.05度・経度0.0625度）に頼らず、テストが小さな格子を与える。
"""

import numpy as np
import pytest

from app.domain import msm

# 南10・西100・北11・東102、3×9点 → 緯度0.5度・経度0.25度間隔（緯度と経度を取り違えると間隔が入れ替わる）
GRID = msm.MsmGrid.from_bbox_and_shape((10.0, 100.0, 11.0, 102.0), n_lat=3, n_lon=9)


def _points(*points: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    return np.array([p[0] for p in points]), np.array([p[1] for p in points])


# ---- メタ情報から格子を導く ----


def test_the_bbox_is_read_south_west_north_east_from_the_wkt():
    wkt = 'GEOGCRS["WGS 84", USAGE[SCOPE["x"], BBOX[ 22.4 , -120.0 ,47.6, 150.0 ]]]'

    assert msm.parse_bbox(wkt) == (22.4, -120.0, 47.6, 150.0)


def test_a_wkt_without_a_bbox_is_an_error():
    with pytest.raises(ValueError):
        msm.parse_bbox('GEOGCRS["WGS 84"]')


def test_the_spacing_comes_from_the_bbox_and_the_array_shape():
    assert (GRID.lat_min, GRID.lon_min, GRID.d_lat, GRID.d_lon) == (10.0, 100.0, 0.5, 0.25)


@pytest.mark.parametrize(("n_lat", "n_lon"), [(1, 5), (3, 1)])
def test_a_grid_needs_at_least_two_points_each_way(n_lat, n_lon):
    with pytest.raises(ValueError):
        msm.MsmGrid.from_bbox_and_shape((10.0, 100.0, 11.0, 102.0), n_lat=n_lat, n_lon=n_lon)


# ---- 切り出す窓 ----


def test_the_window_covers_the_points_and_one_more_row_and_column_up():
    window = GRID.window(*_points((10.2, 100.6)))

    assert (window.lat_slice, window.lon_slice) == (slice(0, 2), slice(2, 4))


def test_the_window_stops_at_the_far_edge_of_the_grid():
    window = GRID.window(*_points((11.0, 102.0)))

    assert (window.lat_slice, window.lon_slice) == (slice(2, 3), slice(8, 9))


@pytest.mark.parametrize("point", [(9.99, 101.0), (11.01, 101.0), (10.5, 99.99), (10.5, 102.01)])
def test_a_point_outside_the_grid_on_any_side_is_an_error(point):
    with pytest.raises(ValueError):
        GRID.window(*_points(point))


@pytest.mark.parametrize("point", [(10.0, 100.0), (11.0, 102.0)])
def test_points_exactly_on_the_edge_are_inside(point):
    GRID.window(*_points(point))


# ---- 補間 ----


def _field(window: msm.MsmWindow, times: int = 2) -> np.ndarray:
    """値 = 緯度×10 + 経度 + 時刻×100（平面なので双一次補間で正確に再現される）。"""
    lat = GRID.lat_min + GRID.d_lat * np.arange(GRID.n_lat)
    lon = GRID.lon_min + GRID.d_lon * np.arange(GRID.n_lon)
    full = lat[:, None, None] * 10 + lon[None, :, None] + 100 * np.arange(times)[None, None, :]
    return full[window.lat_slice, window.lon_slice]


@pytest.mark.parametrize(
    "point",
    [
        (10.5, 101.0),  # 格子点ちょうど
        (10.25, 100.625),  # 4点の中央
        (10.1, 101.9),  # 片寄った位置
        (11.0, 102.0),  # 全体の右上端（余分の1つが取れない）
    ],
)
def test_interpolation_reproduces_a_plane_at_any_point(point):
    window = GRID.window(*_points(point))

    values = window.interpolate(_field(window))

    assert values.shape == (1, 2)
    assert values[0] == pytest.approx([point[0] * 10 + point[1], point[0] * 10 + point[1] + 100])


def test_several_points_are_interpolated_from_one_window():
    window = GRID.window(*_points((10.1, 100.2), (10.9, 101.8)))

    values = window.interpolate(_field(window, times=1))

    assert values[:, 0] == pytest.approx([10.1 * 10 + 100.2, 10.9 * 10 + 101.8])


# ---- 風速・風向 ----


@pytest.mark.parametrize(
    ("u", "v", "direction"),
    [
        (0.0, -3.0, 0.0),  # 南へ吹く＝北から吹いてくる
        (-3.0, 0.0, 90.0),  # 西へ吹く＝東から
        (0.0, 3.0, 180.0),
        (3.0, 0.0, 270.0),
    ],
)
def test_the_direction_is_where_the_wind_comes_from(u, v, direction):
    speed, angle = msm.wind_speed_and_direction(np.array([u]), np.array([v]))

    assert speed[0] == pytest.approx(3.0)
    assert angle[0] == pytest.approx(direction)


def test_the_speed_combines_both_components():
    speed, _ = msm.wind_speed_and_direction(np.array([3.0]), np.array([4.0]))

    assert speed[0] == pytest.approx(5.0)
