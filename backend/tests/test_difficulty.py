from app.domain.difficulty import (
    accident_difficulty,
    composite_difficulty,
    distance_weighted_difficulty,
    evaluate_axis_difficulties,
    gradient_difficulty,
    road_difficulty,
    stop_difficulty,
    car_stress_difficulty,
    wind_difficulty,
)
from app.domain.night import night_difficulty


def test_gradient_difficulty_easy_flat_road():
    assert gradient_difficulty(0.0) == 0.0


def test_gradient_difficulty_moderate_climb():
    assert gradient_difficulty(3.0) == 25.0


def test_gradient_difficulty_hard_climb():
    assert gradient_difficulty(9.0) == 75.0


def test_gradient_difficulty_caps_at_100_for_steep_climbs():
    assert gradient_difficulty(20.0) == 100.0


def test_gradient_difficulty_treats_descent_same_as_climb():
    # abs()で評価するため、下りも同じ勾配なら同じ難易度になる
    assert gradient_difficulty(-6.0) == gradient_difficulty(6.0)


def test_gradient_difficulty_none_passthrough():
    assert gradient_difficulty(None) is None


def test_wind_difficulty_tailwind_is_zero():
    assert wind_difficulty(-3.0) == 0.0


def test_wind_difficulty_no_wind_is_zero():
    assert wind_difficulty(0.0) == 0.0


def test_wind_difficulty_strong_headwind_caps_at_100():
    assert wind_difficulty(10.0) == 100.0


def test_wind_difficulty_moderate_headwind_is_between():
    assert 0.0 < wind_difficulty(4.0) < 100.0


def test_road_difficulty_good_surface_is_easy():
    assert road_difficulty(True) == 0.0


def test_road_difficulty_bad_surface_is_hard():
    assert road_difficulty(False) > 0.0


def test_road_difficulty_none_passthrough():
    assert road_difficulty(None) is None


def test_stop_difficulty_zero_density_is_easiest():
    assert stop_difficulty(0.0) == 0.0


def test_stop_difficulty_increases_with_density():
    assert stop_difficulty(2.0) == 50.0


def test_stop_difficulty_caps_at_100_for_high_density():
    assert stop_difficulty(10.0) == 100.0


def test_stop_difficulty_none_passthrough():
    assert stop_difficulty(None) is None


def test_stop_difficulty_negative_is_none():
    assert stop_difficulty(-1.0) is None


def test_stop_difficulty_intersection_count_defaults_to_no_contribution():
    assert stop_difficulty(2.0) == stop_difficulty(2.0, None)


def test_stop_difficulty_intersection_count_adds_weighted_contribution():
    # 改善計画T149: タグなし交差点は0.3倍の重みでstop_countへ加算される
    # (2.0 + 2.0*0.3=2.6)/4.0*100 = 65.0
    assert stop_difficulty(2.0, 2.0) == 65.0


def test_stop_difficulty_intersection_count_alone_without_stop_count_is_none():
    # stop_count_per_kmがNoneならintersection_count_per_kmの値に関わらず評価しない
    assert stop_difficulty(None, 5.0) is None


def test_stop_difficulty_negative_intersection_count_is_none():
    assert stop_difficulty(2.0, -1.0) is None


def test_stop_difficulty_combined_still_caps_at_100():
    assert stop_difficulty(4.0, 10.0) == 100.0


def test_composite_difficulty_weighted_average():
    result = composite_difficulty([(0.0, 0.5), (100.0, 0.5)])

    assert result == 50.0


def test_composite_difficulty_excludes_none_and_renormalizes():
    # 2つ目の指標がNoneなので、残り2つ(重み0.5,0.25)だけで再正規化される
    # (0*0.5 + 100*0.25) / (0.5+0.25) = 33.33... -> 33.3
    result = composite_difficulty([(0.0, 0.5), (None, 0.25), (100.0, 0.25)])

    assert result == 33.3


def test_composite_difficulty_all_none_returns_none():
    assert composite_difficulty([(None, 0.5), (None, 0.5)]) is None


