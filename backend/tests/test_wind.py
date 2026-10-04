"""`domain/wind.py`——風を走行の負荷へ写す式、予報を引く固定の格子、通過予定時刻の推定。

入口は`wind_components`・`wind_drag_ratio_array`（スカラー版`wind_drag_ratio`・成分から求める
`wind_drag_ratio_from_components`）・`grid_index_at_or_below`・`WindLattice`・`WindForecastSeries`・
`estimate_passage_hours`。

ここで見ないもの:
- 風の材料を道・区間へ配る評価器（`domain/dynamic_materials.py`） → `test_wind_way_service.py`・`test_leg_costs.py`
- タイルの道へ予報を引く配信 → `test_wind_way_service.py`
- 探索の時刻ビンと区間の風（`SegmentWind`） → `test_leg_costs.py`・`test_route_generation_behavior.py`
- 地図の風の格子点（`domain/wind_grid.py`） → `test_wind_grid.py`
"""

import math
from datetime import datetime, timedelta

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.route import Coordinates
from app.domain.wind import (
    WIND_DRAG_REFERENCE_SPEED_MS,
    WIND_FORECAST_LAT_STEP_DEG,
    WIND_FORECAST_LON_STEP_DEG,
    WindForecastSeries,
    WindLattice,
    estimate_passage_hours,
    grid_index_at_or_below,
    kmh_to_ms,
    wind_components,
    wind_drag_ratio,
    wind_drag_ratio_array,
    wind_drag_ratio_from_components,
)

#: 風速・走行速度の本番の範囲（m/s）。台風の暴風と、想定速度の上限60km/hを覆う。
WIND_SPEEDS = st.floats(0.0, 40.0)
TRAVEL_SPEEDS = st.floats(1.0, 17.0)
BEARINGS = st.floats(0.0, 360.0)

#: 本番で格子を敷く範囲（日本の周り）の緯度・経度。
LATITUDES = st.floats(20.0, 46.0)
LONGITUDES = st.floats(122.0, 154.0)


def test_kmh_to_ms():
    assert kmh_to_ms(36.0) == pytest.approx(10.0)


# --- 風の分解 ---


@given(WIND_SPEEDS, BEARINGS, BEARINGS, BEARINGS)
def test_wind_components_depend_only_on_the_angle_between_wind_and_travel(speed, wind_dir, bearing, turn):
    """風向と走行方位を同じだけ回しても、走る人が受ける風は変わらない。分解しても風の強さは保たれる。"""
    headwind, crosswind = wind_components(speed, wind_dir, bearing)
    turned = wind_components(speed, wind_dir + turn, bearing + turn)

    assert np.allclose(turned, (headwind, crosswind), atol=1e-9)
    assert math.hypot(float(headwind), float(crosswind)) == pytest.approx(speed, abs=1e-9)


# --- 風の追加負荷 ---


def _one_dimensional(headwind: float, travel_speed: float) -> float:
    """横風の無い場合の素直な式: 相対風速xとして`sign(x)·x² − v²`。"""
    x = travel_speed + headwind
    return (math.copysign(x * x, x) - travel_speed * travel_speed) / WIND_DRAG_REFERENCE_SPEED_MS**2


@given(st.floats(-40.0, 40.0), TRAVEL_SPEEDS)
@example(-WIND_DRAG_REFERENCE_SPEED_MS, WIND_DRAG_REFERENCE_SPEED_MS)  # 相対風速0
def test_without_crosswind_the_drag_follows_the_one_dimensional_square_law(headwind, travel_speed):
    """風向は風が吹いてくる方向（気象の慣習）。追い風が走行速度を超える（相対風速が負になる）所も同じ式で続く。"""
    direction = 0.0 if headwind >= 0 else 180.0

    value = wind_drag_ratio(abs(headwind), direction, 0.0, travel_speed)

    assert value == pytest.approx(_one_dimensional(headwind, travel_speed), abs=1e-9)


@given(st.floats(0.1, 40.0), st.floats(-40.0, 40.0), TRAVEL_SPEEDS, TRAVEL_SPEEDS)
def test_with_a_headwind_a_faster_rider_pays_more(headwind, crosswind, speed_a, speed_b):
    """同じ向かい風でも、速く走るほど負荷が大きい（材料の値が想定速度で変わる理由）。"""
    slow, fast = sorted((speed_a, speed_b))
    if fast - slow < 1e-3:
        return

    assert wind_drag_ratio_from_components(headwind, crosswind, slow) < wind_drag_ratio_from_components(
        headwind, crosswind, fast
    )


