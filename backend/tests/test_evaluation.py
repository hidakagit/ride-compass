import inspect

import pytest

from app.domain import evaluation, safety, traffic
from app.domain.attributes import ElevationAttribute
from app.domain.evaluation import (
    RoutePreference,
    compute_cost_from_axis_scores,
    compute_edge_axis_scores,
    compute_edge_cost,
    compute_wind_penalty,
    is_edge_allowed,
    preference_to_axis_weights,
)
from app.domain.graph import DirectedEdge
from app.domain.weather import WeatherConditions


def _edge(**overrides) -> DirectedEdge:
    defaults = dict(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-2",
        geometry=[[35.700, 139.700], [35.701, 139.700]],
        distance_m=100.0,
        osm_way_id=1,
        highway="residential",
    )
    defaults.update(overrides)
    return DirectedEdge(**defaults)


def _elevation_attr(average_grade: float | None) -> ElevationAttribute:
    return ElevationAttribute(edge_id="edge-1", average_grade=average_grade, data_source="test", calculated_at="t")


def test_is_edge_allowed_excludes_motorway():
    assert is_edge_allowed(_edge(highway="motorway")) is False
    assert is_edge_allowed(_edge(highway="motorway_link")) is False


def test_is_edge_allowed_excludes_trunk():
    # 改善計画T140: trunk/trunk_linkの除外は既存動作（挙動変更なし）。以前は単体テストが
    # 無く、motorwayのみ回帰確認されていた抜けを埋める。
    assert is_edge_allowed(_edge(highway="trunk")) is False
    assert is_edge_allowed(_edge(highway="trunk_link")) is False


def test_is_edge_allowed_allows_residential():
    assert is_edge_allowed(_edge(highway="residential")) is True


def test_is_edge_allowed_allows_unknown_highway():
    assert is_edge_allowed(_edge(highway=None)) is True


def test_is_edge_allowed_excludes_bicycle_no():
    # 改善計画T100: bicycle=noのHard Constraint化。highway自体は許可種別でも除外する。
    assert is_edge_allowed(_edge(highway="residential"), {"bicycle": "no"}) is False


def test_is_edge_allowed_bicycle_no_is_case_and_whitespace_insensitive():
    assert is_edge_allowed(_edge(highway="residential"), {"bicycle": " NO "}) is False


def test_is_edge_allowed_allows_bicycle_yes():
    assert is_edge_allowed(_edge(highway="residential"), {"bicycle": "yes"}) is True


def test_is_edge_allowed_allows_missing_way_tags():
    # way_tags=None（未取得）は判断材料が無いため除外しない（highway不明時と同じ方針）。
    assert is_edge_allowed(_edge(highway="residential"), None) is True


def test_is_edge_allowed_allows_way_tags_without_bicycle_key():
    assert is_edge_allowed(_edge(highway="residential"), {"lanes": "2"}) is True


def test_is_edge_allowed_hard_filters_override_disables_trunk_exclusion():
    # 改善計画T140: hard_filters引数で名前付きフィルタを個別に無効化できる
    # （T141でレシピJSON化した際の`hard_filters: list[str]`をそのまま渡す想定）。
    custom_filters = frozenset({"no_bicycle", "motorway"})
    assert is_edge_allowed(_edge(highway="trunk"), hard_filters=custom_filters) is True
    assert is_edge_allowed(_edge(highway="motorway"), hard_filters=custom_filters) is False


def test_is_edge_allowed_hard_filters_override_disables_no_bicycle():
    custom_filters = frozenset({"motorway", "trunk"})
    assert is_edge_allowed(_edge(highway="residential"), {"bicycle": "no"}, hard_filters=custom_filters) is True


def test_is_edge_allowed_empty_hard_filters_allows_everything():
    assert is_edge_allowed(_edge(highway="motorway"), {"bicycle": "no"}, hard_filters=frozenset()) is True


def test_compute_edge_cost_excludes_disallowed_edge():
    edge = _edge(highway="motorway")
    result = compute_edge_cost(edge, None, None, RoutePreference())

    assert result.allowed is False
    assert result.cost is None


