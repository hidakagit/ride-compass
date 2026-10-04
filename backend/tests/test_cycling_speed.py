"""`domain/cycling_speed.py`——平地・無風の巡航速度から出力を逆算し、勾配・風・路面から区間ごとの速度と走行時間を解く走行モデル。

入口は`RiderProfile`・`wheel_power_w`・`SegmentSpeedModel`（`speed_ms`・`travel_seconds`）・`crr_for_surface`。
期待値は走行方程式（公開の物理）と、モデルが約束する性質（平地・無風なら巡航速度に戻る・向かい風で遅くなる・上下限で止まる）から書く。

ここで見ないもの:
- 区間の勾配・路面・停止の待ちを走行モデルへ渡し、所要時間を合成すること → `test_leg_costs.py`
- 風を進行方向の成分と横成分へ分けること → `test_wind.py`
"""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain import cycling_speed
from app.domain.attributes import CategoricalColumn
from app.domain.cycling_speed import RiderProfile, SegmentSpeedModel
from app.domain.tuning import TUNING_VALUES

# 二分法が詰める幅（下限〜上限を12回半分にした幅）より広く、速度の違いとして意味のある差より狭い許容。
SOLVE_TOLERANCE_MS = 0.005


def _kmh(name: str) -> float:
    return cycling_speed.tuning_value(name) / 3.6


def _speed(profile: RiderProfile, grade: float = 0.0, headwind: float = 0.0, crosswind: float = 0.0,
           crr: float | None = None) -> float:
    model = SegmentSpeedModel(profile, np.array([grade]), np.array([profile.crr if crr is None else crr]))
    return float(model.speed_ms(np.array([headwind]), np.array([crosswind]))[0])


def test_the_power_of_a_rider_cruising_at_20kmh_is_that_of_an_easy_ride():
    """CdA 0.32m²・Crr 0.005・総質量80kgで20km/hを保つ出力は、走行方程式で約55W（趣味の自転車のゆっくりした巡航）。"""
    profile = RiderProfile(cruise_speed_kmh=20.0, cda_m2=0.32, crr=0.005, mass_kg=80.0)

    assert cycling_speed.wheel_power_w(profile) == pytest.approx(55.4, abs=0.5)


def test_the_standard_values_follow_the_values_changed_from_the_admin_screen(monkeypatch):
    """標準値は作るたびに読む。管理画面から変えた値が、プロセスを入れ替えずに次の生成から効く。"""
    monkeypatch.setitem(TUNING_VALUES, "speed.cda_m2", 0.5)
    monkeypatch.setitem(TUNING_VALUES, "speed.crr", 0.02)
    monkeypatch.setitem(TUNING_VALUES, "speed.mass_kg", 100.0)

    profile = RiderProfile(cruise_speed_kmh=20.0)

    assert (profile.cda_m2, profile.crr, profile.mass_kg) == (0.5, 0.02, 100.0)


profiles = st.builds(
    RiderProfile,
    cruise_speed_kmh=st.floats(min_value=8.0, max_value=40.0),
    cda_m2=st.floats(min_value=0.2, max_value=0.6),
    crr=st.floats(min_value=0.002, max_value=0.02),
    mass_kg=st.floats(min_value=50.0, max_value=150.0),
)
grades = st.floats(min_value=-0.3, max_value=0.3)
winds = st.floats(min_value=-20.0, max_value=20.0)


@given(profile=profiles)
def test_on_the_flat_without_wind_the_rider_rides_at_the_cruise_speed(profile):
    """出力は平地・無風の巡航速度から逆算したものなので、同じ条件へ戻せば巡航速度で走る。"""
    assert _speed(profile) == pytest.approx(profile.cruise_speed_ms, abs=SOLVE_TOLERANCE_MS)


@given(profile=profiles, grade=grades, headwind=winds, crosswind=winds)
def test_the_speed_stays_between_walking_and_the_descent_limit(profile, grade, headwind, crosswind):
    """急な登りや強い向かい風でも押して歩く速度より遅くならず、急な下りでも上限を超えない（所要時間が発散しない）。"""
    speed = _speed(profile, grade, headwind, crosswind)

    assert _kmh("speed.walking_kmh") - SOLVE_TOLERANCE_MS <= speed <= _kmh("speed.max_descent_kmh") + SOLVE_TOLERANCE_MS


@given(profile=profiles, grade=grades, headwind=winds, stronger=st.floats(min_value=0.0, max_value=10.0), crosswind=winds)
def test_a_stronger_headwind_never_makes_the_rider_faster(profile, grade, headwind, stronger, crosswind):
    assert _speed(profile, grade, headwind + stronger, crosswind) <= _speed(profile, grade, headwind, crosswind)


@given(profile=profiles, grade=grades, headwind=winds, extra=st.floats(min_value=0.0, max_value=0.03))
def test_a_rougher_surface_never_makes_the_rider_faster(profile, grade, headwind, extra):
    assert _speed(profile, grade, headwind, crr=profile.crr + extra) <= _speed(profile, grade, headwind)


RIDER = RiderProfile(cruise_speed_kmh=20.0)


