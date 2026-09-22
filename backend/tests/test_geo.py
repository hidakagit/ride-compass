"""`domain/geo.py`——緯度経度まわりの計算。方位・距離と、そのベクトル版。"""

import numpy as np

from app.domain.geo import (
    COMPASS_LABELS,
    KM_PER_DEGREE_LATITUDE,
    LatLonPoint,
    bearing_between,
    bearing_between_array,
    compass_label,
    haversine_distance_km,
    haversine_distance_km_array,
)
from app.domain.route import Coordinates

TOKYO = LatLonPoint(latitude=35.68, longitude=139.77)
OSAKA = LatLonPoint(latitude=34.69, longitude=135.50)


class TestCompassLabel:

    def test_each_sector_centre_gets_its_own_label(self):
        assert [compass_label(45 * i) for i in range(8)] == COMPASS_LABELS

    def test_a_sector_boundary_rounds_up(self):
        """22.5度は偶数丸めなら「北」、half-upなら「北東」。"""
        assert compass_label(22.5) == "北東"
        assert compass_label(67.5) == "東"

    def test_angles_outside_one_turn_are_folded(self):
        assert compass_label(360) == compass_label(0)
        assert compass_label(-45) == compass_label(315)
        assert compass_label(725) == compass_label(5)

    def test_the_last_sector_wraps_back_to_north(self):
        """357.75度以上は次の区分＝北へ入る。畳まずに索引を引くと範囲外になる。"""
        assert compass_label(359) == "北"


class TestBearingBetween:

    def test_due_east_is_ninety(self):
        east = bearing_between(TOKYO, LatLonPoint(TOKYO.latitude, TOKYO.longitude + 1))

        assert 89.0 < east < 91.0

    def test_due_west_is_around_two_hundred_seventy(self):
        """負の角度で返さず0〜360へ畳む——方位差の計算が符号で割れる。"""
        west = bearing_between(TOKYO, LatLonPoint(TOKYO.latitude, TOKYO.longitude - 1))

        assert 269.0 < west < 271.0

    def test_the_same_point_has_no_direction_and_reports_north(self):
        """距離0では向きが定まらない。例外にせず0（北）へ倒す——呼び出し側は「目的地に
        着いている」場合も同じ式で方位を引く。
        """
        assert bearing_between(TOKYO, LatLonPoint(TOKYO.latitude, TOKYO.longitude)) == 0.0

    def test_the_reverse_bearing_is_exactly_opposite_along_a_meridian(self):
        """**大円では、逆方位は一般に正確な±180度にならない**（子午線が収束するため）。
        同じ経度の2点だけは厳密に逆になる。ここを平面の直感で固定すると、東西に長い区間で
        落ちるテストになる。
        """
        north = LatLonPoint(TOKYO.latitude + 1, TOKYO.longitude)

        assert bearing_between(TOKYO, north) == 0.0
        assert bearing_between(north, TOKYO) == 180.0

    def test_the_reverse_bearing_stays_within_a_few_degrees_of_opposite(self):
        """東西に離れた2点では収束のぶんだけずれる。逆向きであること自体は保つ。"""
        there = bearing_between(TOKYO, OSAKA)
        back = bearing_between(OSAKA, TOKYO)

        assert abs((there - back) % 360 - 180) < 5.0


class TestBearingBetweenArray:

    def test_it_agrees_with_the_scalar_version(self):
        targets = [LatLonPoint(35.0, 139.0), LatLonPoint(36.5, 140.5), LatLonPoint(34.0, 138.0)]
        expected = [bearing_between(TOKYO, t) for t in targets]

        actual = bearing_between_array(
            TOKYO, np.array([t.latitude for t in targets]), np.array([t.longitude for t in targets])
        )

        assert np.allclose(actual, expected)

    def test_an_empty_input_gives_an_empty_result(self):
        result = bearing_between_array(TOKYO, np.array([]), np.array([]))

        assert result.shape == (0,)


class TestHaversineDistanceKm:
    def test_the_same_point_is_zero_apart(self):
        assert haversine_distance_km(TOKYO, TOKYO) == 0.0

    def test_it_is_symmetric(self):
        assert haversine_distance_km(TOKYO, OSAKA) == haversine_distance_km(OSAKA, TOKYO)

    def test_a_known_distance_is_reproduced(self):
        """東京〜大阪の大円距離は約400km。桁を取り違えると探索の打ち切りが効かなくなる。"""
        assert 390.0 < haversine_distance_km(TOKYO, OSAKA) < 410.0

    def test_one_degree_of_latitude_is_about_the_declared_constant(self):
        """実測とかけ離れていると、空間索引のバケット分割や矩形マージンが的外れになる。"""
        one_degree = haversine_distance_km(TOKYO, LatLonPoint(TOKYO.latitude + 1, TOKYO.longitude))

        assert abs(one_degree - KM_PER_DEGREE_LATITUDE) < 1.0


class TestHaversineDistanceKmArray:

    def test_it_agrees_with_the_scalar_version(self):
        points = [LatLonPoint(35.0, 139.0), LatLonPoint(36.5, 140.5), OSAKA]
        expected = [haversine_distance_km(p, TOKYO) for p in points]

        actual = haversine_distance_km_array(
            np.array([p.latitude for p in points]), np.array([p.longitude for p in points]), TOKYO
        )

        assert np.allclose(actual, expected)

    def test_the_target_itself_is_zero_and_not_nan(self):
        """同一点では丸め誤差で平方根の中身がわずかに負になりうる。そのままだとNaNが出て、
        A*の優先度比較が静かに壊れる。
        """
        result = haversine_distance_km_array(
            np.array([TOKYO.latitude]), np.array([TOKYO.longitude]), TOKYO
        )

        assert not np.isnan(result).any()
        assert result[0] == 0.0

    def test_an_empty_input_gives_an_empty_result(self):
        result = haversine_distance_km_array(np.array([]), np.array([]), TOKYO)

        assert result.shape == (0,)


class TestLatLon:

    def test_a_different_shape_of_input_gives_the_same_answer(self):
        as_model = Coordinates(latitude=TOKYO.latitude, longitude=TOKYO.longitude)

        assert haversine_distance_km(as_model, OSAKA) == haversine_distance_km(TOKYO, OSAKA)
        assert bearing_between(as_model, OSAKA) == bearing_between(TOKYO, OSAKA)



def test_the_compass_has_a_label_for_every_sector():
    """区分の数とラベルの数がずれると、索引が別の方位を指す。"""
    assert len(COMPASS_LABELS) == 8
    assert len(set(COMPASS_LABELS)) == 8
    assert {compass_label(deg) for deg in range(0, 360)} == set(COMPASS_LABELS)


def test_the_north_sector_is_centred_on_zero():
    """北だけは区分が0度をまたぐ。片側だけで判定すると、真北の手前が「北西」になる。"""
    assert compass_label(-22) == "北"
    assert compass_label(22) == "北"
