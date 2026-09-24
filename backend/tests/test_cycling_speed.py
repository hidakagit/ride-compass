"""`domain/cycling_speed.py`——自転車の走行モデル（巡航速度から出力を逆算し、区間ごとの速度を解く）。

ここで見ないもの:
- 較正値の宣言そのもの（既定・範囲・効き方）と、上書きがプロセス内の値まで届くこと → `test_tuning_overrides.py`
- 所要時間をコスト配列へ合成すること → `test_road_graph_engine.py`

**較正値は宣言の既定に頼らず、テストが与える**（`tuning`フィクスチャ）。走行モデルは較正値を
呼ぶたびに読むので、値を差し替えると次の計算から効く——上下限として効く値は、頭打ちになる入力を
通して観測する。例外は「宣言の標準値で、実際の自転車の範囲に入るか」の節で、期待値の出どころが
コードの外（実際の自転車の出力・登坂速度）にあるため、宣言の既定値（`declared_defaults`）で計算する。
どちらもプロセスで共有する「いま効いている値」は読まない（他のテストが上書きを読み込んでいても
結果が変わらない）。宣言の既定値だけは`domain/tuning.py`から直接読む——この節の検査の対象が
宣言の既定値そのものだから。
"""

import numpy as np
import pytest

from app.domain import cycling_speed
from app.domain.cycling_speed import RiderProfile
from app.domain.tuning import TUNING_PARAMETERS
from tests.bound_fake import bound

TUNING = {
    "speed.cda_m2": 0.4,
    "speed.crr": 0.005,
    "speed.unpaved_crr": 0.012,
    "speed.mass_kg": 80.0,
    "speed.walking_kmh": 5.0,
    "speed.max_descent_kmh": 50.0,
    "speed.climb_power_per_grade": 10.0,
    "speed.max_climb_power_ratio": 1.5,
}
# 二分法が詰める幅（初期区間 5〜50km/h を12回半分にした幅）より少し広く取る。
SOLVE_TOLERANCE_MS = 0.004


def _read_from(monkeypatch, values: dict[str, float]) -> dict[str, float]:
    monkeypatch.setattr(
        cycling_speed, "tuning_value", bound(cycling_speed.tuning_value, lambda param_id: values[param_id])
    )
    return values


@pytest.fixture
def tuning(monkeypatch):
    """走行モデルが読む較正値。テストごとに新しい辞書を渡し、書き換えると次の計算から効く。"""
    return _read_from(monkeypatch, dict(TUNING))


@pytest.fixture
def declared_defaults(monkeypatch):
    """宣言の既定値。プロセスで共有する「いま効いている値」は読まない——他のテストが管理画面の
    上書きを読み込んだあとでも、同じ値で計算する。"""
    return _read_from(monkeypatch, {p.id: p.default for p in TUNING_PARAMETERS})


def _speed(cruise_kmh: float, grade: float = 0.0, headwind: float = 0.0, **kwargs) -> float:
    (value,) = cycling_speed.speed_ms(RiderProfile(cruise_kmh), np.array([grade]), np.array([headwind]), **kwargs)
    return float(value)


# ---- 巡航速度からの逆算 ----


@pytest.mark.parametrize("cruise_kmh", [15.0, 20.0, 30.0])
def test_flat_calm_road_gives_back_the_cruise_speed(tuning, cruise_kmh):
    # 出力は平地・無風の巡航速度から逆算するので、同じ条件へ戻すと巡航速度になる
    assert _speed(cruise_kmh) == pytest.approx(cruise_kmh / 3.6, abs=SOLVE_TOLERANCE_MS)


