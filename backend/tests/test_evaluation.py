from datetime import datetime, timezone

import numpy as np
import pytest

from app.domain.attributes import (
    ElevationAttribute,
)
from app.domain.material_catalog import MATERIAL_CATALOG
from tests.material_arrays import material_arrays
from app.domain.landcover import LandcoverPercentages, WayLandcover
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    time_scoped_weights,
)
from app.domain.axis_inspector import axis_inspector_breakdown
from app.domain.evaluation import (
    build_static_edge_score_matrix,
    combine_static_edge_score_matrices,
    compose_costs_from_axis_matrix,
    has_route_facing_raw_value,
)
from app.domain.axis_display import raw_value_unit
from app.domain import evaluation as evaluation_module
from app.domain.hard_filters import compute_routable_node_ids
from app.domain.route_preference import RoutePreference
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.weather import WeatherConditions
from app.domain.wind import kmh_to_ms
from tests.realistic_axis_fixtures import axis_definitions_snapshot

V20 = kmh_to_ms(20.0)

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














































def _wind(wind_speed_ms: float, wind_direction_deg: float) -> WeatherConditions:
    return WeatherConditions(
        temperature_c=20.0,
        wind_speed_ms=wind_speed_ms,
        wind_direction_deg=wind_direction_deg,
        wind_direction_label="北",
        precipitation_mm=None,
        observed_at="2026-01-01T00:00",
        weather_code=None,
        is_day=None,
        sunrise=None,
        sunset=None,
        wind_speed_max_ms=None,
        temperature_max_c=None,
        precipitation_max_mm=None,
        temperature_min_c=None,
        today_periods=[],
    )






















# --- 改善計画T142: 二次(compute_edge_axis_scores)・三次(compute_cost_from_axis_scores)の分離 ---










