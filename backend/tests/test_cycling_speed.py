"""`domain/cycling_speed.py`——所要時間の物理。走行方程式を速度について解く。

較正値の宣言そのものは`domain/tuning.py`側で、変更が効く経路は
`test_tuning_overrides.py`が持つ。**ここへ数字を書き写さない**——書き写すと、
変えた値が効いているか誰も見なくなる。
"""

import numpy as np
import pytest

from app.domain.cycling_speed import (
    RiderProfile,
    climb_power_ratio,
    crr_for_surface,
    speed_ms,
    travel_seconds,
    wheel_power_w,
)
from app.domain.tuning import tuning_value

FLAT = np.zeros(1)
NO_WIND = np.zeros(1)


def _profile(cruise_kmh: float = 20.0) -> RiderProfile:
    return RiderProfile(cruise_speed_kmh=cruise_kmh)


def _speed(profile: RiderProfile, grade: float = 0.0, headwind: float = 0.0, **kwargs) -> float:
    return float(speed_ms(profile, np.array([grade]), np.array([headwind]), **kwargs)[0])


class TestCrrForSurface:
    def test_a_road_known_to_be_rough_rolls_worse(self):
        result = crr_for_surface(np.array([0.0]), 1)

        assert result[0] == tuning_value("speed.unpaved_crr")

    def test_a_road_known_to_be_paved_rolls_well(self):
        result = crr_for_surface(np.array([1.0]), 1)

        assert result[0] == tuning_value("speed.crr")

    def test_an_unknown_surface_is_treated_as_paved(self):
        """悪路側へ倒すと、タグの付いていない道が一律に遅く見積もられる。"""
        result = crr_for_surface(np.array([np.nan]), 1)

        assert result[0] == tuning_value("speed.crr")

    def test_no_surface_material_at_all_is_treated_as_paved(self):
        result = crr_for_surface(None, 3)

        assert result.tolist() == [tuning_value("speed.crr")] * 3

    def test_it_returns_one_value_per_segment(self):
        assert crr_for_surface(np.array([0.0, 1.0, np.nan]), 3).shape == (3,)


class TestRiderProfile:
    def test_the_standard_values_come_from_the_declaration(self):
        profile = _profile()

        assert profile.cda_m2 == tuning_value("speed.cda_m2")
        assert profile.crr == tuning_value("speed.crr")
        assert profile.mass_kg == tuning_value("speed.mass_kg")

    def test_the_cruise_speed_is_converted_to_metres_per_second(self):
        assert _profile(36.0).cruise_speed_ms == 10.0


class TestWheelPowerW:
    def test_a_faster_cruiser_needs_more_power(self):
        assert wheel_power_w(_profile(30.0)) > wheel_power_w(_profile(20.0))

    def test_the_power_lands_in_the_range_real_cyclists_produce(self):
        """単位の取り違え（CdAをcm²で置く等）はここでしか捕まらない——比較だけの検査は
        桁が揃ってずれても通る。
        """
        assert wheel_power_w(_profile(20.0)) == pytest.approx(55, abs=5)
        assert wheel_power_w(_profile(30.0)) == pytest.approx(146, abs=10)

    def test_power_grows_faster_than_speed(self):
        """線形に伸びると読むと、速い人の向かい風耐性を過小に見積もる。"""
        slow = wheel_power_w(_profile(15.0))
        fast = wheel_power_w(_profile(30.0))

        assert fast > 2 * slow


class TestClimbPowerRatio:
    def test_flat_and_downhill_use_the_baseline_power(self):
        assert climb_power_ratio(np.array([0.0, -0.05, -0.2])).tolist() == [1.0, 1.0, 1.0]

    def test_a_steeper_climb_asks_for_more_power(self):
        ratios = climb_power_ratio(np.array([0.01, 0.03, 0.05]))

        assert ratios[0] < ratios[1] < ratios[2]

    def test_the_increase_stops_at_the_declared_ceiling(self):
        assert climb_power_ratio(np.array([1.0]))[0] == tuning_value("speed.max_climb_power_ratio")


