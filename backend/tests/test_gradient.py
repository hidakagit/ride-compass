"""`domain/gradient.py`——道路自身の勾配を、その道をこの向きに辿った場合の値にする。"""

from app.domain.gradient import LENS_PERPENDICULAR_BAND_DEG, GradientCalculator

# 道路の向き（始点→終点）。走行方位はテストごとにこれとの差で与える。
ROAD = 30.0


class TestEffectiveGradient:
    def test_the_steepness_never_depends_on_the_angle(self):
        along = [GradientCalculator.effective_gradient(5.0, ROAD, ROAD + d) for d in (0, 30, 60, 74)]
        against = [GradientCalculator.effective_gradient(5.0, ROAD, ROAD + d) for d in (106, 120, 150, 180)]

        assert along == [5.0] * 4
        assert against == [-5.0] * 4

    def test_the_band_edge_itself_has_no_value(self):
        edge = 90 - LENS_PERPENDICULAR_BAND_DEG

        assert GradientCalculator.effective_gradient(5.0, ROAD, ROAD + edge) is None

    def test_just_outside_the_band_has_a_value(self):
        outside = 90 - LENS_PERPENDICULAR_BAND_DEG - 0.1

        assert GradientCalculator.effective_gradient(5.0, ROAD, ROAD + outside) == 5.0

    def test_the_band_is_symmetric_around_perpendicular(self):
        inside = 90 + LENS_PERPENDICULAR_BAND_DEG - 0.1
        outside = 90 + LENS_PERPENDICULAR_BAND_DEG + 0.1

        assert GradientCalculator.effective_gradient(5.0, ROAD, ROAD + inside) is None
        assert GradientCalculator.effective_gradient(5.0, ROAD, ROAD + outside) == -5.0

    def test_the_value_is_the_same_from_either_edge_row_of_the_road(self):
        """示せる範囲でだけ成り立つ——直角ちょうどは符号を選べない。"""
        for delta in (0, 30, 60, 120, 150, 180):
            travel = ROAD + delta

            assert GradientCalculator.effective_gradient(5.0, ROAD, travel) == (
                GradientCalculator.effective_gradient(-5.0, ROAD + 180, travel)
            )
