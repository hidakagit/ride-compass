"""MSM格子の幾何・補間（domain/msm.py）のテスト。"""

import numpy as np
import pytest

from app.domain.msm import MsmGrid, interpolate_points, parse_bbox, wind_speed_and_direction

CRS_WKT = 'GEOGCRS["WGS 84", USAGE[SCOPE["grid"], BBOX[22.4,120.0,47.6,150.0]]]'


def test_parse_bbox_reads_south_west_north_east():
    assert parse_bbox(CRS_WKT) == (22.4, 120.0, 47.6, 150.0)


def test_parse_bbox_raises_without_bbox():
    with pytest.raises(ValueError):
        parse_bbox('GEOGCRS["WGS 84"]')


def test_grid_derives_spacing_from_bbox_and_shape():
    """MSMの格子間隔（緯度0.05度・経度0.0625度）は定数ではなく配信元の情報から導かれる。"""
    grid = MsmGrid.from_bbox_and_shape(parse_bbox(CRS_WKT), n_lat=505, n_lon=481)

    assert grid.d_lat == pytest.approx(0.05)
    assert grid.d_lon == pytest.approx(0.0625)
    assert grid.lat_min == 22.4
    assert grid.lon_min == 120.0


def test_grid_rejects_degenerate_shape():
    with pytest.raises(ValueError):
        MsmGrid.from_bbox_and_shape((0.0, 0.0, 1.0, 1.0), n_lat=1, n_lon=10)


def _grid() -> MsmGrid:
    return MsmGrid.from_bbox_and_shape((0.0, 0.0, 10.0, 10.0), n_lat=11, n_lon=11)


def test_slice_bounds_includes_upper_neighbour_for_interpolation():
    grid = _grid()

    i0, i1, j0, j1 = grid.slice_bounds(np.array([2.5, 4.5]), np.array([1.5, 3.5]))

    # 上端側は補間で参照する隣の格子点まで含める。
    assert (i0, i1) == (2, 6)
    assert (j0, j1) == (1, 5)


def test_slice_bounds_clamps_to_grid_edges():
    grid = _grid()

    i0, i1, j0, j1 = grid.slice_bounds(np.array([10.0]), np.array([10.0]))

    assert i1 == grid.n_lat
    assert j1 == grid.n_lon


def test_slice_bounds_rejects_points_outside_grid():
    grid = _grid()

    with pytest.raises(ValueError):
        grid.slice_bounds(np.array([11.0]), np.array([1.0]))


def test_interpolate_points_returns_grid_value_on_lattice():
    grid = _grid()
    block = np.arange(3 * 3 * 2, dtype=float).reshape(3, 3, 2)

    values = interpolate_points(block, grid, i0=1, j0=1, latitudes=np.array([2.0]), longitudes=np.array([3.0]))

    assert values[0].tolist() == block[1, 2].tolist()


def test_interpolate_points_averages_between_lattice_points():
    grid = _grid()
    block = np.zeros((2, 2, 1))
    block[0, 0, 0], block[1, 0, 0], block[0, 1, 0], block[1, 1, 0] = 0.0, 10.0, 20.0, 30.0

    values = interpolate_points(block, grid, i0=0, j0=0, latitudes=np.array([0.5]), longitudes=np.array([0.5]))

    assert values[0, 0] == pytest.approx(15.0)


def test_interpolate_points_handles_multiple_points_at_once():
    grid = _grid()
    block = np.arange(2 * 2 * 3, dtype=float).reshape(2, 2, 3)

    values = interpolate_points(block, grid, i0=0, j0=0, latitudes=np.array([0.0, 1.0]), longitudes=np.array([0.0, 1.0]))

    assert values.shape == (2, 3)
    assert values[0].tolist() == block[0, 0].tolist()
    assert values[1].tolist() == block[1, 1].tolist()


@pytest.mark.parametrize(
    ("u", "v", "expected_speed", "expected_direction"),
    [
        (0.0, -1.0, 1.0, 0.0),  # 北から吹く風
        (-1.0, 0.0, 1.0, 90.0),  # 東から吹く風
        (0.0, 1.0, 1.0, 180.0),  # 南から吹く風
        (1.0, 0.0, 1.0, 270.0),  # 西から吹く風
        (3.0, 4.0, 5.0, 216.87),
    ],
)
def test_wind_speed_and_direction(u, v, expected_speed, expected_direction):
    speed, direction = wind_speed_and_direction(np.array([u]), np.array([v]))

    assert speed[0] == pytest.approx(expected_speed)
    assert direction[0] == pytest.approx(expected_direction, abs=0.01)


def test_wind_direction_stays_within_zero_to_360():
    rng = np.random.default_rng(0)
    u, v = rng.normal(size=200), rng.normal(size=200)

    _speed, direction = wind_speed_and_direction(u, v)

    assert np.all(direction >= 0.0)
    assert np.all(direction < 360.0)
