import math

from app.domain.gradient import LENS_PERPENDICULAR_BAND_DEG, GradientCalculator


def test_same_direction_keeps_gradient_unchanged():
    # 走行方位が道路自身の向きと一致するなら、そのまま辿る＝道路自身の勾配。
    assert GradientCalculator.effective_gradient(5.0, 90.0, 90.0) == 5.0


def test_opposite_direction_flips_sign():
    # 道路を逆向きに辿る想定（差180度）なら、登り坂は下り坂として表れる。
    result = GradientCalculator.effective_gradient(5.0, 90.0, 270.0)
    assert math.isclose(result, -5.0, abs_tol=1e-9)


def test_magnitude_does_not_shrink_with_the_bearing():
    """走行方位は符号だけを決め、坂の急さは変えない。

    角度差を係数に掛けると、同じ坂が方位次第で緩く見える。15%の坂はどの方位を選んでいても
    15%の坂で、緩い坂と同じ色で塗ってよい理由が無い。
    """
    for travel_bearing_deg in (0.0, 30.0, 60.0, 74.0):
        assert GradientCalculator.effective_gradient(15.0, 0.0, travel_bearing_deg) == 15.0
    # 逆向き寄りでも、入れ替わるのは符号だけ。
    for travel_bearing_deg in (106.0, 150.0, 180.0):
        assert GradientCalculator.effective_gradient(15.0, 0.0, travel_bearing_deg) == -15.0


def test_downhill_road_same_direction():
    assert GradientCalculator.effective_gradient(-3.0, 45.0, 45.0) == -3.0


def test_forward_and_backward_edge_agree():
    # 同じway・同じ物理区間のforward/backward2行（road_edges、向きが180度反転・
    # gradient_percentの符号も反転）のどちらを使っても、結果は一致する。
    gradient_percent = 4.5
    road_bearing_deg = 123.0
    travel_bearing_deg = 60.0

    forward = GradientCalculator.effective_gradient(gradient_percent, road_bearing_deg, travel_bearing_deg)
    backward = GradientCalculator.effective_gradient(-gradient_percent, road_bearing_deg + 180.0, travel_bearing_deg)

    assert math.isclose(forward, backward, abs_tol=1e-9)


def test_swapping_road_and_travel_bearing_is_symmetric():
    # 符号の判定は角度差のcosの向きだけで決まり、cosは偶関数のため入れ替えても結果は同じ。
    a = GradientCalculator.effective_gradient(5.0, 30.0, 200.0)
    b = GradientCalculator.effective_gradient(5.0, 200.0, 30.0)
    assert math.isclose(a, b, abs_tol=1e-9)


def test_perpendicular_road_has_no_gradient_to_show():
    """直角に近い道路は「示せない」であって「平坦」ではない。

    0%として配ると凡例の平坦な段へ入り、実際には急な坂の道が平坦な道と同じ色で塗られる。
    """
    assert GradientCalculator.shows_gradient(road_bearing_deg=90.0, travel_bearing_deg=0.0) is False
    assert GradientCalculator.shows_gradient(road_bearing_deg=270.0, travel_bearing_deg=0.0) is False


def test_road_along_travel_direction_shows_gradient():
    assert GradientCalculator.shows_gradient(road_bearing_deg=0.0, travel_bearing_deg=0.0) is True
    # 逆走（180度）も、符号が反転するだけで示せる。
    assert GradientCalculator.shows_gradient(road_bearing_deg=180.0, travel_bearing_deg=0.0) is True


def test_perpendicular_band_is_symmetric_around_the_right_angle():
    """直角の左右で判定が食い違わない（cosの大小で比べると浮動小数の差でずれる）。"""
    band = LENS_PERPENDICULAR_BAND_DEG
    for offset in (band, band / 2, 0.0):
        assert GradientCalculator.shows_gradient(90.0 - offset, 0.0) is False
        assert GradientCalculator.shows_gradient(90.0 + offset, 0.0) is False
    for offset in (band + 1.0, 45.0):
        assert GradientCalculator.shows_gradient(90.0 - offset, 0.0) is True
        assert GradientCalculator.shows_gradient(90.0 + offset, 0.0) is True
