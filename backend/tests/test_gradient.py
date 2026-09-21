"""`domain/gradient.py`——道路自身の勾配を、その道をこの向きに辿った場合の値にする。"""

from app.domain.gradient import LENS_PERPENDICULAR_BAND_DEG, GradientCalculator

# 道路の向き（始点→終点）。走行方位はテストごとにこれとの差で与える。
ROAD = 30.0


class TestEffectiveGradient:
    """走行方位が決めるのは**符号だけ**。"""

    def test_travelling_along_the_road_keeps_the_sign(self):
        assert GradientCalculator.effective_gradient(5.0, ROAD, ROAD) == 5.0

    def test_travelling_against_the_road_flips_the_sign(self):
        """逆向きに辿れば登りは下りになる。"""
        assert GradientCalculator.effective_gradient(5.0, ROAD, ROAD + 180) == -5.0

    def test_the_steepness_never_depends_on_the_angle(self):
        """**角度差で急さを割り引かない**（cos投影しない）。道路は道路に沿ってしか走れず、
        辿る以上は坂の急さをそのまま受ける。割り引くと、同じ坂が方位次第で緩く見える。
        """
        along = [GradientCalculator.effective_gradient(5.0, ROAD, ROAD + d) for d in (0, 30, 60, 89)]
        against = [GradientCalculator.effective_gradient(5.0, ROAD, ROAD + d) for d in (91, 120, 150, 180)]

        assert along == [5.0] * 4
        assert against == [-5.0] * 4

    def test_descent_is_carried_through_the_same_way(self):
        assert GradientCalculator.effective_gradient(-3.0, ROAD, ROAD) == -3.0
        assert GradientCalculator.effective_gradient(-3.0, ROAD, ROAD + 180) == 3.0


class TestShowsGradient:
    """直角に近いと、その道をどちら向きに辿るかが決まらず符号を選べない。

    示せない範囲は値そのものを配らない——0%として配ると、実際には急な坂である道が
    地図の凡例で「平坦」の段に入り、平坦な道と同じ色で塗られる。
    """

    def test_travelling_along_the_road_is_shown(self):
        assert GradientCalculator.shows_gradient(ROAD, ROAD) is True

    def test_travelling_against_the_road_is_shown(self):
        """逆走は符号が反転するだけで、示せないわけではない。"""
        assert GradientCalculator.shows_gradient(ROAD, ROAD + 180) is True

    def test_perpendicular_is_not_shown(self):
        assert GradientCalculator.shows_gradient(ROAD, ROAD + 90) is False

    def test_the_band_edge_itself_is_not_shown(self):
        """境界ちょうどは示さない側に入る（判定は「帯より外なら示す」）。"""
        edge = 90 - LENS_PERPENDICULAR_BAND_DEG

        assert GradientCalculator.shows_gradient(ROAD, ROAD + edge) is False

    def test_just_outside_the_band_is_shown(self):
        outside = 90 - LENS_PERPENDICULAR_BAND_DEG - 0.1

        assert GradientCalculator.shows_gradient(ROAD, ROAD + outside) is True

    def test_the_band_is_symmetric_around_perpendicular(self):
        """直角の左右で同じ幅。片側だけで判定すると、逆走時に判定が入れ替わる。"""
        inside = 90 + LENS_PERPENDICULAR_BAND_DEG - 0.1
        outside = 90 + LENS_PERPENDICULAR_BAND_DEG + 0.1

        assert GradientCalculator.shows_gradient(ROAD, ROAD + inside) is False
        assert GradientCalculator.shows_gradient(ROAD, ROAD + outside) is True

    def test_the_value_is_the_same_from_either_edge_row_of_the_road(self):
        """同じ道路には向きの違う2行（forward/backward）がある。逆方向の行は道路の向きが
        180度回り、勾配の符号も反転している。符号が2回反転して元に戻るため、どちらの行から
        求めても同じ値になる——示せる範囲でだけ成り立つ（直角ちょうどは符号を選べない）。
        """
        shown = [d for d in (0, 30, 60, 120, 150, 180) if GradientCalculator.shows_gradient(ROAD, ROAD + d)]
        assert shown, "示せる角度が1つも無ければ、下の比較は何も確かめていない"

        for delta in shown:
            travel = ROAD + delta

            assert GradientCalculator.effective_gradient(5.0, ROAD, travel) == (
                GradientCalculator.effective_gradient(-5.0, ROAD + 180, travel)
            )

    def test_the_result_does_not_change_when_both_directions_are_flipped(self):
        """同じ道路の逆方向のedge行は、道路の向きが180度回り勾配の符号も反転する。
        符号が2回反転して元に戻るため、示せるかどうかも変わらない。
        """
        for delta in (0, 45, 90, 135, 180):
            assert GradientCalculator.shows_gradient(ROAD, ROAD + delta) is GradientCalculator.shows_gradient(
                ROAD + 180, ROAD + delta
            )