def test_compute_edge_cost_excludes_bicycle_no_edge():
    # 改善計画T100: way_tags経由でbicycle=noが渡るとcompute_edge_cost全体がHard Constraintで
    # 除外される（is_edge_allowedのテストと同じ判定を、実際の呼び出し経路で確認）。
    edge = _edge(highway="residential")
    result = compute_edge_cost(edge, None, None, RoutePreference(), way_tags={"bicycle": "no"})

    assert result.allowed is False
    assert result.cost is None
    assert result.difficulty is None
    assert result.difficulty is None
    assert result.edge_id == "edge-1"


def _count_car_closeness_calls(monkeypatch) -> "list[int]":
    # car_closeness()はapp.domain.evaluation/traffic/safetyそれぞれが`from ... import
    # car_closeness`で個別に束縛しているため、3箇所すべてにパッチしないと見落としが
    # 起こりうる（precompute側が正しく配線されず各軸内部でフォールバック呼び出しされても、
    # evaluation.py側の1箇所だけを数えていては検出できない）。共有カウンタで合算する。
    counter = [0]

    def make_counting(original):
        def counting(*args, **kwargs):
            counter[0] += 1
            return original(*args, **kwargs)

        return counting

    monkeypatch.setattr(evaluation, "car_closeness", make_counting(evaluation.car_closeness))
    monkeypatch.setattr(traffic, "car_closeness", make_counting(traffic.car_closeness))
    monkeypatch.setattr(safety, "car_closeness", make_counting(safety.car_closeness))
    return counter


def test_compute_edge_cost_calls_car_closeness_once_per_edge(monkeypatch):
    # 「車との近さ」(N2)はcar_stress_level・safety_levelの両方が内部で参照する共通の
    # 土台で、以前は同じ材料タグ・同じレシピに対してcar_closeness()が両者から独立に
    # 毎回呼ばれ、1Edgeにつき2回計算していた（ルート生成の全Edge分の無駄）。
    # compute_edge_cost側で1回だけ計算して両方へ渡すようになったことを、実呼び出し回数で
    # 直接確認する（本物のcar_closeness()へ委譲しつつ呼び出し回数だけ数える）。
    counter = _count_car_closeness_calls(monkeypatch)

    edge = _edge(highway="primary")
    result = compute_edge_cost(edge, None, None, RoutePreference(), way_tags={"lanes": "2"})

    assert result.allowed is True
    assert counter[0] == 1


def test_compute_edge_cost_without_way_tags_does_not_call_car_closeness(monkeypatch):
    # way_tags=Noneの場合はcar_stress/safetyとも評価しない（既存仕様）ため、
    # car_closeness()自体を呼ぶ必要が無いことも確認する。
    counter = _count_car_closeness_calls(monkeypatch)

    edge = _edge(highway="primary")
    compute_edge_cost(edge, None, None, RoutePreference())

    assert counter[0] == 0


def test_compute_edge_cost_flat_and_paved_has_low_difficulty_and_cost_near_distance():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(average_grade=0.0)
    surface = "asphalt"

    result = compute_edge_cost(edge, elevation, surface, RoutePreference())

    assert result.allowed is True
    assert result.difficulty == 0.0
    assert result.cost == 100.0  # ペナルティ倍率1.0


def test_compute_edge_cost_steep_and_unpaved_costs_more_than_flat_and_paved():
    edge = _edge(distance_m=100.0)

    easy_result = compute_edge_cost(edge, _elevation_attr(0.0), "asphalt", RoutePreference())
    hard_result = compute_edge_cost(edge, _elevation_attr(12.0), "gravel", RoutePreference())

    assert hard_result.difficulty > easy_result.difficulty
    assert hard_result.cost > easy_result.cost
    assert hard_result.cost > edge.distance_m  # ペナルティが加算されている


def test_compute_edge_cost_missing_attributes_falls_back_to_distance_only():
    edge = _edge(distance_m=250.0)

    result = compute_edge_cost(edge, None, None, RoutePreference())

    assert result.allowed is True
    assert result.difficulty is None
    assert result.cost == 250.0


