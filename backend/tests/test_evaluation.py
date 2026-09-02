import inspect

import numpy as np
import pytest

from app.domain.attributes import EdgeAttributeCounts, EdgeMaterialBundle, EdgeMaterialTable, ElevationAttribute
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    MaterialTerm,
    time_scoped_weights,
)
from app.domain.evaluation import (
    RoutePreference,
    axis_inspector_breakdown,
    build_static_edge_score_matrix,
    combine_static_edge_score_matrices,
    compute_cost_from_axis_scores,
    compute_edge_axis_scores,
    compute_edge_cost,
    compute_hard_filter_excluded,
    compute_routable_node_ids,
    compute_wind_penalty,
    is_edge_allowed,
)
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.weather import WeatherConditions
from tests.realistic_axis_fixtures import axis_definitions_snapshot

# 改善計画T350: 本番相当の14軸（実軸id前提のロジック用）はtests/conftest.pyのセッション
# スコープautouseフィクスチャが全テスト共通で用意する（tests/realistic_axis_fixtures.py参照）。


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


def test_is_edge_allowed_excludes_edge_exceeding_max_average_grade_percent():
    # 改善計画T218a・T12 ADR原則5: 0次ハードフィルタの勾配しきい値。
    steep_uphill = _elevation_attr(average_grade=9.0)
    assert (
        is_edge_allowed(
            _edge(), elevation_attribute=steep_uphill, max_average_grade_percent=8.0
        )
        is False
    )


def test_is_edge_allowed_excludes_edge_exceeding_max_average_grade_percent_downhill():
    # 下り（負のaverage_grade）も絶対値で判定する。
    steep_downhill = _elevation_attr(average_grade=-9.0)
    assert (
        is_edge_allowed(
            _edge(), elevation_attribute=steep_downhill, max_average_grade_percent=8.0
        )
        is False
    )


def test_is_edge_allowed_allows_edge_within_max_average_grade_percent():
    gentle = _elevation_attr(average_grade=5.0)
    assert (
        is_edge_allowed(_edge(), elevation_attribute=gentle, max_average_grade_percent=8.0) is True
    )


def test_is_edge_allowed_max_average_grade_percent_none_disables_gradient_filter():
    steep = _elevation_attr(average_grade=99.0)
    assert is_edge_allowed(_edge(), elevation_attribute=steep, max_average_grade_percent=None) is True


def test_is_edge_allowed_allows_edge_without_elevation_attribute_even_with_threshold_set():
    # 事前計算バッチ未実行のEdge（elevation_attribute=None）は判断材料が無いため除外しない
    # （他のHard Constraint同様、不明な場合は許可しSoft Constraint側に委ねる）。
    assert is_edge_allowed(_edge(), elevation_attribute=None, max_average_grade_percent=1.0) is True


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
        apparent_temperature_c=None,
        wind_speed_ms=wind_speed_ms,
        wind_direction_deg=wind_direction_deg,
        wind_direction_label="北",
        wind_gusts_ms=None,
        precipitation_probability_percent=None,
        precipitation_mm=None,
        uv_index=None,
        observed_at="2026-01-01T00:00",
        weather_code=None,
        is_day=None,
        sunrise=None,
        sunset=None,
        precipitation_probability_max_percent=None,
        wind_speed_max_ms=None,
        temperature_max_c=None,
        temperature_min_c=None,
        uv_index_max=None,
        today_periods=[],
    )


def test_compute_wind_penalty_headwind_is_positive():
    # 改善計画T218: compute_wind_penaltyはgeometryではなくbearing_degを直接使うため、
    # ここでbearing=0（北向きに進む）を明示する。北から吹いてくる風（wind_direction_deg=0）は
    # 正面からの向かい風になるはず（domain/wind.py: WindCalculatorの規約と同じ）。
    edge = _edge(bearing_deg=0.0)
    wind = _wind(wind_speed_ms=5.0, wind_direction_deg=0.0)

    penalty = compute_wind_penalty(edge, wind)

    assert penalty == pytest.approx(5.0, abs=0.1)


def test_compute_wind_penalty_tailwind_is_negative():
    edge = _edge(bearing_deg=0.0)
    wind = _wind(wind_speed_ms=5.0, wind_direction_deg=180.0)  # 南から北へ吹く=追い風

    penalty = compute_wind_penalty(edge, wind)

    assert penalty == pytest.approx(-5.0, abs=0.1)