def test_route_preference_weights_fill_defaults_and_reject_unknown_axis():
    # 改善計画T221 Stage B: RoutePreference自体がaxis_idキーの重み辞書を持つ。
    # 部分指定は既定値（AXIS_DEFINITIONSのdefault_weight）で補完され、未知キーはエラー。
    preference = RoutePreference(weights={"car_stress": 0.4, "night": 0.1})

    assert preference.weights["car_stress"] == 0.4
    assert preference.weights["night"] == 0.1
    assert preference.weights["gradient"] == 0.15  # 既定値で補完
    # 改善計画T347: bicycle_infra_qualityが公開軸として加わった。
    assert set(preference.weights) == {
        "gradient", "wind", "surface_q", "stop_density", "car_stress", "accident", "night",
        "bicycle_infra_quality", "openness",
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














# --- axis_inspector_breakdown（区間インスペクタ、改善計画T146） ---


def _way_materials(**overrides) -> dict[str, object]:
    """way1本ぶんの材料値（リポジトリが返す形）。既定は全て欠損で、軸が要る材料だけ渡す。

    どの材料がどの軸を成立させるかを、このファイルの中で見えるようにするための入力。
    材料の値の求め方そのものは`MaterialSpec.value_sql`の仕事で、
    `tests/test_material_sql.py`が別に検証する。
    """
    materials: dict[str, object] = {material_id: None for material_id in MATERIAL_CATALOG}
    materials.update(overrides)
    return materials


# 自転車インフラを何も持たない道（bicycle_infra_qualityはこの5材料が揃って初めて算出できる）。
_NO_BICYCLE_INFRA = {
    "cycleway_has_lane": False,
    "cycleway_has_shared": False,
    "cycleway_has_track": False,
    "highway_is_cycleway": False,
    "shared_pedestrian_path": False,
}
_RESIDENTIAL_PAVED = {
    "highway": "residential",
    "surface_good": True,
    "surface": "asphalt",
    **_NO_BICYCLE_INFRA,
}


def test_axis_inspector_breakdown_computes_available_axes_from_materials():
    """材料が揃っている軸だけがavailableになる。way単体では求まらない勾配・風は常に欠損。"""
    result = axis_inspector_breakdown(
        highway="residential",
        tags={"lit": "yes"},
        is_designated=False,
        materials=_way_materials(
            **_RESIDENTIAL_PAVED,
            lit=True,
            has_tunnel=False,
            accident_count_per_km_year=1.0,
            intersection_count_per_km=6.0,
            poi_signal_per_km=4.0,
            poi_stop_per_km=0.0,
            poi_crossing_per_km=0.0,
            poi_level_crossing_per_km=0.0,
        ),
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
    # gradient(0.15)+wind(0.26)を除いた0.82ぶんが取得できている。
    assert result.covered_weight_fraction == pytest.approx(0.82 / 1.23, abs=0.001)


def test_axis_inspector_contributions_sum_to_the_composite():
    """軸ごとの寄与度の合計が合成スコアと一致する（内訳の合計が結論と合わない表示を作らない）。

    ルート結果の`axis_contributions`と同じ読み方にするため、重みを掛ける計算はサーバー側に
    置く。算出できない軸は寄与度もNoneで、合成の分母にも入らない。
    """
    result = axis_inspector_breakdown(
        highway="residential",
        tags={"lit": "yes"},
        is_designated=False,
        materials=_way_materials(
            **_RESIDENTIAL_PAVED,
            lit=True,
            has_tunnel=False,
            accident_count_per_km_year=1.0,
            intersection_count_per_km=6.0,
            poi_signal_per_km=4.0,
        ),
    )

    by_id = {axis.axis_id: axis for axis in result.axes}
    assert by_id["gradient"].contribution is None  # ルート文脈が無く算出不能
    total = sum(axis.contribution for axis in result.axes if axis.contribution is not None)
    assert result.composite_difficulty == pytest.approx(total, abs=0.15)


def test_axis_inspector_contributions_are_none_when_nothing_is_available():
    """1軸も算出できなければ合成もNoneで、寄与度も全てNone（0ではない）。"""
    result = axis_inspector_breakdown(
        highway=None, tags={}, is_designated=False, materials=_way_materials(),
    )

    if result.composite_difficulty is None:
        assert all(axis.contribution is None for axis in result.axes)


def _landcover(percentages: LandcoverPercentages | None) -> WayLandcover:
    return WayLandcover(
        osm_way_id=100,
        percentages=percentages,
        data_source="esri-io-lulc",
        data_version="2025",
        computed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


_LANDCOVER_PERCENTAGES = LandcoverPercentages(
    valid_pixels=500, water_percent=0, trees_percent=40.0, flooded_veg_percent=0,
    crops_percent=0, built_percent=25.0, bare_percent=0, snow_ice_percent=0, rangeland_percent=35.0,
)


def test_axis_inspector_breakdown_openness_follows_the_landcover_materials():
    """開放度は土地被覆の材料だけを見て、他の軸のスコアには影響しない。材料が欠損なら
    算出不能（available=False）になる。"""
    without = axis_inspector_breakdown(
        highway="residential", tags={}, is_designated=False,
        materials=_way_materials(**_RESIDENTIAL_PAVED),
    )
    with_landcover = axis_inspector_breakdown(
        highway="residential", tags={}, is_designated=False,
        materials=_way_materials(**_RESIDENTIAL_PAVED, trees_percent=40.0, built_percent=25.0),
    )

    def by_id(result):
        return {axis.axis_id: axis for axis in result.axes}

    assert by_id(without)["openness"].available is False
    assert by_id(with_landcover)["openness"].available is True
    others_with = [axis for axis in with_landcover.axes if axis.axis_id != "openness"]
    others_without = [axis for axis in without.axes if axis.axis_id != "openness"]
    assert others_with == others_without


def test_axis_inspector_breakdown_returns_every_landcover_class():
    """軸が材料に使うのは一部のクラスだけだが、内訳は全クラス返す。

    「この道が何で覆われているか」は軸の点数からは読み取れないため、区間インスペクタは
    材料に使っていないクラス（農地・草地等）も見せる。
    """
    result = axis_inspector_breakdown(
        highway="residential", tags={}, is_designated=False,
        materials=_way_materials(**_RESIDENTIAL_PAVED),
        way_landcover=_landcover(_LANDCOVER_PERCENTAGES),
    )

    assert result.landcover is not None
    # 材料に使っていないクラスが、値を保ったまま届く。
    assert result.landcover.rangeland_percent == 35.0
    assert result.landcover.valid_pixels == 500


def test_axis_inspector_breakdown_has_no_landcover_when_it_was_not_given():
    result = axis_inspector_breakdown(
        highway="residential", tags={}, is_designated=False,
        materials=_way_materials(**_RESIDENTIAL_PAVED),
    )

    assert result.landcover is None


def test_axis_inspector_breakdown_treats_no_value_landcover_row_as_missing():
    """割合がNULLの行（そのラスタ構成では値なし、T688）は、行が無い場合と同じ欠損。

    行を残すのは増分実行が毎回やり直さないためで、表示の意味は変えない。
    """
    result = axis_inspector_breakdown(
        highway="residential", tags={}, is_designated=False,
        materials=_way_materials(**_RESIDENTIAL_PAVED),
        way_landcover=_landcover(None),
    )

    assert result.landcover is None


def test_axis_inspector_breakdown_bicycle_infra_quality_reflects_bicycle_infra_materials():
    """cycleway=trackの有無でbicycle_infra_qualityが変わり、car_stressは変わらない（T353）。"""
    without_track = axis_inspector_breakdown(
        highway="residential", tags={}, is_designated=False,
        materials=_way_materials(highway="residential", **_NO_BICYCLE_INFRA),
    )
    with_track = axis_inspector_breakdown(
        highway="residential", tags={"cycleway": "track"}, is_designated=False,
        materials=_way_materials(
            highway="residential", **{**_NO_BICYCLE_INFRA, "cycleway_has_track": True},
        ),
    )

    def difficulty(result, axis_id: str) -> float:
        return next(a.difficulty for a in result.axes if a.axis_id == axis_id)

    without_infra = difficulty(without_track, "bicycle_infra_quality")
    with_infra = difficulty(with_track, "bicycle_infra_quality")
    assert without_infra == 100.0
    assert with_infra == 0.0
    # car_stressはhighway種別のみで決まり、自転車インフラの有無では変化しない（T353）。
    assert difficulty(without_track, "car_stress") == difficulty(with_track, "car_stress") == 50.0


def test_axis_inspector_breakdown_missing_count_materials_mark_those_axes_unavailable():
    """事故・停止の材料が欠損なら、その軸だけがavailable=Falseになる。"""
    result = axis_inspector_breakdown(
        highway="residential", tags={}, is_designated=False,
        materials=_way_materials(**_RESIDENTIAL_PAVED),
    )

    by_id = {axis.axis_id: axis for axis in result.axes}
    assert by_id["stop_density"].available is False
    assert by_id["accident"].available is False
    assert by_id["car_stress"].available is True
    assert by_id["surface_q"].available is True
    assert 0.0 < result.covered_weight_fraction < 1.0


def test_axis_inspector_breakdown_unknown_highway_yields_no_usable_composite():
    """判定基準未登録のhighway・材料ほぼ欠損では、車ストレス・路面・停止密度・事故密度が
    すべてavailable=Falseになる。night_difficultyだけは常に加点式でスコアを返すが、
    既定の重みが0.0のため合成コストへは効かない。改善計画T347: bicycle_infra_qualityは
    car_stressのhighway基準値ゲートに依存しないため、唯一weight>0で合成に効く軸として
    availableになる。"""
    result = axis_inspector_breakdown(
        highway="motorway",  # car_stress_levelの判定基準に未登録
        tags={},
        is_designated=False,
        materials=_way_materials(highway="motorway", lit=False, has_tunnel=False, **_NO_BICYCLE_INFRA),
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
        highway="residential", tags={}, is_designated=False, materials=_way_materials(),
    )

    expected_weights = RoutePreference().weights
    for axis in result.axes:
        assert axis.weight == expected_weights[axis.axis_id]


# --- 改善計画T536フォローアップ: 空タイル（Edge0件）混在時のcombine_static_edge_score_matrices ---




def test_has_route_facing_raw_value_excludes_dynamic_material_axes(monkeypatch):
    """生値の列に載せるかの述語のうち、**動的材料の除外**を直接確かめる。

    この分岐は現在の材料カタログでは一度も効かない——唯一の動的材料`wind_drag_ratio`は
    単位を持たず、単位の条件で先に落ちるため。ここでは単位を持つ材料を一時的に動的扱いへ
    差し替え、除外が効くこと自体を固定する（片方の条件だけを消しても気づけるように）。

    静的スコア行列は`weather=None`で組み立てるので、動的材料の生値はNaNになる。
    人へ見せる値にならない列を作ると、タイルごとの列数は揃っていても中身が全部NaNになる。
    """
    axis = AxisDefinition(
        axis_id="synthetic_raw",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="intersection_count_per_km", weight=1.0)],
            breakpoints=[(0.0, 0.0), (200.0, 100.0)],
        ),
        default_weight=0.1,
        label="合成: 単位のある軸",
        category="観測",
    )

    # 単位は定まるので、静的材料のままなら列に載る。
    assert raw_value_unit(axis) is not None
    assert has_route_facing_raw_value(axis) is True

    # 同じ軸でも、参照する材料がリクエスト時決定（動的）になれば載らない。
    monkeypatch.setattr(evaluation_module, "REQUEST_DYNAMIC_MATERIAL_IDS", frozenset({"intersection_count_per_km"}))
    assert has_route_facing_raw_value(axis) is False