class TestSpeedMs:
    def test_flat_and_windless_reproduces_the_cruise_speed(self):
        """ここがずれると、利用者が入力した速度と表示される所要時間が食い違う。"""
        profile = _profile(24.0)

        assert abs(_speed(profile) - profile.cruise_speed_ms) < 0.01

    def test_a_headwind_slows_the_rider_and_a_tailwind_speeds_them_up(self):
        profile = _profile()

        assert _speed(profile, headwind=5.0) < _speed(profile) < _speed(profile, headwind=-5.0)

    def test_a_climb_slows_the_rider_and_a_descent_speeds_them_up(self):
        profile = _profile()

        assert _speed(profile, grade=0.05) < _speed(profile) < _speed(profile, grade=-0.05)

    def test_a_climb_costs_a_slower_rider_more(self):
        assert _speed(_profile(20.0), grade=0.05) < _speed(_profile(30.0), grade=0.05)

    def test_climbing_speeds_stay_realistic_because_riders_push_harder(self):
        """踏む量を増やすモデルでは、5%で時速10km前後・10%で時速6km前後に収まる。"""
        profile = _profile(20.0)

        assert _speed(profile, grade=0.05) * 3.6 == pytest.approx(10.0, abs=1.5)
        assert _speed(profile, grade=0.10) * 3.6 == pytest.approx(6.0, abs=1.5)

    def test_a_crosswind_costs_less_than_the_same_headwind(self):
        """横風は合成風速としてのみ効く。向かい風と同じ扱いにすると、横風の区間が
        不当に遅くなる。
        """
        profile = _profile()
        cross = _speed(profile, crosswind_ms=np.array([5.0]))
        head = _speed(profile, headwind=5.0)

        assert head < cross < _speed(profile)

    def test_a_rough_surface_slows_the_rider(self):
        profile = _profile()
        rough = _speed(profile, crr=np.array([tuning_value("speed.unpaved_crr")]))

        assert rough < _speed(profile)

    def test_a_slower_cruiser_loses_a_bigger_share_to_the_same_headwind(self):
        def lost_share(cruise_kmh: float) -> float:
            profile = _profile(cruise_kmh)
            return 1.0 - _speed(profile, headwind=5.0) / _speed(profile)

        assert lost_share(20.0) > lost_share(30.0)

    def test_the_result_stays_inside_the_declared_limits(self):
        """極端な勾配でも所要時間が0や無限にならない。"""
        profile = _profile()
        grades = np.array([-0.5, -0.1, 0.0, 0.1, 0.5])

        speeds = speed_ms(profile, grades, np.zeros(5))

        assert speeds.min() >= tuning_value("speed.walking_kmh") / 3.6 - 0.01
        assert speeds.max() <= tuning_value("speed.max_descent_kmh") / 3.6 + 0.01

    def test_it_returns_one_speed_per_segment(self):
        speeds = speed_ms(_profile(), np.zeros(4), np.zeros(4))

        assert speeds.shape == (4,)

    def test_the_result_is_float64_for_the_callers(self):
        assert speed_ms(_profile(), FLAT, NO_WIND).dtype == np.float64


class TestTravelSeconds:
    def test_time_is_distance_over_speed(self):
        profile = _profile()
        speed = speed_ms(profile, FLAT, NO_WIND)

        seconds = travel_seconds(np.array([1000.0]), profile, FLAT, NO_WIND)

        assert np.allclose(seconds, 1000.0 / speed)

    def test_a_longer_segment_takes_longer(self):
        profile = _profile()

        seconds = travel_seconds(np.array([100.0, 200.0]), profile, np.zeros(2), np.zeros(2))

        assert seconds[1] > seconds[0]

    def test_a_zero_length_segment_takes_no_time(self):
        assert travel_seconds(np.array([0.0]), _profile(), FLAT, NO_WIND)[0] == 0.0