def test_compute_wind_penalty_returns_none_without_wind():
    edge = _edge(bearing_deg=0.0)

    assert compute_wind_penalty(edge, None) is None


def test_compute_wind_penalty_returns_none_without_bearing():
    # 改善計画T218: bearing_deg未計算（None）のEdgeは風評価を行わない
    # （探索フェーズの軽量グラフはgeometryを持たずbearing_degのみで判定するため、
    # このNoneガードが実質的な唯一の「データ無し」経路になる）。
    edge = _edge(bearing_deg=None)
    wind = _wind(wind_speed_ms=5.0, wind_direction_deg=0.0)

    assert compute_wind_penalty(edge, wind) is None


def test_compute_edge_cost_headwind_costs_more_than_tailwind():
    edge = _edge(distance_m=100.0, bearing_deg=0.0)
    elevation = _elevation_attr(0.0)
    surface = "asphalt"

    headwind_result = compute_edge_cost(edge, elevation, surface, RoutePreference(), weather=_wind(8.0, 0.0))
    tailwind_result = compute_edge_cost(edge, elevation, surface, RoutePreference(), weather=_wind(8.0, 180.0))

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
        edge, elevation, surface, RoutePreference(weights={"gradient": 1.0, "surface_q": 0.0})
    )
    road_focused = compute_edge_cost(
        edge, elevation, surface, RoutePreference(weights={"gradient": 0.0, "surface_q": 1.0})
    )

    # 勾配を全く考慮しない重みなら、舗装路のroad_difficulty(0)がそのままdifficultyになる
    assert road_focused.difficulty == 0.0
    # 勾配だけを考慮する重みなら、激坂のgradient_difficultyがそのままdifficultyになる
    assert elevation_focused.difficulty > road_focused.difficulty


# --- 改善計画T142: 二次(compute_edge_axis_scores)・三次(compute_cost_from_axis_scores)の分離 ---


def test_compute_cost_from_axis_scores_signature_has_no_primary_attribute_names():
    # T142の完了条件そのもの: 三次のコードのシグネチャに一次属性名(highway/lanes等)が
    # 一切現れないことをコードレビューではなくテストでも機械的に確認する。
    params = set(inspect.signature(compute_cost_from_axis_scores).parameters)
    # 改善計画T218・T12 ADR原則1: penalty_strength（P）はコスト式の割増率の強さを
    # 調整するリクエストパラメータであり、一次属性名ではないため許容する。
    assert params == {"distance_m", "axis_scores", "weights", "penalty_strength"}
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


def test_compute_edge_axis_scores_bicycle_infra_quality_reflects_bicycle_infra_tags():
    """改善計画T353回帰テスト: car_stress_bicycle_infra_adjustment（1材料1軸原則T268
    違反のため廃止）が担っていた「compute_edge_axis_scoresが手組みするmaterials辞書に
    正規化フラグ材料（highway_is_cycleway等）を混ぜ込む」役割は、bicycle_infra_quality
    公開軸が直接引き継いだ。混ぜ込み忘れがあると、この関数経由のbicycle_infra_quality
    評価だけが常に「データなし」に固定されてしまう（required=Trueなterms→全欠損）。
    cycleway=trackタグの有無でbicycle_infra_qualityスコアが変わること（分離自転車道は
    易しい側=値が小さい）を確認する。

    あわせて、T353の設計変更どおりcar_stressは自転車インフラの有無に一切影響されない
    こと（trackの有無で値が変わらない）も回帰確認する——旧設計ではここが変動していた。"""
    edge = _edge(distance_m=100.0, highway="residential")

    without_track = compute_edge_axis_scores(edge, None, None, way_tags={})
    with_track = compute_edge_axis_scores(edge, None, None, way_tags={"cycleway": "track"})

    assert without_track["bicycle_infra_quality"] == 100.0
    assert with_track["bicycle_infra_quality"] == 0.0
    assert with_track["bicycle_infra_quality"] < without_track["bicycle_infra_quality"]
    # car_stressはhighway種別のみで決まり、自転車インフラの有無では変化しない（T353）。
    assert without_track["car_stress"] == with_track["car_stress"] == 50.0


