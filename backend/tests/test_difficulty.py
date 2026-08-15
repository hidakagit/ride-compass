from app.domain.difficulty import (
    composite_difficulty,
    distance_weighted_difficulty,
    gradient_difficulty,
    road_difficulty,
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
