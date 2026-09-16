"""走行モデル（`domain/cycling_speed.py`）のテスト。"""

import numpy as np
import pytest

from app.domain.cycling_speed import (
    RiderProfile,
    speed_ms,
    travel_seconds,
    wheel_power_w,
)
from app.domain.tuning import tuning_value


def _kmh(profile: RiderProfile, grade: float = 0.0, headwind_ms: float = 0.0) -> float:
    return float(speed_ms(profile, np.array([grade]), np.array([headwind_ms]))[0]) * 3.6


def test_flat_still_air_reproduces_the_cruise_speed():
    """平地・無風では入力した巡航速度がそのまま出る（出力の逆算と速度の逆算が整合する）。"""
    for cruise in (15.0, 20.0, 25.0, 30.0):
        assert _kmh(RiderProfile(cruise_speed_kmh=cruise)) == pytest.approx(cruise, abs=0.05)


def test_wheel_power_is_in_a_plausible_range():
    """巡航速度から逆算した出力が、実際の自転車で言われる範囲に入る。"""
    assert wheel_power_w(RiderProfile(cruise_speed_kmh=20.0)) == pytest.approx(55, abs=5)
    assert wheel_power_w(RiderProfile(cruise_speed_kmh=30.0)) == pytest.approx(146, abs=10)


def test_headwind_slows_slower_riders_more():
    """同じ向かい風でも、巡航速度が低い人ほど割合として大きく落ちる。

    「向かい風に強い／弱い」を軸で補正しなくてよい根拠（走行モデルから出る）。
    """
    slow = RiderProfile(cruise_speed_kmh=20.0)
    fast = RiderProfile(cruise_speed_kmh=30.0)
    slow_ratio = _kmh(slow, headwind_ms=5.0) / 20.0
    fast_ratio = _kmh(fast, headwind_ms=5.0) / 30.0
    assert slow_ratio < fast_ratio
    assert slow_ratio == pytest.approx(0.58, abs=0.05)
    assert fast_ratio == pytest.approx(0.67, abs=0.05)


def test_crosswind_also_slows_down():
    """真横からの風でも相対風速が増えるため遅くなる（進行方向成分だけでは過小評価になる）。"""
    profile = RiderProfile(cruise_speed_kmh=20.0)
    still = speed_ms(profile, np.array([0.0]), np.array([0.0]))
    crosswind = speed_ms(profile, np.array([0.0]), np.array([0.0]), crosswind_ms=np.array([5.0]))
    assert crosswind[0] < still[0]


def test_tailwind_is_faster_than_still_air():
    profile = RiderProfile(cruise_speed_kmh=20.0)
    assert _kmh(profile, headwind_ms=-3.0) > _kmh(profile)


def test_climbing_slows_down_and_is_harder_for_slower_riders():
    slow = RiderProfile(cruise_speed_kmh=20.0)
    fast = RiderProfile(cruise_speed_kmh=30.0)
    assert _kmh(slow, grade=0.05) < _kmh(slow)
    assert _kmh(slow, grade=0.05) < _kmh(fast, grade=0.05)


def test_climbing_speed_is_realistic_because_riders_push_harder_uphill():
    """登りでは出力を上げるため、一定出力で計算したときのような「勾配5%で押して歩く速度」に
    ならない（平地20km/hの人で、5%＝時速10km前後・10%＝時速6km前後）。"""
    profile = RiderProfile(cruise_speed_kmh=20.0)
    assert _kmh(profile, grade=0.05) == pytest.approx(10.0, abs=1.5)
    assert _kmh(profile, grade=0.10) == pytest.approx(6.0, abs=1.5)


def test_climb_power_ratio_rises_with_grade_and_is_clamped():
    from app.domain.cycling_speed import climb_power_ratio

    ratios = climb_power_ratio(np.array([-0.05, 0.0, 0.02, 0.05, 0.20]))
    assert ratios[0] == 1.0, "下りでは増やさない"
    assert ratios[1] == 1.0
    assert 1.0 < ratios[2] < ratios[3]
    assert ratios[4] == tuning_value("speed.max_climb_power_ratio"), "急勾配では上限で止まる"


def test_speed_is_clipped_at_both_ends():
    """下りは上限、激坂は押して歩く速度で止まる（入れないと所要時間が発散する）。"""
    profile = RiderProfile(cruise_speed_kmh=20.0)
    assert _kmh(profile, grade=-0.10) == pytest.approx(tuning_value("speed.max_descent_kmh"), abs=0.05)
    assert _kmh(profile, grade=0.20) == pytest.approx(tuning_value("speed.walking_kmh"), abs=0.05)


def test_rough_surface_slows_down():
    """転がり抵抗が大きい区間（未舗装）は遅くなる。"""
    profile = RiderProfile(cruise_speed_kmh=20.0)
    paved = speed_ms(profile, np.array([0.0]), np.array([0.0]), crr=np.array([0.005]))
    gravel = speed_ms(profile, np.array([0.0]), np.array([0.0]), crr=np.array([0.015]))
    assert gravel[0] < paved[0]


def test_travel_seconds_matches_distance_over_speed():
    profile = RiderProfile(cruise_speed_kmh=20.0)
    seconds = travel_seconds(np.array([1000.0]), profile, np.array([0.0]), np.array([0.0]))
    assert seconds[0] == pytest.approx(3600.0 / 20.0, abs=1.0)


def test_speed_is_vectorised_over_segments():
    profile = RiderProfile(cruise_speed_kmh=20.0)
    speeds = speed_ms(profile, np.array([0.0, 0.05, -0.05]), np.array([0.0, 0.0, 0.0]))
    assert speeds.shape == (3,)
    assert speeds[1] < speeds[0] < speeds[2]


def test_stop_seconds_covers_every_counted_kind():
    """停止要因の集計キー（POI_COUNT_KINDS）すべてに秒が定義されている——片方だけ増えると、
    その種別が所要時間へ入らないまま静かに無視される。"""
    from app.domain.traffic import POI_COUNT_KINDS, stop_seconds
    from app.domain.tuning import TUNING_PARAMETERS_BY_ID, stop_seconds_parameter_id

    declared = {stop_seconds_parameter_id(kind) for kind in POI_COUNT_KINDS}
    assert {p for p in TUNING_PARAMETERS_BY_ID if p.startswith("stop.")} == declared
    assert stop_seconds("signal") > stop_seconds("stop") > 0
    assert stop_seconds("crossing") == 0.0, "信号の無い横断歩道は止まらない"
    assert stop_seconds("未知の種別") == 0.0