def test_route_preference_weights_fill_defaults_and_reject_unknown_axis():
    # 改善計画T221 Stage B: RoutePreference自体がaxis_idキーの重み辞書を持つ。
    # 部分指定は既定値（AXIS_DEFINITIONSのdefault_weight）で補完され、未知キーはエラー。
    preference = RoutePreference(weights={"car_stress": 0.4, "night": 0.1})

    assert preference.weights["car_stress"] == 0.4
    assert preference.weights["night"] == 0.1
    assert preference.weights["gradient"] == 0.15  # 既定値で補完
    # 改善計画T347: bicycle_infra_qualityが公開軸として加わった。
    assert set(preference.weights) == {
        "gradient", "wind", "surface_q", "stop_density", "car_stress", "accident", "night", "bicycle_infra_quality",
    }

    with pytest.raises(ValueError, match="unknown axis_id"):
        RoutePreference(weights={"no_such_axis": 1.0})


def test_route_preference_with_weight_returns_modified_copy():
    base = RoutePreference()
    modified = base.with_weight("night", 0.5)

    assert modified.weights["night"] == 0.5
    assert base.weights["night"] == 0.0  # 元のインスタンスは不変
    assert modified.weights["gradient"] == base.weights["gradient"]


def test_route_preference_with_weight_returns_self_for_unknown_axis_id():
    # 改善計画T316フォローアップ回帰テスト: 対象軸が現在の重み辞書（＝現在の公開軸集合）に
    # 無い場合、強制的にキーを追加してRoutePreferenceを再構築すると
    # 「未知のaxis_id」バリデーションエラーになる（night軸が軸スタジオで非公開化された際、
    # road_graph_engine.pyのnight動的化が丸ごと500になった実障害、2026-08-25）。
    # 差し替え対象の軸自体が存在しない以上、無変更のselfを返すのが正しい。
    base = RoutePreference(weights={"gradient": 0.15})

    result = base.with_weight("no_such_axis", 0.5)

    assert result is base


def test_route_preference_with_time_scope_zeros_night_only_axis_when_scope_inactive():
    # 改善計画T352: axis_id"night"の直接ハードコードから、AxisDefinition.time_scope
    # （実フィクスチャではnightのみ"night_only"）ベースの汎用ロジックへ置き換えた回帰テスト。
    base = RoutePreference().with_weight("night", 0.7)

    scoped = base.with_time_scope(frozenset())

    assert scoped.weights["night"] == 0.0
    assert scoped.weights["gradient"] == base.weights["gradient"]  # 他軸は無変更


def test_route_preference_with_time_scope_keeps_weight_when_scope_active():
    base = RoutePreference().with_weight("night", 0.7)

    scoped = base.with_time_scope(frozenset({"night_only"}))

    assert scoped.weights["night"] == 0.7
    assert scoped.weights == base.weights


def test_route_preference_with_time_scope_ignores_axis_not_in_weights():
    # with_weightのT316フォローアップ（未知axis_idは無変更）と同じ理由: time_scope対象の
    # 軸自体がweightsに存在しない（内部軸・非公開化済み等）場合、KeyError等では落ちず
    # 単に無視される。
    base = RoutePreference(weights={"gradient": 0.15})

    result = base.with_time_scope(frozenset())

    assert result is base


def test_time_scoped_weights_works_with_a_single_night_only_axis():
    # 改善計画T352完了条件: night軸のtime_scope汎用化が、本番相当の13軸フルセット
    # （tests/realistic_axis_fixtures.py）に依存せず、1軸だけのAXIS_DEFINITIONSでも
    # 正しく動作することを確認する（フルセット必須という制約が解消されたことの裏付け）。
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS["only_axis"] = AxisDefinition(
            axis_id="only_axis",
            shape=BreakpointLinearShape(
                terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (1.0, 100.0)]
            ),
            default_weight=0.5,
            label="テスト専用軸",
            is_published=True,
            time_scope="night_only",
        )

        active = time_scoped_weights({"only_axis": 0.7}, frozenset({"night_only"}))
        inactive = time_scoped_weights({"only_axis": 0.7}, frozenset())

        assert active == {"only_axis": 0.7}
        assert inactive == {"only_axis": 0.0}


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
    composed_cost, composed_difficulty = compute_cost_from_axis_scores(edge.distance_m, axis_scores, preference.weights)

    assert direct.cost == composed_cost
    assert direct.difficulty == composed_difficulty


# --- axis_inspector_breakdown（区間インスペクタ、改善計画T146） ---