def test_has_route_facing_raw_value_excludes_axes_without_a_unit():
    # 単位が定まらない軸（複数材料の重み付き結合等）は、数字を添えても読み手が意味を取れない。
    categorical_axis = AxisDefinition(
        axis_id="synthetic_categorical",
        shape=CategoricalShape(material="surface_good", mapping={"true": 0.0, "false": 80.0}),
        default_weight=0.1,
        label="合成: カテゴリ軸",
        category="観測",
    )

    assert raw_value_unit(categorical_axis) is None
    assert has_route_facing_raw_value(categorical_axis) is False




def test_combine_static_edge_score_matrices_handles_all_empty_tiles():
    # bbox内の全タイルがEdge0件（道路データの無い区画）の場合も例外なく空の結合結果を返す。
    empty_graph = RoadGraph(graph_version="v1", nodes={}, edges={})
    empty_matrix_a = build_static_edge_score_matrix(empty_graph, material_arrays(empty_graph, []))
    empty_matrix_b = build_static_edge_score_matrix(empty_graph, material_arrays(empty_graph, []))

    combined = combine_static_edge_score_matrices([empty_matrix_a, empty_matrix_b])

    assert combined.edge_ids == []
    assert combined.axis_scores.shape == (0, len(empty_matrix_a.axis_ids))


