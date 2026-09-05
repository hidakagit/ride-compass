"""`domain/wind.py`の風の材料（`wind_drag_ratio_array`）。"""

import math

import numpy as np
import pytest

from app.domain.wind import (
    WIND_DRAG_REFERENCE_SPEED_MS,
    kmh_to_ms,
    wind_drag_ratio,
    wind_drag_ratio_array,
)

V20 = kmh_to_ms(20.0)


def test_reference_speed_is_20_kmh_and_independent_constant():
    assert WIND_DRAG_REFERENCE_SPEED_MS == pytest.approx(5.5556, abs=1e-4)
    assert kmh_to_ms(36.0) == pytest.approx(10.0)


# --- 向かい風・追い風・横風・無風（時速20km基準） ---


def test_headwind_increases_load_quadratically():
    # 北(0)に向かって走行中、北から風が吹いてくる＝真正面からの向かい風。
    # x=v+w, Vr=x → (x²−v²)/v_ref²。
    v = V20
    assert wind_drag_ratio(2.0, 0, 0, v) == pytest.approx(((v + 2.0) ** 2 - v**2) / v**2, abs=1e-9)
    assert wind_drag_ratio(2.0, 0, 0, v) == pytest.approx(0.85, abs=0.01)
    assert wind_drag_ratio(4.0, 0, 0, v) == pytest.approx(1.96, abs=0.01)
    assert wind_drag_ratio(8.0, 0, 0, v) == pytest.approx(4.95, abs=0.01)


def test_tailwind_reduces_load_and_equal_tailwind_gives_minus_one():
    # 南から吹いてくる風＝背後からの追い風。走行速度と同じ追い風で相対風速0→ −v²/v_ref² = −1。
    assert wind_drag_ratio(4.0, 180, 0, V20) == pytest.approx(-0.92, abs=0.01)
    assert wind_drag_ratio(V20, 180, 0, V20) == pytest.approx(-1.0, abs=1e-9)


def test_pure_crosswind_gives_small_positive_load():
    # 東から吹く風は進行方向成分0だが、相対風速が増えるぶんだけ小さな正の値。
    value = wind_drag_ratio(4.0, 90, 0, V20)
    assert value == pytest.approx(0.23, abs=0.01)
    assert 0 < value < wind_drag_ratio(4.0, 0, 0, V20)


def test_no_wind_gives_zero_regardless_of_direction():
    assert wind_drag_ratio(0.0, 45, 270, V20) == pytest.approx(0.0, abs=1e-12)
    assert wind_drag_ratio(0.0, 45, 270, kmh_to_ms(60.0)) == pytest.approx(0.0, abs=1e-12)


# --- 二乗則固有の性質 ---


def test_same_wind_is_heavier_when_riding_faster():
    # 向かい風3m/sで10km/h→30km/hにすると約2.3倍。
    slow = wind_drag_ratio(3.0, 0, 0, kmh_to_ms(10.0))
    fast = wind_drag_ratio(3.0, 0, 0, kmh_to_ms(30.0))
    assert fast / slow == pytest.approx(2.3, abs=0.05)


@pytest.mark.parametrize("wind_speed", [0.5, 3.0, V20 - 0.1, V20 + 0.1, 12.0])
@pytest.mark.parametrize("relative_angle", [0.0, 180.0])
def test_zero_crosswind_matches_one_dimensional_formula(wind_speed, relative_angle):
    # 横風0（sin=0）のとき、2次元式はsign(x)·x² − v²と厳密に一致する。
    v = V20
    x = v + wind_speed * math.cos(math.radians(relative_angle))
    expected = (math.copysign(x * x, x) - v * v) / WIND_DRAG_REFERENCE_SPEED_MS**2
    assert wind_drag_ratio(wind_speed, relative_angle, 0, v) == pytest.approx(expected, abs=1e-9)


def test_continuous_where_tailwind_exceeds_travel_speed():
    v = V20
    epsilon = 1e-4
    below = wind_drag_ratio(v - epsilon, 180, 0, v)
    above = wind_drag_ratio(v + epsilon, 180, 0, v)
    assert abs(above - below) < 1e-6
    assert wind_drag_ratio(v + 3.0, 180, 0, v) < wind_drag_ratio(v, 180, 0, v) < wind_drag_ratio(v - 3.0, 180, 0, v)


def test_array_version_broadcasts_scalar_wind_over_bearing_array():
    bearings = np.array([0.0, 90.0, 180.0, np.nan])
    values = wind_drag_ratio_array(4.0, 0.0, bearings, V20)
    assert values.shape == bearings.shape
    assert values[0] == pytest.approx(wind_drag_ratio(4.0, 0.0, 0.0, V20))
    assert values[1] == pytest.approx(wind_drag_ratio(4.0, 0.0, 90.0, V20))
    assert values[2] == pytest.approx(wind_drag_ratio(4.0, 0.0, 180.0, V20))
    assert np.isnan(values[3])  # bearing未計算のEdgeはNaNのまま


def test_array_version_accepts_per_edge_wind_series():
    speeds = np.array([2.0, 4.0])
    directions = np.array([0.0, 180.0])
    bearings = np.array([0.0, 0.0])
    values = wind_drag_ratio_array(speeds, directions, bearings, V20)
    assert values[0] == pytest.approx(wind_drag_ratio(2.0, 0.0, 0.0, V20))
    assert values[1] == pytest.approx(wind_drag_ratio(4.0, 180.0, 0.0, V20))


def test_non_positive_travel_speed_is_rejected():
    with pytest.raises(ValueError):
        wind_drag_ratio(4.0, 0, 0, 0.0)