def test_axis_inspector_breakdown_computes_available_axes_from_way_counts():
    """way_counts（length_m, accident_count, stop_count, intersection_count）がある場合、
    car_stress/surface_q/stop_density/accident/nightが算出され、gradient/windは
    ルート文脈が無いため常にavailable=Falseになる。"""
    result = axis_inspector_breakdown(
        highway="residential",
        tags={"surface": "asphalt", "lit": "yes"},
        is_designated=False,
        way_counts=(1000.0, 2.0, 4, 6),  # 1km, 事故2件, 停止4件, 交差点6件
        accident_years_covered=2,
    )

    by_id = {axis.axis_id: axis for axis in result.axes}
    assert by_id["car_stress"].available is True
    assert by_id["surface_q"].available is True
    assert by_id["surface_q"].difficulty == 0.0  # asphalt=良い路面
    assert by_id["stop_density"].available is True
    assert by_id["accident"].available is True
    assert by_id["night"].available is True
    # 改善計画T347: bicycle_infra_qualityはcar_stressのhighway基準値ゲートに依存しない
    # （highway="residential"かつcyclewayタグ無しでも「専用インフラ無し」として算出可能）
    # ため、他の軸とは独立にavailable=Trueになる。
    assert by_id["bicycle_infra_quality"].available is True
    assert by_id["gradient"].available is False
    assert by_id["gradient"].difficulty is None
    assert by_id["wind"].available is False
    assert result.composite_difficulty is not None
    # 全8軸（改善計画T347でbicycle_infra_quality追加）の重み合計1.23のうち
    # gradient(0.15)+wind(0.26)を除いた0.82ぶんが取得できている。
    assert result.covered_weight_fraction == pytest.approx(0.82 / 1.23, abs=0.001)


def test_axis_inspector_breakdown_bicycle_infra_quality_reflects_bicycle_infra_tags():
    """改善計画T353回帰テスト: compute_edge_axis_scores版と同じ理由
    （car_stress_bicycle_infra_adjustment内部軸の廃止に伴い、正規化フラグ材料を
    bicycle_infra_quality公開軸が直接持つようになったため、axis_inspector_breakdownが
    手組みするmaterials辞書にも新materialsを混ぜ込む必要がある）。cycleway=trackタグの
    有無で区間インスペクタのbicycle_infra_quality表示が変わること、car_stressは
    変わらないことを確認する。"""
    without_track = axis_inspector_breakdown(
        highway="residential", tags={}, is_designated=False, way_counts=None, accident_years_covered=0
    )
    with_track = axis_inspector_breakdown(
        highway="residential",
        tags={"cycleway": "track"},
        is_designated=False,
        way_counts=None,
        accident_years_covered=0,
    )

    def difficulty(result, axis_id: str) -> float:
        return next(a.difficulty for a in result.axes if a.axis_id == axis_id)

    without_infra = difficulty(without_track, "bicycle_infra_quality")
    with_infra = difficulty(with_track, "bicycle_infra_quality")
    assert without_infra == 100.0
    assert with_infra == 0.0
    assert with_infra < without_infra
    # car_stressはhighway種別のみで決まり、自転車インフラの有無では変化しない（T353）。
    assert difficulty(without_track, "car_stress") == difficulty(with_track, "car_stress") == 50.0


def test_axis_inspector_breakdown_way_counts_none_marks_count_based_axes_unavailable():
    """way_attribute_countsに行が無い（way_counts=None）場合、事故密度・停止密度は
    算出不能（available=False）だが、タグだけで決まる車ストレス・路面・夜間は
    引き続き算出できる。"""
    result = axis_inspector_breakdown(
        highway="residential",
        tags={"surface": "asphalt"},
        is_designated=False,
        way_counts=None,
        accident_years_covered=3,
    )

    by_id = {axis.axis_id: axis for axis in result.axes}
    assert by_id["stop_density"].available is False
    assert by_id["accident"].available is False
    assert by_id["car_stress"].available is True
    assert by_id["surface_q"].available is True
    assert 0.0 < result.covered_weight_fraction < 1.0


