"""`domain/gradient.py`——道路自身の勾配を、その道をこの向きに辿った場合の値にする。"""

from app.domain.gradient import LENS_PERPENDICULAR_BAND_DEG, GradientCalculator

# 道路の向き（始点→終点）。走行方位はテストごとにこれとの差で与える。
ROAD = 30.0


class TestEffectiveGradient:
    def test_travelling_along_the_road_keeps_the_sign(self):
        assert GradientCalculator.effective_gradient(5.0, ROAD, ROAD) == 5.0

    def test_travelling_against_the_road_flips_the_sign(self):
        assert GradientCalculator.effective_gradient(5.0, ROAD, ROAD + 180) == -5.0

    def test_the_steepness_never_depends_on_the_angle(self):
        along = [GradientCalculator.effective_gradient(5.0, ROAD, ROAD + d) for d in (0, 30, 60, 89)]
        against = [GradientCalculator.effective_gradient(5.0, ROAD, ROAD + d) for d in (91, 120, 150, 180)]

        assert along == [5.0] * 4
        assert against == [-5.0] * 4

    def test_descent_is_carried_through_the_same_way(self):
        assert GradientCalculator.effective_gradient(-3.0, ROAD, ROAD) == -3.0
        assert GradientCalculator.effective_gradient(-3.0, ROAD, ROAD + 180) == 3.0


class TestShowsGradient:
    def test_travelling_along_the_road_is_shown(self):
        assert GradientCalculator.shows_gradient(ROAD, ROAD) is True

    def test_travelling_against_the_road_is_shown(self):
        """逆走は符号が反転するだけで、示せないわけではない。"""
        assert GradientCalculator.shows_gradient(ROAD, ROAD + 180) is True

    def test_perpendicular_is_not_shown(self):
        assert GradientCalculator.shows_gradient(ROAD, ROAD + 90) is False

    def test_the_band_edge_itself_is_not_shown(self):
        edge = 90 - LENS_PERPENDICULAR_BAND_DEG

        assert GradientCalculator.shows_gradient(ROAD, ROAD + edge) is False

    def test_just_outside_the_band_is_shown(self):
        outside = 90 - LENS_PERPENDICULAR_BAND_DEG - 0.1

        assert GradientCalculator.shows_gradient(ROAD, ROAD + outside) is True

    def test_the_band_is_symmetric_around_perpendicular(self):
        inside = 90 + LENS_PERPENDICULAR_BAND_DEG - 0.1
        outside = 90 + LENS_PERPENDICULAR_BAND_DEG + 0.1

        assert GradientCalculator.shows_gradient(ROAD, ROAD + inside) is False
        assert GradientCalculator.shows_gradient(ROAD, ROAD + outside) is True

    def test_the_value_is_the_same_from_either_edge_row_of_the_road(self):
        """示せる範囲でだけ成り立つ——直角ちょうどは符号を選べない。"""
        shown = [d for d in (0, 30, 60, 120, 150, 180) if GradientCalculator.shows_gradient(ROAD, ROAD + d)]
        assert shown, "示せる角度が1つも無ければ、下の比較は何も確かめていない"

        for delta in shown:
            travel = ROAD + delta

            assert GradientCalculator.effective_gradient(5.0, ROAD, travel) == (
                GradientCalculator.effective_gradient(-5.0, ROAD + 180, travel)
            )

    def test_the_result_does_not_change_when_both_directions_are_flipped(self):
        for delta in (0, 45, 90, 135, 180):
            assert GradientCalculator.shows_gradient(ROAD, ROAD + delta) is GradientCalculator.shows_gradient(
                ROAD + 180, ROAD + delta
            )