def _wind(wind_speed_ms: float, wind_direction_deg: float) -> WeatherConditions:
    return WeatherConditions(
        temperature_c=20.0,
        wind_speed_ms=wind_speed_ms,
        wind_direction_deg=wind_direction_deg,
        wind_direction_label="北",
        precipitation_probability_percent=None,
        observed_at="2026-01-01T00:00",
    )


def test_compute_wind_penalty_headwind_is_positive():
    # Edgeは北向き（bearing=0）に進む。北から吹いてくる風（wind_direction_deg=0）は正面からの
    # 向かい風になるはず（domain/wind.py: WindCalculatorの規約と同じ）。
    edge = _edge(geometry=[[35.700, 139.700], [35.701, 139.700]])
    wind = _wind(wind_speed_ms=5.0, wind_direction_deg=0.0)

    penalty = compute_wind_penalty(edge, wind)

    assert penalty == pytest.approx(5.0, abs=0.1)


def test_compute_wind_penalty_tailwind_is_negative():
    edge = _edge(geometry=[[35.700, 139.700], [35.701, 139.700]])
    wind = _wind(wind_speed_ms=5.0, wind_direction_deg=180.0)  # 南から北へ吹く=追い風

    penalty = compute_wind_penalty(edge, wind)

    assert penalty == pytest.approx(-5.0, abs=0.1)


def test_compute_wind_penalty_returns_none_without_wind():
    edge = _edge()

    assert compute_wind_penalty(edge, None) is None


def test_compute_edge_cost_headwind_costs_more_than_tailwind():
    edge = _edge(distance_m=100.0, geometry=[[35.700, 139.700], [35.701, 139.700]])
    elevation = _elevation_attr(0.0)
    surface = "asphalt"

    headwind_result = compute_edge_cost(edge, elevation, surface, RoutePreference(), wind=_wind(8.0, 0.0))
    tailwind_result = compute_edge_cost(edge, elevation, surface, RoutePreference(), wind=_wind(8.0, 180.0))

    assert headwind_result.difficulty > tailwind_result.difficulty
    assert headwind_result.cost > tailwind_result.cost


def test_compute_edge_cost_without_wind_ignores_wind_weight():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(0.0)
    surface = "asphalt"

    result = compute_edge_cost(edge, elevation, surface, RoutePreference())  # windを渡さない

    # 標高・路面がどちらも「易しい」なら、風が無視される限りdifficultyは0のはず
    assert result.difficulty == 0.0


def test_compute_edge_cost_without_stop_count_ignores_stop_weight():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(0.0)
    surface = "asphalt"

    result = compute_edge_cost(edge, elevation, surface, RoutePreference())  # stop_countを渡さない

    assert result.difficulty == 0.0


def test_compute_edge_cost_more_stops_costs_more():
    edge = _edge(distance_m=1000.0)
    elevation = _elevation_attr(0.0)
    surface = "asphalt"

    no_stops = compute_edge_cost(edge, elevation, surface, RoutePreference(), stop_count=0)
    many_stops = compute_edge_cost(edge, elevation, surface, RoutePreference(), stop_count=4)

    assert many_stops.difficulty > no_stops.difficulty
    assert many_stops.cost > no_stops.cost


def test_compute_edge_cost_respects_custom_weights():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(average_grade=12.0)  # 激坂
    surface = "asphalt"  # 舗装路（易しい）

    elevation_focused = compute_edge_cost(
        edge, elevation, surface, RoutePreference(elevation_weight=1.0, road_weight=0.0)
    )
    road_focused = compute_edge_cost(edge, elevation, surface, RoutePreference(elevation_weight=0.0, road_weight=1.0))

    # 勾配を全く考慮しない重みなら、舗装路のroad_difficulty(0)がそのままdifficultyになる
    assert road_focused.difficulty == 0.0
    # 勾配だけを考慮する重みなら、激坂のgradient_difficultyがそのままdifficultyになる
    assert elevation_focused.difficulty > road_focused.difficulty