def test_axis_inspector_breakdown_unknown_highway_yields_no_usable_composite():
    """判定基準未登録のhighway・タグ無し・way_counts無しでは、車ストレス・路面・
    停止密度・事故密度すべてavailable=Falseになる。night_difficultyだけはタグが
    空辞書でも常に加点式でスコアを返す（lit無し=+50）ため唯一availableになるが、
    night_weightの既定値は0.0のため合成コストへは効かない。改善計画T347:
    bicycle_infra_qualityはcar_stressのhighway基準値ゲートに依存しない
    （highwayの値そのものは判定基準未登録でも、cyclewayタグが無ければ「専用インフラ
    無し」として算出できる）ため、唯一weight>0で合成に効く軸としてavailableになる。"""
    result = axis_inspector_breakdown(
        highway="motorway",  # car_stress_levelの判定基準に未登録
        tags={},
        is_designated=False,
        way_counts=None,
        accident_years_covered=0,
    )

    by_id = {axis.axis_id: axis for axis in result.axes}
    assert by_id["car_stress"].available is False
    assert by_id["surface_q"].available is False
    assert by_id["stop_density"].available is False
    assert by_id["accident"].available is False
    assert by_id["night"].available is True  # weight=0.0のため合成には無影響
    assert by_id["bicycle_infra_quality"].available is True
    assert by_id["bicycle_infra_quality"].difficulty == 100.0  # 専用インフラ無し(roadway相当)
    assert result.composite_difficulty == 100.0
    assert result.covered_weight_fraction == pytest.approx(0.15 / 1.23, abs=0.001)


def test_axis_inspector_breakdown_weights_match_route_preference_weights():
    """各軸のweightはRoutePreference.weightsと一致する（既定route_preference使用時）。"""
    result = axis_inspector_breakdown(
        highway="residential", tags={}, is_designated=False, way_counts=None, accident_years_covered=0,
    )

    expected_weights = RoutePreference().weights
    for axis in result.axes:
        assert axis.weight == expected_weights[axis.axis_id]


# --- 改善計画T536フォローアップ: 空タイル（Edge0件）混在時のcombine_static_edge_score_matrices ---


def test_build_static_edge_score_matrix_for_empty_graph_matches_axis_ids_of_nonempty_graph():
    # 改善計画T536フォローアップ回帰（2026-09-02、本番Oracle VMの使い捨てコンテナ・
    # 東京駅30km・split済み条件で実際に発生した障害）: Edge0件のグラフから構築した
    # StaticEdgeScoreMatrixは、axis_scoresの列数が0（=公開軸の集合と食い違う）に
    # なっていた（_evaluate_axes_bulkのn==0早期returnがaxis_arrays={}を返していたため）。
    # 修正後は空グラフでもaxis_idsが非空グラフと同じ公開軸集合・同じ順序になる。
    graph = RoadGraph(
        graph_version="v1",
        nodes={
            "node-1": Node(node_id="node-1", latitude=35.70, longitude=139.70),
            "node-2": Node(node_id="node-2", latitude=35.71, longitude=139.71),
        },
        edges={"edge-1": _edge()},
    )
    materials = {
        "edge-1": EdgeMaterialBundle(
            surface="asphalt", way_tags={}, attribute_counts=None, elevation_attribute=None, is_designated=False
        )
    }
    nonempty_matrix = build_static_edge_score_matrix(graph, materials)

    empty_graph = RoadGraph(graph_version="v1", nodes={}, edges={})
    empty_matrix = build_static_edge_score_matrix(empty_graph, {})

    assert len(nonempty_matrix.axis_ids) > 0
    assert empty_matrix.axis_ids == nonempty_matrix.axis_ids
    assert empty_matrix.axis_scores.shape == (0, len(nonempty_matrix.axis_ids))


def test_combine_static_edge_score_matrices_handles_empty_tile_mixed_with_nonempty_tile():
    # 上記バグの本体（combine_static_edge_score_matrices側）の直接回帰確認。修正前は
    # np.concatenateが「dimension 1のサイズ不一致」でValueErrorを送出していた。
    # 空タイルの登場順（先/後）どちらでも正しく結合できることを確認する
    # （combine_static_edge_score_matricesはmatrices[0].axis_idsを全体のaxis_idsとして
    # 採用するため、先頭が空タイルの場合も列数・列順が揃っている必要がある）。
    graph = RoadGraph(
        graph_version="v1",
        nodes={
            "node-1": Node(node_id="node-1", latitude=35.70, longitude=139.70),
            "node-2": Node(node_id="node-2", latitude=35.71, longitude=139.71),
        },
        edges={"edge-1": _edge()},
    )
    materials = {
        "edge-1": EdgeMaterialBundle(
            surface="asphalt", way_tags={}, attribute_counts=None, elevation_attribute=None, is_designated=False
        )
    }
    nonempty_matrix = build_static_edge_score_matrix(graph, materials)
    empty_matrix = build_static_edge_score_matrix(RoadGraph(graph_version="v1", nodes={}, edges={}), {})

    combined = combine_static_edge_score_matrices([nonempty_matrix, empty_matrix])
    assert combined.edge_ids == ["edge-1"]
    assert combined.axis_scores.shape == (1, len(nonempty_matrix.axis_ids))

    combined_reversed = combine_static_edge_score_matrices([empty_matrix, nonempty_matrix])
    assert combined_reversed.edge_ids == ["edge-1"]
    assert combined_reversed.axis_scores.shape == (1, len(nonempty_matrix.axis_ids))
    # 値そのものも登場順に関わらず一致する（列の並びがずれていないことの確認、NaNは
    # NaN同士で一致とみなす）。
    left, right = combined.axis_scores, combined_reversed.axis_scores
    both_nan = np.isnan(left) & np.isnan(right)
    assert ((left == right) | both_nan).all()


