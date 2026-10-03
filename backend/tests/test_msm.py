"""`domain/msm.py`——MSM格子の幾何（範囲の読み取り・切り出す窓）と双一次補間・風の成分から風速と風向。

入口は`parse_bbox`・`MsmGrid.from_bbox_and_shape`・`MsmGrid.window`と、窓の`lat_slice`/`lon_slice`で切り出した
部分ブロックを渡す`MsmWindow.interpolate`、`wind_speed_and_direction`。格子はMSMの公表値（緯度0.05度・
経度0.0625度、北緯22.4〜47.6度・東経120〜150度）で作る。

ここで見ないもの:
- 配信元の同期・メタ情報と実データの読み出し → `test_msm_client.py`
- 補間した風をルートの道へ配ること → `test_wind_way_service.py`
"""

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.msm import MsmGrid, parse_bbox, wind_speed_and_direction

MSM_BBOX = (22.4, 120.0, 47.6, 150.0)
GRID = MsmGrid.from_bbox_and_shape(MSM_BBOX, 505, 481)

_LATITUDES = GRID.lat_min + GRID.d_lat * np.arange(GRID.n_lat)
_LONGITUDES = GRID.lon_min + GRID.d_lon * np.arange(GRID.n_lon)


def _bilinear(lat, lon):
    """双一次補間がそのまま再現する形（緯度・経度・その積の一次式）。時刻ごとに係数を変える。"""
    return np.stack([1.5 + 0.2 * lat - 0.1 * lon + 0.003 * lat * lon, -4.0 + 0.05 * lon - 0.002 * lat * lon], axis=-1)


FIELD = _bilinear(_LATITUDES[:, None], _LONGITUDES[None, :])


def test_the_bbox_is_read_south_west_north_east_from_the_wkt():
    """WKT2のBBOXは南・西・北・東の順。"""
    wkt = 'GEOGCRS["WGS 84",DATUM["World Geodetic System 1984"],USAGE[SCOPE["unknown"],BBOX[ 22.4, 120.0 ,47.6,150.0]]]'
    assert parse_bbox(wkt) == MSM_BBOX


def test_a_wkt_without_a_bbox_is_refused():
    with pytest.raises(ValueError):
        parse_bbox('GEOGCRS["WGS 84"]')


def test_the_published_msm_spacing_follows_from_the_bbox_and_the_shape():
    assert (GRID.d_lat, GRID.d_lon) == (pytest.approx(0.05), pytest.approx(0.0625))


@pytest.mark.parametrize(("n_lat", "n_lon"), [(1, 481), (505, 1)])
def test_a_grid_with_fewer_than_two_points_on_a_side_is_refused(n_lat, n_lon):
    with pytest.raises(ValueError):
        MsmGrid.from_bbox_and_shape(MSM_BBOX, n_lat, n_lon)


def _interpolate(latitudes, longitudes, field=FIELD):
    window = GRID.window(np.asarray(latitudes, dtype=float), np.asarray(longitudes, dtype=float))
    return window, window.interpolate(field[window.lat_slice, window.lon_slice])


_points = st.lists(
    st.tuples(
        st.floats(min_value=MSM_BBOX[0], max_value=MSM_BBOX[2]),
        st.floats(min_value=MSM_BBOX[1], max_value=MSM_BBOX[3]),
    ),
    min_size=1,
    max_size=5,
)


def _nearby_points():
    """ルート1本ぶんのように、格子数マスの中に集まった地点。"""
    return st.tuples(
        st.floats(min_value=MSM_BBOX[0], max_value=MSM_BBOX[2] - 0.3),
        st.floats(min_value=MSM_BBOX[1], max_value=MSM_BBOX[3] - 0.3),
    ).flatmap(
        lambda corner: st.lists(
            st.tuples(
                st.floats(min_value=corner[0], max_value=corner[0] + 0.3),
                st.floats(min_value=corner[1], max_value=corner[1] + 0.3),
            ),
            min_size=1,
            max_size=5,
        )
    )


@given(points=st.one_of(_points, _nearby_points()))
def test_interpolation_reproduces_a_bilinear_field_at_every_point_of_the_grid(points):
    latitudes, longitudes = (np.array(values) for values in zip(*points, strict=True))

    window, values = _interpolate(latitudes, longitudes)

    assert values.shape == (len(points), 2)
    np.testing.assert_allclose(values, _bilinear(latitudes, longitudes), rtol=1e-9, atol=1e-7)
    # 読む部分ブロックは地点の範囲より上下左右に1格子までしか広げない。
    assert window.i1 - window.i0 <= math.ceil((latitudes.max() - latitudes.min()) / GRID.d_lat) + 2
    assert window.j1 - window.j0 <= math.ceil((longitudes.max() - longitudes.min()) / GRID.d_lon) + 2


def test_grid_points_on_the_outer_edges_and_corners_return_the_grid_value():
    """全体格子の上端・右端ちょうどでは、その外側の格子点が無い。"""
    rng = np.random.default_rng(0)
    field = rng.normal(size=(GRID.n_lat, GRID.n_lon, 1))
    rows = [0, GRID.n_lat - 1, GRID.n_lat - 1, 0, GRID.n_lat - 1, 250]
    cols = [0, GRID.n_lon - 1, 0, GRID.n_lon - 1, 240, GRID.n_lon - 1]

    _, values = _interpolate(_LATITUDES[rows], _LONGITUDES[cols], field)

    np.testing.assert_allclose(values[:, 0], field[rows, cols, 0], rtol=1e-9)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(22.39, 135.0), (47.61, 135.0), (35.0, 119.99), (35.0, 150.01)],
    ids=["south", "north", "west", "east"],
)
def test_a_point_outside_the_grid_is_refused(latitude, longitude):
    with pytest.raises(ValueError):
        GRID.window(np.array([35.0, latitude]), np.array([135.0, longitude]))


@given(
    speed=st.floats(min_value=0.1, max_value=60),
    direction=st.floats(min_value=0, max_value=360, exclude_max=True),
)
def test_speed_and_the_direction_the_wind_comes_from_are_recovered_from_the_components(speed, direction):
    """北から吹く風（向かう先は南）は南北成分が負。風向は吹いてくる方位で北=0・東=90。"""
    u = np.array([-speed * math.sin(math.radians(direction))])
    v = np.array([-speed * math.cos(math.radians(direction))])

    speeds, directions = wind_speed_and_direction(u, v)

    assert speeds[0] == pytest.approx(speed)
    difference = (directions[0] - direction + 180) % 360 - 180
    assert abs(difference) < 1e-6