def test_the_same_headwind_takes_a_larger_share_from_a_slower_rider():
    """向かい風5m/sで、巡航20km/hの人は42%、30km/hの人は33%落ちる（向かい風への強さの差は巡航速度の差として式から出る）。"""
    for cruise_kmh, share in ((20.0, 0.42), (30.0, 0.33)):
        rider = RiderProfile(cruise_speed_kmh=cruise_kmh, cda_m2=0.32, crr=0.005, mass_kg=80.0)

        assert 1 - _speed(rider, headwind=5.0) / rider.cruise_speed_ms == pytest.approx(share, abs=0.01)


def test_at_the_same_cruise_speed_a_heavier_rider_climbs_slower():
    """平地では重さのぶん踏む力も増えるが、登りでは重さそのものを持ち上げる。"""
    light = RiderProfile(cruise_speed_kmh=20.0, mass_kg=60.0)
    heavy = RiderProfile(cruise_speed_kmh=20.0, mass_kg=100.0)

    assert _speed(heavy, grade=0.06) < _speed(light, grade=0.06)


def test_a_crosswind_slows_the_rider_less_than_a_headwind_of_the_same_strength():
    """横風は相対風速の大きさにだけ効く。"""
    calm = _speed(RIDER)
    crosswind = _speed(RIDER, crosswind=5.0)
    headwind = _speed(RIDER, headwind=5.0)

    assert headwind < crosswind < calm


def test_the_rider_works_harder_on_a_climb_than_on_the_flat():
    """一定の出力のままだと20km/hの人が5%の登りで押して歩く速度まで落ちる。登りでは出力を増やし、それより速く登る。"""
    speed = _speed(RIDER, grade=0.05)

    assert _kmh("speed.walking_kmh") * 1.5 < speed < RIDER.cruise_speed_ms


def test_the_extra_power_on_a_climb_stops_at_the_upper_limit():
    """上限より先では出力が増えないので、勾配が増えたぶんだけ遅くなる（上限が無ければ登りの速度が下がりきらない）。"""
    ratios = cycling_speed.climb_power_ratio(np.array([-0.1, 0.5]))

    assert ratios.tolist() == [1.0, cycling_speed.tuning_value("speed.max_climb_power_ratio")]


@pytest.mark.parametrize(
    ("grade", "limit"),
    [
        (-0.3, "speed.max_descent_kmh"),  # 急な下りは上限で止まる
        (0.3, "speed.walking_kmh"),  # 急な登りは押して歩く
    ],
)
def test_the_limits_follow_the_values_changed_from_the_admin_screen(monkeypatch, grade, limit):
    """上下限は値をそのまま読み返せないので、頭打ちになる入力を通して、変えた値で止まることを見る。"""
    changed = TUNING_VALUES[limit] * 0.8
    monkeypatch.setitem(TUNING_VALUES, limit, changed)

    assert _speed(RIDER, grade=grade) == pytest.approx(changed / 3.6, abs=SOLVE_TOLERANCE_MS)


def test_the_travel_time_is_the_distance_at_the_solved_speed():
    model = SegmentSpeedModel(RIDER, np.array([0.0]), np.array([RIDER.crr]))

    seconds = model.travel_seconds(np.array([1000.0]), np.zeros(1), np.zeros(1))

    assert seconds[0] == pytest.approx(1000.0 / RIDER.cruise_speed_ms, rel=1e-3)


@pytest.mark.parametrize(
    "call",
    [
        lambda: SegmentSpeedModel(RIDER, np.zeros(3), np.zeros(1)),
        lambda: SegmentSpeedModel(RIDER, np.zeros(3), np.zeros(3)).speed_ms(np.zeros(1), np.zeros(3)),
        lambda: SegmentSpeedModel(RIDER, np.zeros(3), np.zeros(3)).travel_seconds(np.zeros(1), np.zeros(3), np.zeros(3)),
    ],
)
def test_arrays_of_different_lengths_are_refused_instead_of_spread_over_every_segment(call):
    """長さ1の配列はnumpyが全区間へ黙って広げる。1区間の値が全区間に効く前に断る。"""
    with pytest.raises(ValueError):
        call()


def test_the_rolling_resistance_of_a_surface_follows_the_value_changed_from_the_admin_screen(monkeypatch):
    estimate = cycling_speed.SURFACE_ESTIMATES[0]
    monkeypatch.setitem(TUNING_VALUES, estimate.rolling_resistance, 0.0421)

    crr = cycling_speed.crr_for_surface(CategoricalColumn.encode([estimate.key, estimate.key]))

    assert crr.tolist() == [0.0421, 0.0421]


@pytest.mark.parametrize("value", ["no_such_surface", None])
def test_a_segment_without_a_declared_surface_is_refused_instead_of_treated_as_paved(value):
    """舗装へ倒すと、路面の違いが黙って所要時間から消える。"""
    surface = CategoricalColumn.encode([cycling_speed.SURFACE_ESTIMATES[0].key, value])

    with pytest.raises(ValueError):
        cycling_speed.crr_for_surface(surface)
