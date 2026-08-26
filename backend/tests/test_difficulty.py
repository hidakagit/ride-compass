from app.domain.axis_definitions import AXIS_DEFINITIONS, evaluate_axis_scalar
from app.domain.difficulty import (
    composite_difficulty,
    distance_weighted_difficulty,
    evaluate_axis_difficulties,
)

# 改善計画T320: 以前はgradient_difficulty/wind_difficulty/road_difficulty/stop_difficulty/
# accident_difficulty（domain/difficulty.py）・night_difficulty（domain/night.py）という
# 軸ごとのスカラー版互換ラッパ経由でテストしていたが、これらは実行時経路のどこからも
# 呼ばれておらずテストのみの消費者だったため削除した（両エンジンとも
# evaluate_axis_difficulties/compute_edge_axis_scoresが材料辞書を直接渡す経路を使う）。
# 削除された関数が担っていた「軸定義（breakpoints等）どおりに変換される」という検証自体は
# 引き続き価値があるため、実際に使われている評価関数evaluate_axis_scalarを軸定義付きで
# 直接呼ぶ形へ書き換えた。


def test_gradient_axis_easy_flat_road():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["gradient"], {"gradient_percent": 0.0}) == 0.0


def test_gradient_axis_moderate_climb():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["gradient"], {"gradient_percent": 3.0}) == 25.0


def test_gradient_axis_hard_climb():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["gradient"], {"gradient_percent": 9.0}) == 75.0


def test_gradient_axis_caps_at_100_for_steep_climbs():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["gradient"], {"gradient_percent": 20.0}) == 100.0


def test_gradient_axis_treats_descent_same_as_climb():
    # preprocess="abs"で評価するため、下りも同じ勾配なら同じ難易度になる
    definition = AXIS_DEFINITIONS["gradient"]
    assert evaluate_axis_scalar(definition, {"gradient_percent": -6.0}) == evaluate_axis_scalar(
        definition, {"gradient_percent": 6.0}
    )


def test_gradient_axis_missing_material_is_none():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["gradient"], {}) is None


def test_wind_axis_tailwind_is_zero():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["wind"], {"wind_penalty": -3.0}) == 0.0


def test_wind_axis_no_wind_is_zero():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["wind"], {"wind_penalty": 0.0}) == 0.0


def test_wind_axis_strong_headwind_caps_at_100():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["wind"], {"wind_penalty": 10.0}) == 100.0


def test_wind_axis_moderate_headwind_is_between():
    value = evaluate_axis_scalar(AXIS_DEFINITIONS["wind"], {"wind_penalty": 4.0})
    assert value is not None
    assert 0.0 < value < 100.0


def test_surface_q_axis_good_surface_is_easy():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["surface_q"], {"surface_good": True}) == 0.0


def test_surface_q_axis_bad_surface_is_hard():
    value = evaluate_axis_scalar(AXIS_DEFINITIONS["surface_q"], {"surface_good": False})
    assert value is not None
    assert value > 0.0


def test_surface_q_axis_missing_material_is_none():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["surface_q"], {}) is None


def test_stop_density_axis_zero_density_is_easiest():
    assert (
        evaluate_axis_scalar(AXIS_DEFINITIONS["stop_density"], {"stop_count_per_km": 0.0}) == 0.0
    )


def test_stop_density_axis_increases_with_density():
    assert (
        evaluate_axis_scalar(AXIS_DEFINITIONS["stop_density"], {"stop_count_per_km": 2.0}) == 50.0
    )


def test_stop_density_axis_caps_at_100_for_high_density():
    assert (
        evaluate_axis_scalar(AXIS_DEFINITIONS["stop_density"], {"stop_count_per_km": 10.0}) == 100.0
    )


def test_stop_density_axis_missing_stop_count_is_none():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["stop_density"], {}) is None


def test_stop_density_axis_intersection_count_defaults_to_no_contribution():
    definition = AXIS_DEFINITIONS["stop_density"]
    with_intersection_absent = evaluate_axis_scalar(definition, {"stop_count_per_km": 2.0})
    with_intersection_none = evaluate_axis_scalar(
        definition, {"stop_count_per_km": 2.0, "intersection_count_per_km": None}
    )
    assert with_intersection_absent == with_intersection_none