@pytest.mark.parametrize(
    ("field", "param_id"),
    [("cda_m2", "speed.cda_m2"), ("crr", "speed.crr"), ("mass_kg", "speed.mass_kg")],
)
def test_profile_reads_each_standard_value_when_it_is_made(tuning, field, param_id):
    before = RiderProfile(20.0)
    tuning[param_id] = TUNING[param_id] * 2
    after = RiderProfile(20.0)

    assert getattr(before, field) == TUNING[param_id]
    # 作ったあとに変えた値は、次に作るものから効く（import時に束ねない）
    assert getattr(after, field) == TUNING[param_id] * 2


def test_profile_converts_the_cruise_speed_to_metres_per_second(tuning):
    assert RiderProfile(18.0).cruise_speed_ms == pytest.approx(5.0)


def test_heavier_rider_at_the_same_cruise_speed_is_slower_uphill(tuning):
    light = _speed(20.0, grade=0.04)
    tuning["speed.mass_kg"] = 100.0

    assert _speed(20.0, grade=0.04) < light


# ---- 風・勾配・路面 ----


def test_headwind_slows_and_tailwind_speeds_up(tuning):
    assert _speed(20.0, headwind=5.0) < _speed(20.0) < _speed(20.0, headwind=-5.0)


def test_crosswind_slows_the_rider_less_than_the_same_headwind(tuning):
    # 横風は相対風速の大きさにだけ効き、進行方向の成分としては効かない
    assert _speed(20.0, headwind=6.0) < _speed(20.0, crosswind_ms=np.array([6.0])) < _speed(20.0)


def test_the_same_headwind_takes_a_bigger_share_from_a_slower_rider(tuning):
    def lost_share(cruise_kmh: float) -> float:
        return 1.0 - _speed(cruise_kmh, headwind=5.0) / _speed(cruise_kmh)

    # 「向かい風に弱い」は巡航速度の違いとして式から出る（利用者から体重・出力を取らない）
    assert lost_share(20.0) > lost_share(30.0)


def test_uphill_is_slower_and_downhill_faster(tuning):
    assert _speed(20.0, grade=0.03) < _speed(20.0) < _speed(20.0, grade=-0.03)


@pytest.mark.parametrize(
    ("grade", "ratio"),
    [
        (-0.05, 1.0),  # 下りでは踏む量を減らさない
        (0.0, 1.0),
        (0.02, 1.2),  # 勾配に比例して増える
        (0.05, 1.5),  # ちょうど上限
        (0.10, 1.5),  # 上限で止まる
    ],
)
def test_climbing_raises_the_power_in_proportion_to_grade_up_to_a_limit(tuning, grade, ratio):
    assert cycling_speed.climb_power_ratio(np.array([grade]))[0] == pytest.approx(ratio)


def test_the_extra_climbing_power_makes_climbs_faster(tuning):
    tuning["speed.climb_power_per_grade"] = 0.0
    constant_power = _speed(20.0, grade=0.03)
    tuning["speed.climb_power_per_grade"] = 10.0

    assert _speed(20.0, grade=0.03) > constant_power


PAVED = TUNING["speed.crr"]
UNPAVED = TUNING["speed.unpaved_crr"]


def test_unknown_surface_counts_as_paved_and_only_bad_surface_as_unpaved(tuning):
    crr = cycling_speed.crr_for_surface(np.array([1.0, 0.0, np.nan]), 3)

    assert crr.tolist() == [PAVED, UNPAVED, PAVED]


def test_without_a_surface_material_every_segment_is_paved(tuning):
    assert cycling_speed.crr_for_surface(None, 2).tolist() == [PAVED, PAVED]


def test_unpaved_segments_are_slower(tuning):
    paved, unpaved = cycling_speed.speed_ms(
        RiderProfile(20.0), np.zeros(2), np.zeros(2), crr=np.array([PAVED, UNPAVED])
    )

    assert unpaved < paved


def test_rolling_resistance_defaults_to_the_paved_value(tuning):
    assert _speed(20.0, grade=0.02) == _speed(20.0, grade=0.02, crr=np.array([PAVED]))
    assert _speed(20.0, grade=0.02) != _speed(20.0, grade=0.02, crr=np.array([UNPAVED]))