@given(st.floats(0.1, 40.0), TRAVEL_SPEEDS)
def test_a_pure_crosswind_adds_a_little_drag(speed, travel_speed):
    """真横の風も相対風速を増やすので、負荷は正になる。"""
    assert wind_drag_ratio(speed, 90.0, 0.0, travel_speed) > 0.0


def test_the_array_form_evaluates_each_element():
    values = wind_drag_ratio_array(
        np.array([5.0, 5.0, 0.0]), np.array([0.0, 180.0, 0.0]), np.array([0.0, 0.0, 0.0]), 5.0
    )

    assert values.tolist() == pytest.approx([_one_dimensional(5.0, 5.0), _one_dimensional(-5.0, 5.0), 0.0])


def test_drag_requires_a_positive_travel_speed():
    with pytest.raises(ValueError):
        wind_drag_ratio(3.0, 0.0, 0.0, 0.0)


# --- 固定の格子 ---


@given(st.integers(-3_000, 3_000), st.sampled_from([WIND_FORECAST_LAT_STEP_DEG, WIND_FORECAST_LON_STEP_DEG]))
def test_a_value_on_a_grid_line_belongs_to_that_line(k, step):
    """割り算の丸めで格子線ちょうどの値が1本下へ落ちない（例: 0.15 / 0.05 = 2.9999…）。"""
    assert grid_index_at_or_below(k * step, step) == k


@given(st.floats(-180.0, 180.0), st.sampled_from([WIND_FORECAST_LAT_STEP_DEG, WIND_FORECAST_LON_STEP_DEG]))
def test_the_grid_line_is_at_or_below_the_value(value, step):
    index = grid_index_at_or_below(value, step)

    assert index * step <= value + 1e-9
    assert value < (index + 1) * step + 1e-9


def _lattice(south, west, north, east) -> WindLattice:
    return WindLattice.covering(south, west, north, east, WIND_FORECAST_LAT_STEP_DEG, WIND_FORECAST_LON_STEP_DEG)


def test_lattice_points_run_west_to_east_within_rows_from_the_south():
    lattice = WindLattice(south=35.0, west=139.0, lat_step=0.5, lon_step=0.25, rows=2, cols=3)

    latitudes, longitudes = lattice.coordinates()

    assert latitudes.tolist() == pytest.approx([35.0, 35.0, 35.0, 35.5, 35.5, 35.5])
    assert longitudes.tolist() == pytest.approx([139.0, 139.25, 139.5, 139.0, 139.25, 139.5])


@given(LATITUDES, LONGITUDES, st.floats(0.001, 1.0), st.floats(0.001, 1.0))
def test_the_covering_lattice_contains_the_rectangle(south, west, height, width):
    north, east = south + height, west + width
    latitudes, longitudes = _lattice(south, west, north, east).coordinates()

    assert latitudes.min() <= south + 1e-9 and latitudes.max() >= north - 1e-9
    assert longitudes.min() <= west + 1e-9 and longitudes.max() >= east - 1e-9


@given(
    LATITUDES,
    LONGITUDES,
    st.tuples(st.floats(0.0, 0.5), st.floats(0.0, 0.5), st.floats(0.0, 0.5), st.floats(0.0, 0.5)),
    st.tuples(st.floats(0.0, 0.5), st.floats(0.0, 0.5), st.floats(0.0, 0.5), st.floats(0.0, 0.5)),
)
def test_a_place_picks_the_same_forecast_point_whatever_rectangle_the_lattice_covers(lat, lon, margins_a, margins_b):
    """地図のタイルに敷いた格子と探索範囲に敷いた格子で、同じ道が同じ予報の点を使う。"""
    picked = []
    for s, w, n, e in (margins_a, margins_b):
        lattice = _lattice(lat - s, lon - w, lat + n, lon + e)
        latitudes, longitudes = lattice.coordinates()
        point = int(lattice.points_of(np.array([lat]), np.array([lon]))[0])
        picked.append((latitudes[point], longitudes[point]))

    assert picked[0] == pytest.approx(picked[1], abs=1e-9)


@given(LATITUDES, LONGITUDES, st.floats(0.01, 1.0), st.floats(0.01, 1.0), st.floats(0.0, 1.0), st.floats(0.0, 1.0))
def test_a_place_inside_the_lattice_picks_the_nearest_point(south, west, height, width, fy, fx):
    lattice = _lattice(south, west, south + height, west + width)
    lat, lon = south + fy * height, west + fx * width

    latitudes, longitudes = lattice.coordinates()
    point = int(lattice.points_of(np.array([lat]), np.array([lon]))[0])

    assert abs(latitudes[point] - lat) <= WIND_FORECAST_LAT_STEP_DEG / 2 + 1e-9
    assert abs(longitudes[point] - lon) <= WIND_FORECAST_LON_STEP_DEG / 2 + 1e-9