def test_stop_density_axis_intersection_count_adds_weighted_contribution():
    # 改善計画T149: タグなし交差点は0.3倍の重みでstop_countへ加算される
    # (2.0 + 2.0*0.3=2.6)/4.0*100 = 65.0
    value = evaluate_axis_scalar(
        AXIS_DEFINITIONS["stop_density"],
        {"stop_count_per_km": 2.0, "intersection_count_per_km": 2.0},
    )
    assert value == 65.0


def test_stop_density_axis_combined_still_caps_at_100():
    value = evaluate_axis_scalar(
        AXIS_DEFINITIONS["stop_density"],
        {"stop_count_per_km": 4.0, "intersection_count_per_km": 10.0},
    )
    assert value == 100.0


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


def test_accident_axis_zero_density_is_easiest():
    assert (
        evaluate_axis_scalar(AXIS_DEFINITIONS["accident"], {"accident_count_per_km_year": 0.0}) == 0.0
    )


def test_accident_axis_increases_with_density():
    value = evaluate_axis_scalar(AXIS_DEFINITIONS["accident"], {"accident_count_per_km_year": 0.25})
    assert value == 50.0


def test_accident_axis_caps_at_100_for_high_density():
    value = evaluate_axis_scalar(AXIS_DEFINITIONS["accident"], {"accident_count_per_km_year": 10.0})
    assert value == 100.0


def test_accident_axis_missing_material_is_none():
    assert evaluate_axis_scalar(AXIS_DEFINITIONS["accident"], {}) is None


def test_evaluate_axis_difficulties_returns_all_seven_axes_and_composite():
    # 改善計画T221 Stage B: 材料値の辞書＋axis_idキーの重み辞書を渡す形
    # （domain/axis_definitions.py: AXIS_DEFINITIONS参照）。
    weights = {axis_id: 1.0 for axis_id in
               ("gradient", "wind", "surface_q", "stop_density", "car_stress", "accident", "night")}
    materials = {
        "gradient_percent": 6.0,
        "wind_penalty": 4.0,
        "surface_good": True,
        "stop_count_per_km": 2.0,
        "intersection_count_per_km": 1.0,
        # 改善計画T292: car_stressは内部軸5つ+公開軸1つの階層構造になったため、
        # 単一のcar_stress_level材料ではなくhighwayを渡す（highway基準値=2、
        # 他の補正材料[bicycle_infra/maxspeed_kmh/lanes_count/is_designated/
        # motor_vehicle_no]は省略=補正なしのため、breakpoints(1,0)-(5,100)で
        # (2-1)/4*100=25.0になる）。
        "highway": "residential",
        "accident_count_per_km_year": 0.25,
        "no_lit": False,
        "has_tunnel": False,
    }
    result = evaluate_axis_difficulties(materials, weights)

    assert result.axes["gradient"] == evaluate_axis_scalar(
        AXIS_DEFINITIONS["gradient"], materials
    )
    assert result.axes["wind"] == evaluate_axis_scalar(AXIS_DEFINITIONS["wind"], materials)
    assert result.axes["surface_q"] == evaluate_axis_scalar(AXIS_DEFINITIONS["surface_q"], materials)
    assert result.axes["stop_density"] == evaluate_axis_scalar(
        AXIS_DEFINITIONS["stop_density"], materials
    )
    assert result.axes["car_stress"] == 25.0
    assert result.axes["accident"] == evaluate_axis_scalar(AXIS_DEFINITIONS["accident"], materials)
    assert result.axes["night"] == evaluate_axis_scalar(AXIS_DEFINITIONS["night"], materials)
    assert result.composite is not None


def test_evaluate_axis_difficulties_all_none_inputs_yield_none_composite():
    # 改善計画T347: bicycle_infra_qualityが公開軸として加わった。
    weights = {axis_id: 1.0 for axis_id in
               ("gradient", "wind", "surface_q", "stop_density", "car_stress", "accident", "night",
                "bicycle_infra_quality")}
    result = evaluate_axis_difficulties({}, weights)

    assert all(value is None for value in result.axes.values())
    assert set(result.axes.keys()) == set(weights.keys())
    assert result.composite is None