# ---- 速度の上下限（較正値で頭打ちになる） ----


def test_a_climb_too_steep_to_ride_bottoms_out_at_walking_speed(tuning):
    assert _speed(20.0, grade=0.30) == pytest.approx(5.0 / 3.6, abs=SOLVE_TOLERANCE_MS)
    tuning["speed.walking_kmh"] = 6.0

    assert _speed(20.0, grade=0.30) == pytest.approx(6.0 / 3.6, abs=SOLVE_TOLERANCE_MS)


def test_a_steep_descent_tops_out_at_the_descent_limit(tuning):
    assert _speed(20.0, grade=-0.30) == pytest.approx(50.0 / 3.6, abs=SOLVE_TOLERANCE_MS)
    tuning["speed.max_descent_kmh"] = 40.0

    assert _speed(20.0, grade=-0.30) == pytest.approx(40.0 / 3.6, abs=SOLVE_TOLERANCE_MS)


# ---- 所要時間 ----


def test_travel_time_is_distance_over_speed(tuning):
    seconds = cycling_speed.travel_seconds(np.array([1000.0, 2000.0]), RiderProfile(18.0), np.zeros(2), np.zeros(2))

    # 巡航18km/h＝5m/s。呼び出し側（コスト配列）と同じ倍精度で返す
    assert seconds.dtype == np.float64
    assert seconds.tolist() == pytest.approx([200.0, 400.0], rel=1e-3)


# ---- 宣言の標準値で、実際の自転車の範囲に入るか ----


def test_the_power_lands_in_the_range_real_cyclists_produce(declared_defaults):
    """単位の取り違え（CdAをcm²で置く等）はここでしか捕まらない——比較だけの検査は
    桁が揃ってずれても通る。
    """
    assert cycling_speed.wheel_power_w(RiderProfile(cruise_speed_kmh=20.0)) == pytest.approx(55, abs=5)
    assert cycling_speed.wheel_power_w(RiderProfile(cruise_speed_kmh=30.0)) == pytest.approx(146, abs=10)


def test_climbing_speeds_stay_realistic_because_riders_push_harder(declared_defaults):
    """踏む量を増やすモデルでは、5%で時速10km前後・10%で時速6km前後に収まる。"""
    profile = RiderProfile(cruise_speed_kmh=20.0)

    assert _speed_of(profile, grade=0.05) * 3.6 == pytest.approx(10.0, abs=1.5)
    assert _speed_of(profile, grade=0.10) * 3.6 == pytest.approx(6.0, abs=1.5)


def _speed_of(profile: RiderProfile, grade: float) -> float:
    return float(cycling_speed.speed_ms(profile, np.array([grade]), np.array([0.0]))[0])


# ---- 区間の配列の長さ ----


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("headwind_ms", {"headwind_ms": np.zeros(1)}),
        ("crosswind_ms", {"crosswind_ms": np.zeros(1)}),
        ("crr", {"crr": np.zeros(1)}),
    ],
)
def test_segment_arrays_of_a_different_length_are_rejected(tuning, name, kwargs):
    # 長さ1の配列はブロードキャストで全区間へ黙って広がる（1区間の風が全区間に効く）
    arguments = {"headwind_ms": np.zeros(3), **kwargs}

    with pytest.raises(ValueError, match=name):
        cycling_speed.speed_ms(RiderProfile(20.0), np.zeros(3), **arguments)


def test_surface_values_of_a_different_length_are_rejected(tuning):
    with pytest.raises(ValueError):
        cycling_speed.crr_for_surface(np.array([1.0]), 3)


def test_distances_of_a_different_length_are_rejected(tuning):
    with pytest.raises(ValueError):
        cycling_speed.travel_seconds(np.array([100.0]), RiderProfile(20.0), np.zeros(3), np.zeros(3))
