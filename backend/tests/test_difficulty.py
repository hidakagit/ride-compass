from app.domain.difficulty import (
    accident_difficulty,
    bicycle_infra_difficulty,
    composite_difficulty,
    distance_weighted_difficulty,
    evaluate_axis_difficulties,
    gradient_difficulty,
    intersection_difficulty,
    road_difficulty,
    stop_difficulty,
    traffic_stress_difficulty,
    wind_difficulty,
)


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


def test_traffic_stress_difficulty_level_1_is_easiest():
    assert traffic_stress_difficulty(1) == 0.0


def test_traffic_stress_difficulty_level_4_is_hardest():
    assert traffic_stress_difficulty(4) == 100.0


def test_traffic_stress_difficulty_is_linear_between_min_and_max():
    # (2.5-1)/(4-1)*100 = 50.0
    assert traffic_stress_difficulty(2.5) == 50.0


def test_traffic_stress_difficulty_none_passthrough():
    assert traffic_stress_difficulty(None) is None


def test_bicycle_infra_difficulty_separated_is_easiest():
    assert bicycle_infra_difficulty("separated") == 0.0


def test_bicycle_infra_difficulty_prohibited_is_hardest():
    assert bicycle_infra_difficulty("prohibited") == 100.0


def test_bicycle_infra_difficulty_orders_classes_by_dedication():
    assert (
        bicycle_infra_difficulty("separated")
        < bicycle_infra_difficulty("lane")
        < bicycle_infra_difficulty("shared_busway")
        < bicycle_infra_difficulty("shared_pedestrian")
        < bicycle_infra_difficulty("roadway")
        < bicycle_infra_difficulty("prohibited")
    )


def test_bicycle_infra_difficulty_none_passthrough():
    assert bicycle_infra_difficulty(None) is None


def test_bicycle_infra_difficulty_unknown_class_is_none():
    # unknown（highway自体が不明）は評価しない
    assert bicycle_infra_difficulty("unknown") is None


def test_intersection_difficulty_zero_density_is_easiest():
    assert intersection_difficulty(0.0) == 0.0


def test_intersection_difficulty_increases_with_density():
    assert intersection_difficulty(1.0) == 50.0


def test_intersection_difficulty_caps_at_100_for_high_density():
    assert intersection_difficulty(10.0) == 100.0


def test_intersection_difficulty_none_passthrough():
    assert intersection_difficulty(None) is None


def test_intersection_difficulty_negative_is_none():
    assert intersection_difficulty(-1.0) is None


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


def test_evaluate_axis_difficulties_returns_all_eight_axes_and_composite():
    result = evaluate_axis_difficulties(
        6.0, 4.0, True, 2.0, 2, "lane", 1.0, 0.25,
        elevation_weight=1.0, wind_weight=1.0, road_weight=1.0, stop_weight=1.0,
        traffic_weight=1.0, infra_weight=1.0, intersection_weight=1.0, accident_weight=1.0,
    )

    assert result.elevation == gradient_difficulty(6.0)
    assert result.wind == wind_difficulty(4.0)
    assert result.road == road_difficulty(True)
    assert result.stop == stop_difficulty(2.0)
    assert result.traffic == traffic_stress_difficulty(2)
    assert result.infra == bicycle_infra_difficulty("lane")
    assert result.intersection == intersection_difficulty(1.0)
    assert result.accident == accident_difficulty(0.25)
    assert result.composite is not None


def test_evaluate_axis_difficulties_all_none_inputs_yield_none_composite():
    result = evaluate_axis_difficulties(
        None, None, None, None, None, None, None, None,
        elevation_weight=1.0, wind_weight=1.0, road_weight=1.0, stop_weight=1.0,
        traffic_weight=1.0, infra_weight=1.0, intersection_weight=1.0, accident_weight=1.0,
    )

    assert result == (None, None, None, None, None, None, None, None, None)
