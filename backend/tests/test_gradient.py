"""`domain/gradient.py`——道路自身の勾配と向き・走行方位から、その向きに辿ったときの勾配。

入口は`GradientCalculator.effective_gradient`。走行方位が決めるのは符号だけで、直角に近い向きは値を持たない。

ここで見ないもの:
- 勾配の値を道ごとに集めてタイルへ配ること → `test_gradient_way_service.py`
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.gradient import LENS_PERPENDICULAR_BAND_DEG, GradientCalculator

effective_gradient = GradientCalculator.effective_gradient

# 直角の帯の端ちょうど（帯は端を含む）と、そこから外へわずかに出た角度。
BAND_EDGE = 90.0 - LENS_PERPENDICULAR_BAND_DEG
JUST_OUTSIDE = BAND_EDGE - 0.1


@pytest.mark.parametrize(
    ("road_bearing", "travel_bearing", "expected"),
    [
        (30.0, 30.0, 6.0),  # 道路の向きに辿る
        (30.0, 210.0, -6.0),  # 逆向きに辿ると登りと下りが入れ替わる
        (350.0, 10.0, 6.0),  # 北をまたいでも、向きの差は20度
        (0.0, JUST_OUTSIDE, 6.0),  # 帯のすぐ外は、角度差があっても急さはそのまま
        (0.0, 180.0 - JUST_OUTSIDE, -6.0),
    ],
)
def test_the_travel_bearing_decides_only_the_sign(road_bearing, travel_bearing, expected):
    assert effective_gradient(6.0, road_bearing, travel_bearing) == expected


@pytest.mark.parametrize(
    "travel_bearing",
    [90.0, 270.0, BAND_EDGE, 180.0 - BAND_EDGE, 180.0 + BAND_EDGE, -90.0],
)
def test_a_road_near_perpendicular_to_the_travel_bearing_has_no_value(travel_bearing):
    assert effective_gradient(6.0, 0.0, travel_bearing) is None


angles = st.floats(min_value=-720.0, max_value=720.0, allow_nan=False)
gradients = st.floats(min_value=-30.0, max_value=30.0, allow_nan=False)


@given(gradient=gradients, road_bearing=angles, travel_bearing=angles)
def test_the_value_keeps_the_steepness_of_the_road(gradient, road_bearing, travel_bearing):
    value = effective_gradient(gradient, road_bearing, travel_bearing)
    assert value is None or abs(value) == abs(gradient)


@given(gradient=gradients, road_bearing=angles, travel_bearing=angles)
def test_the_reverse_row_of_the_same_road_gives_the_same_value(gradient, road_bearing, travel_bearing):
    """同じ道路を逆の向きで持つ行（向きが180度回り、勾配の符号が反転する）からも、同じ答えになる。"""
    assert effective_gradient(gradient, road_bearing, travel_bearing) == effective_gradient(
        -gradient, road_bearing + 180.0, travel_bearing
    )