def test_combine_static_edge_score_matrices_handles_all_empty_tiles():
    # bbox内の全タイルがEdge0件（道路データの無い区画）の場合も例外なく空の結合結果を返す。
    empty_matrix_a = build_static_edge_score_matrix(RoadGraph(graph_version="v1", nodes={}, edges={}), {})
    empty_matrix_b = build_static_edge_score_matrix(RoadGraph(graph_version="v1", nodes={}, edges={}), {})

    combined = combine_static_edge_score_matrices([empty_matrix_a, empty_matrix_b])

    assert combined.edge_ids == []
    assert combined.axis_scores.shape == (0, len(empty_matrix_a.axis_ids))


# --- 改善計画T546: EdgeMaterialTable経由でもbuild_static_edge_score_matrixが一致すること ---


def _diverse_graph_and_bundles(n: int) -> tuple[RoadGraph, dict[str, EdgeMaterialBundle]]:
    """標高・件数・タグ・指定路線の有無を組み合わせた、実データ規模相当のfixture。"""
    nodes = {f"node-{i}": Node(node_id=f"node-{i}", latitude=35.70 + i * 0.0001, longitude=139.70) for i in range(n + 1)}
    edges = {
        f"edge-{i}": _edge(
            edge_id=f"edge-{i}", from_node_id=f"node-{i}", to_node_id=f"node-{i + 1}",
            highway="residential" if i % 5 else "trunk", osm_way_id=i,
        )
        for i in range(n)
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)

    bundles: dict[str, EdgeMaterialBundle] = {}
    for i in range(n):
        edge_id = f"edge-{i}"
        remainder = i % 4
        if remainder == 0:
            bundles[edge_id] = EdgeMaterialBundle(
                surface="asphalt",
                way_tags={"highway": "residential", "bicycle": "no" if i % 20 == 0 else "yes"},
                attribute_counts=EdgeAttributeCounts(
                    accident_count=float(i % 3), stop_count=i % 4, intersection_count=i % 2
                ),
                elevation_attribute=ElevationAttribute(
                    edge_id=edge_id, average_grade=(i % 11) - 5, data_source="test", calculated_at="t",
                ),
                is_designated=(i % 13 == 0),
            )
        elif remainder == 1:
            bundles[edge_id] = EdgeMaterialBundle(
                surface=None, way_tags={}, attribute_counts=None, elevation_attribute=None, is_designated=False,
            )
        elif remainder == 2:
            bundles[edge_id] = EdgeMaterialBundle(
                surface="gravel", way_tags={"surface": "gravel"}, attribute_counts=None,
                # 行はあるが有効点不足で全フィールドNone（境界ケース）。
                elevation_attribute=ElevationAttribute(edge_id=edge_id, data_source="test", calculated_at="t"),
                is_designated=False,
            )
        else:
            bundles[edge_id] = EdgeMaterialBundle(
                surface=None, way_tags={"motor_vehicle": "no"},
                attribute_counts=EdgeAttributeCounts(accident_count=0.0, stop_count=0, intersection_count=0),
                elevation_attribute=None, is_designated=(i % 7 == 0),
            )
    return graph, bundles