# --- 改善計画T142: 二次(compute_edge_axis_scores)・三次(compute_cost_from_axis_scores)の分離 ---


def test_compute_cost_from_axis_scores_signature_has_no_primary_attribute_names():
    # T142の完了条件そのもの: 三次のコードのシグネチャに一次属性名(highway/lanes等)が
    # 一切現れないことをコードレビューではなくテストでも機械的に確認する。
    params = set(inspect.signature(compute_cost_from_axis_scores).parameters)
    assert params == {"distance_m", "axis_scores", "weights"}
    primary_attribute_names = {"highway", "lanes", "maxspeed", "cycleway", "surface", "way_tags", "edge"}
    assert params.isdisjoint(primary_attribute_names)


def test_compute_edge_axis_scores_returns_axis_id_keyed_scores():
    edge = _edge(distance_m=100.0)
    scores = compute_edge_axis_scores(edge, _elevation_attr(0.0), "asphalt")

    assert scores["gradient"] == 0.0
    assert scores["surface_q"] == 0.0
    assert "wind" not in scores  # windを渡していないためキー自体が無い


def test_compute_edge_axis_scores_omits_none_axes():
    edge = _edge(distance_m=100.0)
    scores = compute_edge_axis_scores(edge, None, None)

    assert scores == {}


def test_preference_to_axis_weights_maps_to_target_axis_ids():
    weights = preference_to_axis_weights(RoutePreference(car_stress_weight=0.4, night_weight=0.1))

    assert weights["car_stress"] == 0.4
    assert weights["night"] == 0.1
    assert set(weights) == {"gradient", "wind", "surface_q", "stop_density", "car_stress", "accident", "night"}


def test_compute_cost_from_axis_scores_matches_composite_difficulty_semantics():
    cost, difficulty = compute_cost_from_axis_scores(
        distance_m=100.0,
        axis_scores={"gradient": 0.0, "surface_q": 100.0},
        weights={"gradient": 1.0, "surface_q": 1.0},
    )

    assert difficulty == 50.0
    assert cost == 150.0  # 100 * (1 + 50/100)


def test_compute_cost_from_axis_scores_excludes_axes_missing_from_scores():
    # weightsにキーがあってもaxis_scoresに無ければ合成対象外(残りの重みで再正規化)。
    cost, difficulty = compute_cost_from_axis_scores(
        distance_m=100.0,
        axis_scores={"gradient": 40.0},
        weights={"gradient": 1.0, "surface_q": 1.0},
    )

    assert difficulty == 40.0
    assert cost == 140.0


def test_compute_cost_from_axis_scores_empty_scores_returns_distance_only():
    cost, difficulty = compute_cost_from_axis_scores(distance_m=100.0, axis_scores={}, weights={"gradient": 1.0})

    assert difficulty is None
    assert cost == 100.0


def test_compute_edge_cost_equals_composing_axis_scores_and_cost_functions():
    # compute_edge_costは分離後もcompute_edge_axis_scores + compute_cost_from_axis_scoresを
    # 合成した薄いラッパーであり、結果が完全に一致することを確認する（改善計画T142の
    # 回帰確認: 分離前後で同じ結果を返す）。
    edge = _edge(distance_m=250.0, highway="secondary")
    elevation = _elevation_attr(average_grade=5.0)
    surface = "gravel"
    preference = RoutePreference()
    way_tags = {"maxspeed": "50"}

    direct = compute_edge_cost(
        edge, elevation, surface, preference, way_tags=way_tags, stop_count=2, is_designated=True
    )

    axis_scores = compute_edge_axis_scores(
        edge, elevation, surface, way_tags=way_tags, stop_count=2, is_designated=True
    )
    weights = preference_to_axis_weights(preference)
    composed_cost, composed_difficulty = compute_cost_from_axis_scores(edge.distance_m, axis_scores, weights)

    assert direct.cost == composed_cost
    assert direct.difficulty == composed_difficulty
