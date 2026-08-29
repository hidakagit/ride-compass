"""domain/gradient.py: GradientCalculatorのテスト（改善計画T423）。"""

import math

from app.domain.gradient import GradientCalculator


def test_same_direction_keeps_gradient_unchanged():
    # 走行方位が道路自身の向きと完全に一致（差0度）なら、cos(0)=1でそのまま。
    assert GradientCalculator.effective_gradient(5.0, 90.0, 90.0) == 5.0


def test_opposite_direction_flips_sign():
    # 道路を逆走する想定（差180度）なら、登り坂は下り坂として表れる（cos(180度)=-1）。
    result = GradientCalculator.effective_gradient(5.0, 90.0, 270.0)
    assert math.isclose(result, -5.0, abs_tol=1e-9)


def test_perpendicular_direction_has_no_effect():
    # 走行方位が道路の向きと直角（差90度）なら、その道路の勾配はほぼ無関係
    # （cos(90度)=0）。
    result = GradientCalculator.effective_gradient(5.0, 0.0, 90.0)
    assert math.isclose(result, 0.0, abs_tol=1e-9)


def test_downhill_road_same_direction():
    assert GradientCalculator.effective_gradient(-3.0, 45.0, 45.0) == -3.0


def test_forward_and_backward_edge_agree():
    # domain/gradient.pyのモジュールdocstring・road_graph_repository.py:
    # _WAY_GRADIENT_INPUTS_IN_TILE_SQLのコメントで説明した性質: 同じway・同じ物理区間の
    # forward/backward2行（road_edges、向きが180度反転・gradient_percentの符号も反転）の
    # どちらを使ってeffective_gradientを計算しても、結果は一致する。
    gradient_percent = 4.5
    road_bearing_deg = 123.0
    travel_bearing_deg = 60.0

    forward = GradientCalculator.effective_gradient(gradient_percent, road_bearing_deg, travel_bearing_deg)
    backward = GradientCalculator.effective_gradient(-gradient_percent, road_bearing_deg + 180.0, travel_bearing_deg)

    assert math.isclose(forward, backward, abs_tol=1e-9)


def test_swapping_road_and_travel_bearing_is_symmetric():
    # cosは偶関数のため、road_bearing_degとtravel_bearing_degを入れ替えても結果は同じ。
    a = GradientCalculator.effective_gradient(5.0, 30.0, 200.0)
    b = GradientCalculator.effective_gradient(5.0, 200.0, 30.0)
    assert math.isclose(a, b, abs_tol=1e-9)