# --- 改善計画T546: EdgeMaterialTable経由でもbuild_static_edge_score_matrixが一致すること ---




def _assert_matrices_equal(a, b) -> None:
    assert a.edge_ids == b.edge_ids
    assert a.axis_ids == b.axis_ids
    for name in ("axis_scores", "distance_m", "bearing_deg", "gradient_percent"):
        left, right = getattr(a, name), getattr(b, name)
        both_nan = np.isnan(left) & np.isnan(right)
        assert ((left == right) | both_nan).all(), name
    assert set(a.hard_filter_flags) == set(b.hard_filter_flags)
    for name, flags_a in a.hard_filter_flags.items():
        assert (flags_a == b.hard_filter_flags[name]).all()






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




def test_compute_routable_node_ids_empty_inputs_return_empty_set():
    graph = RoadGraph(graph_version="v1", nodes={}, edges={})

    routable = compute_routable_node_ids(graph, [], np.array([]))

    assert routable == set()


def test_compose_costs_from_axis_matrix_returns_axis_contributions():
    """改善計画T550: compose_costs_from_axis_matrixが返す3個目の値
    （axis_id→区間ごとの寄与度配列）は、`arr*weight/weighted_weight_sums`（validな軸の
    みで再正規化した重み配分、区間ごとに欠損軸を除いて残りの重みで再正規化する
    compositeの合成式と同じ重み配分）。有効な寄与度の合計は丸め前のcompositeと一致し、
    validでない軸・weighted_weight_sums==0の区間ではNaNになる。"""
    distance_m = np.array([100.0, 200.0, 300.0, 400.0])
    axis_arrays = {
        "wind": np.array([80.0, 20.0, np.nan, np.nan]),
        "car_stress": np.array([10.0, 40.0, 60.0, np.nan]),
    }
    weights = {"wind": 0.6, "car_stress": 0.4}

    cost, composite, contributions, _ = compose_costs_from_axis_matrix(distance_m, axis_arrays, weights)

    assert set(contributions.keys()) == {"wind", "car_stress"}

    # edge0: 両軸ともvalid。wind=80*0.6/1.0=48、car_stress=10*0.4/1.0=4、合計52=composite。
    assert contributions["wind"][0] == pytest.approx(48.0)
    assert contributions["car_stress"][0] == pytest.approx(4.0)
    assert composite[0] == pytest.approx(52.0)

    # edge2: windがNaN（欠損）のため、car_stressの重みだけで再正規化される
    # （欠損軸を除いて残りの重みで再正規化、というcompositeと同じ規約）。
    assert np.isnan(contributions["wind"][2])
    assert contributions["car_stress"][2] == pytest.approx(60.0)
    assert composite[2] == pytest.approx(60.0)

    # edge3: 両軸ともNaN→weighted_weight_sums=0→composite・寄与度ともNaN。
    assert np.isnan(composite[3])
    assert np.isnan(contributions["wind"][3])
    assert np.isnan(contributions["car_stress"][3])

    # 不変条件: 有効な寄与度の合計（丸め前）は、その区間のcomposite（丸め後）と一致する
    # （RouteCandidate.axis_contributionsの合計をoverall_difficultyと一致させる根拠）。
    for i in range(len(distance_m)):
        if np.isnan(composite[i]):
            continue
        valid_total = sum(
            contributions[axis_id][i] for axis_id in contributions if not np.isnan(contributions[axis_id][i])
        )
        assert valid_total == pytest.approx(composite[i], abs=1e-6)