def test_distance_weighted_difficulty_weights_by_distance():
    # 1kmのdifficulty=0.0と3kmのdifficulty=100.0 -> (0*1 + 100*3) / 4 = 75.0
    result = distance_weighted_difficulty([(0.0, 1.0), (100.0, 3.0)])

    assert result == 75.0


def test_distance_weighted_difficulty_excludes_none_and_renormalizes():
    # 2番目の区間(distance_km=5.0)はdifficulty欠損のため除外し、残り2区間の距離だけで平均する
    result = distance_weighted_difficulty([(0.0, 1.0), (None, 5.0), (100.0, 1.0)])

    assert result == 50.0


def test_distance_weighted_difficulty_all_none_returns_none():
    assert distance_weighted_difficulty([(None, 1.0), (None, 2.0)]) is None


def test_distance_weighted_difficulty_zero_total_distance_returns_none():
    assert distance_weighted_difficulty([(50.0, 0.0)]) is None


def test_distance_weighted_difficulty_empty_returns_none():
    assert distance_weighted_difficulty([]) is None


def test_car_stress_difficulty_level_1_is_easiest():
    assert car_stress_difficulty(1) == 0.0


def test_car_stress_difficulty_level_5_is_hardest():
    assert car_stress_difficulty(5) == 100.0


def test_car_stress_difficulty_is_linear_between_min_and_max():
    # (3-1)/(5-1)*100 = 50.0
    assert car_stress_difficulty(3) == 50.0


def test_car_stress_difficulty_none_passthrough():
    assert car_stress_difficulty(None) is None


def test_accident_difficulty_zero_density_is_easiest():
    assert accident_difficulty(0.0) == 0.0


def test_accident_difficulty_increases_with_density():
    assert accident_difficulty(0.25) == 50.0


def test_accident_difficulty_caps_at_100_for_high_density():
    assert accident_difficulty(10.0) == 100.0


def test_accident_difficulty_none_passthrough():
    assert accident_difficulty(None) is None


def test_accident_difficulty_negative_is_none():
    assert accident_difficulty(-1.0) is None


def test_evaluate_axis_difficulties_returns_all_seven_axes_and_composite():
    # 改善計画T221 Stage B: 材料値の辞書＋axis_idキーの重み辞書を渡す形
    # （domain/axis_definitions.py: AXIS_DEFINITIONS参照）。各軸のdifficultyは
    # 既存のスカラーラッパ関数と一致する（同じ軸定義を参照するため）。
    weights = {axis_id: 1.0 for axis_id in
               ("gradient", "wind", "surface_q", "stop_density", "car_stress", "accident", "night")}
    result = evaluate_axis_difficulties(
        {
            "gradient_percent": 6.0,
            "wind_penalty": 4.0,
            "surface_good": True,
            "stop_count_per_km": 2.0,
            "intersection_count_per_km": 1.0,
            "car_stress_level": 2,
            "accident_count_per_km_year": 0.25,
            "no_lit": False,
            "has_tunnel": False,
        },
        weights,
    )

    assert result.axes["gradient"] == gradient_difficulty(6.0)
    assert result.axes["wind"] == wind_difficulty(4.0)
    assert result.axes["surface_q"] == road_difficulty(True)
    assert result.axes["stop_density"] == stop_difficulty(2.0, 1.0)
    assert result.axes["car_stress"] == car_stress_difficulty(2)
    assert result.axes["accident"] == accident_difficulty(0.25)
    assert result.axes["night"] == night_difficulty({"lit": "yes"})
    assert result.composite is not None


def test_evaluate_axis_difficulties_all_none_inputs_yield_none_composite():
    weights = {axis_id: 1.0 for axis_id in
               ("gradient", "wind", "surface_q", "stop_density", "car_stress", "accident", "night")}
    result = evaluate_axis_difficulties({}, weights)

    assert all(value is None for value in result.axes.values())
    assert set(result.axes.keys()) == set(weights.keys())
    assert result.composite is None