def _assert_matrices_equal(a, b) -> None:
    assert a.edge_ids == b.edge_ids
    assert a.axis_ids == b.axis_ids
    for name in ("axis_scores", "distance_m", "bearing_deg", "gradient_percent"):
        left, right = getattr(a, name), getattr(b, name)
        both_nan = np.isnan(left) & np.isnan(right)
        assert ((left == right) | both_nan).all(), name
    assert (a.is_motorway == b.is_motorway).all()
    assert (a.is_trunk == b.is_trunk).all()
    assert (a.no_bicycle == b.no_bicycle).all()


def test_build_static_edge_score_matrix_matches_between_table_and_dict_materials():
    """改善計画T546「実装リスク」節が要求する回帰: 軸編集後の経路
    （`to_legacy_dicts()`経由で構築したスコア行列）が、bundleの生dictから直接構築した
    行列と一致することを、実データ規模相当のfixtureで確認する（ずれるとルートの軸別
    色分けだけが変わる、という指摘への対応）。"""
    graph, bundles = _diverse_graph_and_bundles(2_000)
    edge_ids = list(graph.edges.keys())
    table = EdgeMaterialTable.from_bundles(edge_ids, bundles)

    matrix_from_table = build_static_edge_score_matrix(graph, table, accident_years_covered=3)
    matrix_from_dict = build_static_edge_score_matrix(graph, bundles, accident_years_covered=3)

    _assert_matrices_equal(matrix_from_table, matrix_from_dict)


def test_build_static_edge_score_matrix_with_empty_edge_material_table():
    graph = RoadGraph(graph_version="v1", nodes={}, edges={})
    table = EdgeMaterialTable.from_bundles([], {})

    matrix = build_static_edge_score_matrix(graph, table)

    assert matrix.edge_ids == []
    assert len(matrix.axis_ids) > 0
    assert matrix.axis_scores.shape == (0, len(matrix.axis_ids))


# --- 改善計画T546: compute_routable_node_ids（スコア行列の生配列ベース版） ---


def test_compute_routable_node_ids_includes_endpoints_of_non_excluded_edges():
    graph = RoadGraph(
        graph_version="v1",
        nodes={
            "node-1": Node(node_id="node-1", latitude=35.70, longitude=139.70),
            "node-2": Node(node_id="node-2", latitude=35.71, longitude=139.71),
        },
        edges={"edge-1": _edge(edge_id="edge-1", from_node_id="node-1", to_node_id="node-2")},
    )

    routable = compute_routable_node_ids(graph, ["edge-1"], np.array([False]))

    assert routable == {"node-1", "node-2"}


def test_compute_routable_node_ids_excludes_edges_marked_excluded():
    graph = RoadGraph(
        graph_version="v1",
        nodes={
            "node-1": Node(node_id="node-1", latitude=35.70, longitude=139.70),
            "node-2": Node(node_id="node-2", latitude=35.71, longitude=139.71),
        },
        edges={"edge-1": _edge(edge_id="edge-1", from_node_id="node-1", to_node_id="node-2")},
    )

    routable = compute_routable_node_ids(graph, ["edge-1"], np.array([True]))

    assert routable == set()


def test_compute_routable_node_ids_matches_hard_filter_excluded_from_score_matrix():
    """`compute_hard_filter_excluded`が返す配列をそのまま渡す実際の呼び出し形（
    `road_graph_engine.py: _get_or_build_node_index`と同じ経路）で、motorway等の
    0次フィルタがそのままroutable判定へ反映されることを確認する。"""
    graph, bundles = _diverse_graph_and_bundles(50)
    edge_ids = list(graph.edges.keys())
    table = EdgeMaterialTable.from_bundles(edge_ids, bundles)
    matrix = build_static_edge_score_matrix(graph, table)
    excluded = compute_hard_filter_excluded(
        matrix.is_motorway, matrix.is_trunk, matrix.no_bicycle, matrix.gradient_percent,
    )

    routable = compute_routable_node_ids(graph, matrix.edge_ids, excluded)

    # trunk（highwayが5の倍数でないedge、_diverse_graph_and_bundles参照）は既定
    # DEFAULT_HARD_FILTERSで除外されるため、trunkのみに接続するNodeはroutableに含まれない。
    for i, edge_id in enumerate(matrix.edge_ids):
        edge = graph.edges[edge_id]
        if excluded[i]:
            continue
        assert edge.from_node_id in routable
        assert edge.to_node_id in routable


def test_compute_routable_node_ids_empty_inputs_return_empty_set():
    graph = RoadGraph(graph_version="v1", nodes={}, edges={})

    routable = compute_routable_node_ids(graph, [], np.array([]))

    assert routable == set()