def test_compose_costs_from_axis_matrix_fills_cost_with_bbox_mean_when_all_axes_missing():
    # 改善計画T552: 重み付き軸がすべて欠損（composite=NaN）のEdgeは、costの算出だけ
    # bbox内の他Edgeの距離加重平均difficultyを代入する。表示用のcomposite・
    # axis_contributionsはNaNのまま変わらない。
    distance_m = np.array([100.0, 200.0, 300.0, 400.0])
    axis_arrays = {
        "wind": np.array([80.0, 20.0, np.nan, np.nan]),
        "car_stress": np.array([10.0, 40.0, 60.0, np.nan]),
    }
    weights = {"wind": 0.6, "car_stress": 0.4}

    cost, composite, contributions, _ = compose_costs_from_axis_matrix(distance_m, axis_arrays, weights)

    # composite = [52.0, 28.0, 60.0, NaN]（distance加重平均48.0を欠損Edgeへ代入）。
    bbox_mean = (52.0 * 100.0 + 28.0 * 200.0 + 60.0 * 300.0) / 600.0
    assert np.isnan(composite[3])
    assert np.isnan(contributions["wind"][3])
    assert cost[3] == pytest.approx(distance_m[3] * (1.0 + bbox_mean / 100), abs=1e-6)
    # 欠損していないEdgeのcostはこれまでどおりcomposite自身を使う（bbox平均の影響を
    # 受けない）。
    assert cost[0] == pytest.approx(distance_m[0] * (1.0 + composite[0] / 100), abs=1e-6)