def test_a_place_outside_the_lattice_picks_the_nearest_edge_point():
    """タイルをまたぐ道の中ほどは格子の外にありうる。"""
    lattice = WindLattice(south=35.0, west=139.0, lat_step=0.5, lon_step=0.5, rows=2, cols=2)

    points = lattice.points_of(np.array([30.0, 40.0]), np.array([130.0, 150.0]))

    assert points.tolist() == [0, 3]


# --- 時別の予報 ---

T0 = datetime(2026, 7, 1, 9, 0)


def _series(hours=3, lattice=None) -> WindForecastSeries:
    """格子点2つ。風速は「点の番号×100＋時刻の番号」、風向は時刻の番号×10。"""
    lattice = lattice or WindLattice(south=35.0, west=139.0, lat_step=1.0, lon_step=1.0, rows=1, cols=2)
    points = lattice.rows * lattice.cols
    speed = np.array([[p * 100.0 + t for t in range(hours)] for p in range(points)])
    direction = np.array([[t * 10.0 for t in range(hours)] for _ in range(points)])
    return WindForecastSeries(
        times=[T0 + timedelta(hours=t) for t in range(hours)], speed_ms=speed, direction_deg=direction, lattice=lattice
    )


@pytest.mark.parametrize(
    "broken",
    [
        {"times": [T0]},
        {"speed_ms": np.zeros((2, 2))},
        {"direction_deg": np.zeros((1, 3))},
        {"times": [T0, T0 + timedelta(hours=3), T0 + timedelta(hours=6)]},
    ],
    ids=["時刻が1つ", "風速の形が違う", "風向の形が違う", "1時間刻みでない"],
)
def test_a_series_refuses_values_that_do_not_line_up_with_hourly_times_and_points(broken):
    series = _series()
    fields = {
        "times": series.times,
        "speed_ms": series.speed_ms,
        "direction_deg": series.direction_deg,
        "lattice": series.lattice,
    }

    with pytest.raises(ValueError):
        WindForecastSeries(**{**fields, **broken})


def test_sample_picks_the_nearest_hour_for_each_point():
    series = _series()

    speed, direction = series.sample(T0 + timedelta(hours=1), np.array([-0.4, 0.6, 0.0]), np.array([0, 1, 1]))

    assert speed.tolist() == [1.0, 102.0, 101.0]
    assert direction.tolist() == [10.0, 20.0, 10.0]


def test_sample_extends_the_edge_hours_beyond_the_series():
    """探索では値が無いより端の値の方が妥当。延ばしたことは`sampled_times`が示す。"""
    series = _series()

    speed, _ = series.sample(T0, np.array([-5.0, 10.0]), np.array([1, 1]))
    times, clamped = series.sampled_times(T0, np.array([-5.0, 1.0, 10.0]))

    assert speed.tolist() == [100.0, 102.0]
    assert times == [T0, T0 + timedelta(hours=1), T0 + timedelta(hours=2)]
    assert clamped.tolist() == [True, False, True]


# --- 通過予定時刻 ---

ANCHOR = Coordinates(latitude=35.0, longitude=139.0)
#: 緯度1度の大円の長さ（km、地球の半径6371km）。
KM_PER_DEGREE = 2 * math.pi * 6371.0 / 360


@pytest.mark.parametrize(("direction", "expected"), [(1, 5.0), (-1, 1.0)], ids=["離れていく", "向かっていく"])
def test_passage_hours_move_from_the_offset_by_the_detoured_ride_time(direction, expected):
    """基準点から北へ緯度1度の道と基準点そのもの。緯度1度を1時間で進む速さ・迂回率2で、道までは2時間。"""
    hours = estimate_passage_hours(
        np.array([36.0, 35.0]), np.array([139.0, 139.0]), ANCHOR, 3.0, direction, KM_PER_DEGREE, 2.0
    )

    assert hours.tolist() == pytest.approx([expected, 3.0], rel=1e-4)


def test_passage_hours_require_a_positive_speed():
    with pytest.raises(ValueError):
        estimate_passage_hours(np.array([35.0]), np.array([139.0]), ANCHOR, 0.0, 1, 0.0, 1.3)