def test_compose_costs_from_axis_matrix_cost_equals_distance_when_all_edges_missing():
    # bbox全体で有効なEdgeが1件も無ければ代入する平均値自体が無いため、従来どおり
    # cost=distance_m（割増なし）。
    distance_m = np.array([100.0, 200.0])
    axis_arrays = {"wind": np.array([np.nan, np.nan])}
    weights = {"wind": 1.0}

    cost, composite, _, _ = compose_costs_from_axis_matrix(distance_m, axis_arrays, weights)

    assert np.all(np.isnan(composite))
    assert cost.tolist() == distance_m.tolist()




# --- 動的材料（風）の3経路一致 ---


def _wind_axis_on(material_id: str, breakpoints: list[tuple[float, float]]) -> AxisDefinition:
    return AxisDefinition(
        axis_id=f"axis_{material_id}",
        shape=BreakpointLinearShape(terms=[MaterialTerm(material=material_id)], breakpoints=breakpoints),
        default_weight=0.5,
        label=f"テスト風軸({material_id})",
        category="動的",
        is_published=True,
    )


def _bearing_graph() -> RoadGraph:
    nodes = {
        "a": Node(node_id="a", latitude=35.0, longitude=139.0),
        "b": Node(node_id="b", latitude=35.001, longitude=139.001),
    }
    edges = {
        f"e{i}": DirectedEdge(
            edge_id=f"e{i}", from_node_id="a", to_node_id="b", geometry=[[35.0, 139.0], [35.001, 139.001]],
            distance_m=120.0, osm_way_id=i, highway="residential", bearing_deg=bearing,
        )
        for i, bearing in enumerate([0.0, 45.0, 90.0, 180.0, 300.0, None])
    }
    return RoadGraph(graph_version="test", nodes=nodes, edges=edges)


def test_dynamic_material_evaluators_cover_every_request_dynamic_material():
    from app.domain.axis_definitions import REQUEST_DYNAMIC_MATERIAL_IDS
    from app.domain.dynamic_materials import DYNAMIC_MATERIAL_EVALUATORS

    assert set(DYNAMIC_MATERIAL_EVALUATORS) == set(REQUEST_DYNAMIC_MATERIAL_IDS)






# --- 内訳の材料列（T689） ---


def test_route_facing_material_ids_excludes_undecomposable_and_categorical_materials():
    from app.domain.evaluation import route_facing_material_ids

    material_ids = route_facing_material_ids()

    # 分解する軸の葉の材料は載る（夜間・停止密度・開放度）。
    assert "lit" in material_ids
    assert "trees_percent" in material_ids
    # 軸参照を辿った先の材料も載る（車の圧迫感の内部軸経由）。
    assert "maxspeed_kmh" in material_ids
    # 1材料へ分解される軸の材料は載らない（軸単位の生値で足りる）。
    assert "gradient_percent" not in material_ids
    assert "wind_drag_ratio" not in material_ids
    # categorical材料は数値行列へ載らない（値ごとの延長割合は別の器が要る）。
    assert "highway" not in material_ids
    # 動的材料は静的スコア行列では全行NaNになるため載らない。
    assert "wind_drag_ratio" not in material_ids




# --- 内訳のcategorical材料（T718） ---


def test_route_facing_categorical_material_ids_holds_only_categorical_leaves():
    from app.domain.evaluation import route_facing_categorical_material_ids, route_facing_material_ids

    categorical = route_facing_categorical_material_ids()

    # 車の圧迫感が内部軸経由で参照するhighway（categorical）。
    assert "highway" in categorical
    # 数値・真偽値の列とは重ならない（同じ材料を2つの器で運ばない）。
    assert not set(categorical) & set(route_facing_material_ids())


