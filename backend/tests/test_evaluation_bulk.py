"""compute_edge_costs_bulk（numpyベクトル化版、改善計画T221/T240）の回帰テスト。

`compute_edge_cost`を1件ずつ呼んだ結果（スカラー版、既存の実装）と`compute_edge_costs_bulk`
（配列版、新実装）が、多様なEdge（highway種別・タグ組み合わせ・欠損データパターンを
網羅する合成グラフ）に対して完全に一致することを確認する。スカラー版は削除しておらず、
本テストのオラクルとして使い続ける。
"""

import itertools
from contextlib import contextmanager

import pytest

from app.domain.attributes import ElevationAttribute
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
from app.domain.evaluation import (
    RoutePreference,
    compute_edge_cost,
    compute_edge_costs_bulk,
)
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.weather import WeatherConditions
from app.domain.wind import kmh_to_ms
from tests.realistic_axis_fixtures import axis_definitions_snapshot

# 改善計画T350: AXIS_DEFINITIONSのPython literal撤去に伴い、本ファイルは
# compute_edge_cost（スカラー版）とcompute_edge_costs_bulk（配列版）の一致を検証する
# ことが目的であって実運用の軸の値を検証したいわけではないため、実軸データを使わず
# テストファイル内で定義した合成軸データへ書き換えた。shapeの種類（BreakpointLinear
# [preprocess="abs"あり/なし・単項/複数項・必須/任意項]・Categorical・FlagSum・
# 軸参照[car_stressが内部軸を参照する階層構造]）は実運用の8軸構成をなるべく再現し、
# 検証したいコードパスの網羅性を落とさないようにしている。materialは実在の
# MATERIAL_CATALOGエントリ（AXIS_DEFINITIONSとは別レジストリのため実データのまま）。

_INTERNAL_AXIS = AxisDefinition(
    axis_id="test_internal_axis",
    # _build_diverse_graph()のhighways一覧（下記）と対応させる。motorwayは本番でも
    # 未登録（ハードフィルタで除外される想定のためcar_stress自体は評価されない）、
    # None/unknown_highwayは意図的に「欠損・未知カテゴリ」経路を検証する値のため、
    # cycleway（本番のhighway基準値では1.0）だけがcategorical分岐の実際のカバレッジに
    # 必要な追加キー。
    shape=CategoricalShape(
        material="highway", mapping={"cycleway": 1.0, "residential": 1.0, "primary": 3.0, "trunk": 4.0}
    ),
    default_weight=0.0,
    label="テスト内部軸",
    category="推定",
    is_published=False,
)

_SYNTHETIC_AXES: dict[str, AxisDefinition] = {
    "gradient": AxisDefinition(
        axis_id="gradient",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (15.0, 100.0)],
        ),
        default_weight=0.15,
        label="テスト勾配",
        category="観測",
        is_published=True,
    ),
    "wind": AxisDefinition(
        axis_id="wind",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="wind_drag_ratio")],
            breakpoints=[(0.0, 0.0), (5.0, 100.0)],
        ),
        default_weight=0.26,
        label="テスト風",
        category="動的",
        is_published=True,
    ),
    "surface_q": AxisDefinition(
        axis_id="surface_q",
        shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
        default_weight=0.19,
        label="テスト舗装質",
        category="観測",
        is_published=True,
    ),
    "stop_density": AxisDefinition(
        axis_id="stop_density",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="stop_count_per_km"),
                MaterialTerm(material="intersection_count_per_km", weight=0.3, required=False),
            ],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="テスト停止密度",
        category="観測",
        is_published=True,
    ),
    "test_internal_axis": _INTERNAL_AXIS,
    "car_stress": AxisDefinition(
        axis_id="car_stress",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="test_internal_axis", required=True),
                MaterialTerm(material="lanes_count", weight=0.1, required=False),
            ],
            breakpoints=[(1.0, 0.0), (5.0, 100.0)],
        ),
        default_weight=0.2,
        label="テスト車ストレス",
        category="推定",
        is_published=True,
    ),
    "accident": AxisDefinition(
        axis_id="accident",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="accident_count_per_km_year")],
            breakpoints=[(0.0, 0.0), (0.5, 100.0)],
        ),
        default_weight=0.08,
        label="テスト事故密度",
        category="推定",
        is_published=True,
    ),
    "night": AxisDefinition(
        axis_id="night",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="lit", weight=-50.0),
                MaterialTerm(material="has_tunnel", weight=50.0),
            ],
            breakpoints=[(-50.0, 0.0), (50.0, 100.0)],
        ),
        default_weight=0.0,
        label="テスト夜間",
        category="観測",
        is_published=True,
    ),
}


@contextmanager
def _synthetic_axis_definitions(extra: dict[str, AxisDefinition] | None = None):
    """AXIS_DEFINITIONSの中身を一時的に合成軸セットへ差し替える（テスト終了後に復元）。

    改善計画T350のcode-review対応: スナップショット/復元の仕組み自体は
    tests/realistic_axis_fixtures.py: axis_definitions_snapshot()へ集約済み
    （本ファイル・test_axis_registry_service.pyとの3重実装を解消）。ここでは
    「合成軸セット（_SYNTHETIC_AXES + extra）を書き込む」という本ファイル固有の
    部分だけを持つ。
    """
    axes = dict(_SYNTHETIC_AXES)
    if extra:
        axes.update(extra)
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(axes)
        yield axes


@pytest.fixture
def preference(request):
    # 全軸の重みを非ゼロにし、compositeが「一部の軸だけ」で決まらないようにする
    # （デフォルトのnight重み0.0だと夜間軸のバグが合成結果に現れず見逃しうるため）。
    # 改善計画T350のcode-review対応: request.param経由でextra軸を注入できるようにした
    # （@pytest.mark.parametrize("preference", [{...}], indirect=True)）。以前は
    # 末尾2テストがこのフィクスチャを経由せず、同じ3ステップ（軸差し替え・weights計算・
    # RoutePreference構築）を手書きで再実装していた。
    extra = getattr(request, "param", None)
    with _synthetic_axis_definitions(extra) as axes:
        yield RoutePreference(weights={axis_id: 1.0 for axis_id, d in axes.items() if d.is_published})

WIND = WeatherConditions(
    temperature_c=20.0,
    apparent_temperature_c=None,
    wind_speed_ms=5.0,
    wind_direction_deg=45.0,
    wind_direction_label="北東",
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


def _build_diverse_graph() -> tuple[RoadGraph, dict]:
    """highway種別・cycleway・maxspeed・lanes・motor_vehicle・designation・lit/tunnel・
    欠損データパターンの組み合わせで多数のEdgeを作る。materials（way_tags等）も併せて返す。
    """
    highways = ["residential", "primary", "trunk", "motorway", "cycleway", None, "unknown_highway"]
    cycleways = [None, "track", "lane", "shared_lane"]
    maxspeeds = [None, "20", "50", "not_a_number"]
    lanes_variants = [None, "1", "2", "6"]
    bicycle_no = [False, True]
    motor_vehicle_no = [False, True]
    lit = [None, "yes", "no"]
    tunnel = [None, "yes"]

    nodes: dict[str, Node] = {}
    edges: dict[str, DirectedEdge] = {}
    elevation_attributes: dict[str, ElevationAttribute] = {}
    surface_attributes: dict[str, str | None] = {}
    stop_counts: dict[str, int] = {}
    way_tags: dict[str, dict[str, str]] = {}
    intersection_counts: dict[str, int] = {}
    accident_counts: dict[str, int] = {}
    designated_edge_ids: set[str] = set()

    combos = list(
        itertools.product(highways, cycleways, maxspeeds, lanes_variants, bicycle_no, motor_vehicle_no, lit, tunnel)
    )
    # 全組み合わせは大きすぎるため、間引いて代表サンプルを取る（それでも数百件规模）。
    combos = combos[::7]

    lat = 35.0
    for idx, (highway, cycleway, maxspeed, lanes, bike_no, mv_no, lit_val, tunnel_val) in enumerate(combos):
        edge_id = f"e{idx}"
        from_id = f"n{idx}a"
        to_id = f"n{idx}b"
        lat += 0.001
        nodes[from_id] = Node(node_id=from_id, latitude=lat, longitude=139.0)
        nodes[to_id] = Node(node_id=to_id, latitude=lat, longitude=139.001)

        tags: dict[str, str] = {}
        if cycleway is not None:
            tags["cycleway"] = cycleway
        if maxspeed is not None:
            tags["maxspeed"] = maxspeed
        if lanes is not None:
            tags["lanes"] = lanes
        if bike_no:
            tags["bicycle"] = "no"
        if mv_no:
            tags["motor_vehicle"] = "no"
        if lit_val is not None:
            tags["lit"] = lit_val
        if tunnel_val is not None:
            tags["tunnel"] = tunnel_val

        bearing_deg = float(idx % 360) if idx % 5 != 0 else None
        distance_m = 50.0 + (idx % 20) * 37.3
        edges[edge_id] = DirectedEdge(
            edge_id=edge_id,
            from_node_id=from_id,
            to_node_id=to_id,
            geometry=[[lat, 139.0], [lat, 139.001]],
            distance_m=distance_m,
            osm_way_id=idx,
            highway=highway,
            bearing_deg=bearing_deg,
        )

        # データ欠損パターンを織り交ぜる（3件に1件は各材料を欠損させる）。
        if idx % 3 != 0:
            elevation_attributes[edge_id] = ElevationAttribute(
                edge_id=edge_id,
                average_grade=((idx % 40) - 20) * 0.7,
                data_source="test",
                calculated_at="t",
            )
        if idx % 4 != 0:
            surface_attributes[edge_id] = ["asphalt", "paved", "gravel", "unknown_surface", None][idx % 5]
        if idx % 3 != 1:
            stop_counts[edge_id] = idx % 5
        if idx % 5 != 2:
            intersection_counts[edge_id] = idx % 3
        if idx % 6 != 3:
            accident_counts[edge_id] = idx % 4
        way_tags[edge_id] = tags
        if idx % 9 == 0:
            designated_edge_ids.add(edge_id)

    graph = RoadGraph(graph_version="test", nodes=nodes, edges=edges)
    materials = dict(
        elevation_attributes=elevation_attributes,
        surface_attributes=surface_attributes,
        stop_counts=stop_counts,
        way_tags=way_tags,
        intersection_counts=intersection_counts,
        accident_counts=accident_counts,
        designated_edge_ids=designated_edge_ids,
    )
    return graph, materials


@pytest.mark.parametrize(
    ("weather", "travel_speed_ms"), [(None, None), (WIND, kmh_to_ms(20.0)), (WIND, kmh_to_ms(35.0))]
)
@pytest.mark.parametrize("max_average_grade_percent", [None, 8.0])
@pytest.mark.parametrize("penalty_strength", [1.0, 2.5])
def test_bulk_matches_scalar_for_every_edge(
    preference, weather, travel_speed_ms, max_average_grade_percent, penalty_strength
):
    graph, materials = _build_diverse_graph()
    weights = preference.weights

    scalar_results = {
        edge_id: compute_edge_cost(
            edge,
            materials["elevation_attributes"].get(edge_id),
            materials["surface_attributes"].get(edge_id),
            preference,
            weights=weights,
            weather=weather,
            travel_speed_ms=travel_speed_ms,
            stop_count=materials["stop_counts"].get(edge_id),
            way_tags=materials["way_tags"].get(edge_id),
            intersection_count=materials["intersection_counts"].get(edge_id),
            accident_count=materials["accident_counts"].get(edge_id),
            accident_years_covered=3,
            is_designated=edge_id in materials["designated_edge_ids"],
            penalty_strength=penalty_strength,
            max_average_grade_percent=max_average_grade_percent,
        )
        for edge_id, edge in graph.edges.items()
    }

    bulk_results = compute_edge_costs_bulk(
        graph,
        materials["elevation_attributes"],
        materials["surface_attributes"],
        preference,
        weather=weather,
        travel_speed_ms=travel_speed_ms,
        stop_counts=materials["stop_counts"],
        way_tags=materials["way_tags"],
        intersection_counts=materials["intersection_counts"],
        accident_counts=materials["accident_counts"],
        accident_years_covered=3,
        designated_edge_ids=materials["designated_edge_ids"],
        penalty_strength=penalty_strength,
        max_average_grade_percent=max_average_grade_percent,
        weights=weights,
    )

    assert set(bulk_results.keys()) == set(scalar_results.keys())
    mismatches = []
    for edge_id, scalar in scalar_results.items():
        bulk = bulk_results[edge_id]
        if (bulk.allowed, bulk.cost, bulk.difficulty) != (scalar.allowed, scalar.cost, scalar.difficulty):
            mismatches.append((edge_id, scalar, bulk))
    assert not mismatches, f"{len(mismatches)}件不一致: {mismatches[:5]}"


def test_bulk_returns_empty_dict_for_empty_graph(preference):
    graph = RoadGraph(graph_version="test", nodes={}, edges={})
    result = compute_edge_costs_bulk(graph, {}, {}, preference)
    assert result == {}


@pytest.mark.parametrize(
    "hard_filters",
    [frozenset(), frozenset({"no_bicycle"}), frozenset({"motorway"}), frozenset({"no_bicycle", "motorway", "trunk"})],
)
def test_bulk_hard_filters_override_matches_scalar(preference, hard_filters):
    """改善計画T266: hard_filters引数の上書きが、bulk/scalarで同じ結果になることを
    確認する（compute_edge_costs_bulkはこれまでDEFAULT_HARD_FILTERS決め打ちだった、
    かつno_bicycleフィルタはフィルタ名の有効/無効に関わらず常時適用されるバグがあった）。
    """
    graph, materials = _build_diverse_graph()
    weights = preference.weights

    scalar_results = {
        edge_id: compute_edge_cost(
            edge,
            materials["elevation_attributes"].get(edge_id),
            materials["surface_attributes"].get(edge_id),
            preference,
            weights=weights,
            stop_count=materials["stop_counts"].get(edge_id),
            way_tags=materials["way_tags"].get(edge_id),
            intersection_count=materials["intersection_counts"].get(edge_id),
            accident_count=materials["accident_counts"].get(edge_id),
            accident_years_covered=3,
            is_designated=edge_id in materials["designated_edge_ids"],
            hard_filters=hard_filters,
        )
        for edge_id, edge in graph.edges.items()
    }

    bulk_results = compute_edge_costs_bulk(
        graph,
        materials["elevation_attributes"],
        materials["surface_attributes"],
        preference,
        stop_counts=materials["stop_counts"],
        way_tags=materials["way_tags"],
        intersection_counts=materials["intersection_counts"],
        accident_counts=materials["accident_counts"],
        accident_years_covered=3,
        designated_edge_ids=materials["designated_edge_ids"],
        weights=weights,
        hard_filters=hard_filters,
    )

    assert set(bulk_results.keys()) == set(scalar_results.keys())
    mismatches = []
    for edge_id, scalar in scalar_results.items():
        bulk = bulk_results[edge_id]
        if (bulk.allowed, bulk.cost, bulk.difficulty) != (scalar.allowed, scalar.cost, scalar.difficulty):
            mismatches.append((edge_id, scalar, bulk))
    assert not mismatches, f"{len(mismatches)}件不一致: {mismatches[:5]}"


def test_bulk_hard_filters_empty_allows_bicycle_no_edge(preference):
    """no_bicycleフィルタが無効化されている場合、bicycle=noのEdgeも除外されない
    （改善計画T266で修正したバグの直接的な回帰確認）。"""
    graph = RoadGraph(
        graph_version="test",
        nodes={
            "a": Node(node_id="a", latitude=35.0, longitude=139.0),
            "b": Node(node_id="b", latitude=35.0, longitude=139.001),
        },
        edges={
            "e0": DirectedEdge(
                edge_id="e0",
                from_node_id="a",
                to_node_id="b",
                geometry=[[35.0, 139.0], [35.0, 139.001]],
                distance_m=100.0,
                osm_way_id=1,
                highway="residential",
                bearing_deg=0.0,
            )
        },
    )
    way_tags = {"e0": {"bicycle": "no"}}

    excluded = compute_edge_costs_bulk(graph, {}, {}, preference, way_tags=way_tags)
    assert excluded["e0"].allowed is False

    included = compute_edge_costs_bulk(
        graph, {}, {}, preference, way_tags=way_tags, hard_filters=frozenset({"motorway", "trunk"})
    )
    assert included["e0"].allowed is True


_N10_ONLY_AXIS = AxisDefinition(
    axis_id="custom_n10_only_axis",
    shape=BreakpointLinearShape(
        terms=[MaterialTerm(material="is_emergency_transport")],
        breakpoints=[(0.0, 0.0), (1.0, 100.0)],
    ),
    default_weight=1.0,
    label="テスト用N10軸",
    description="",
    category="推定",
    is_published=True,
)


@pytest.mark.parametrize("preference", [{_N10_ONLY_AXIS.axis_id: _N10_ONLY_AXIS}], indirect=True)
def test_bulk_does_not_crash_on_axis_referencing_a_material_without_an_extractor(preference):
    """改善計画T343回帰テスト: `MaterialSpec.extractor=None`の材料（oneway/designation/
    is_emergency_transport/is_critical_logistics、「トリガー付きDEFER」設計原則9）を
    参照する軸（軸スタジオ経由でGUI作成できてしまう——`_check_materials_are_known`は
    `is_known_material`のみ検証しextractor有無は見ない）が読み込まれても、
    `compute_edge_costs_bulk`がKeyErrorでクラッシュしないこと。以前は
    `material_arrays`をextractorありの材料ぶんしか確保しておらず、
    `evaluate_axis_array`の`materials[term.material]`がKeyErrorになっていた
    （スカラー版`evaluate_axis_scalar`は`materials.get(...)`のため発生しない
    非対称性があった）。データが無い材料として恒久的に欠損扱いになる
    （スカラー版と同じグレースフルデグレード）ことも確認する。
    """
    graph = RoadGraph(
        graph_version="test",
        nodes={
            "a": Node(node_id="a", latitude=35.0, longitude=139.0),
            "b": Node(node_id="b", latitude=35.0, longitude=139.001),
        },
        edges={
            "e0": DirectedEdge(
                edge_id="e0",
                from_node_id="a",
                to_node_id="b",
                geometry=[[35.0, 139.0], [35.0, 139.001]],
                distance_m=100.0,
                osm_way_id=1,
                highway="residential",
                bearing_deg=0.0,
            )
        },
    )

    # is_emergency_transportの既定値[bool_default="false"]はFalse（欠損ではなく確定値）
    # のためcustom_n10_only_axis自体は"該当なし"として評価される（0.0）。ここで検証したい
    # 主眼は例外が起きないこと（KeyErrorしないこと）と、他の軸の合成が壊れないこと。
    results = compute_edge_costs_bulk(
        graph, {}, {}, preference, way_tags={"e0": {}}, weights=preference.weights
    )

    assert results["e0"].allowed is True
    assert results["e0"].difficulty is not None
    assert results["e0"].cost is not None


_DESIGNATION_ONLY_AXIS = AxisDefinition(
    axis_id="custom_designation_only_axis",
    shape=CategoricalShape(material="designation", mapping={"emergency_transport": 100.0}),
    default_weight=1.0,
    label="テスト用designation軸",
    description="",
    category="推定",
    is_published=True,
)


@pytest.mark.parametrize("preference", [{_DESIGNATION_ONLY_AXIS.axis_id: _DESIGNATION_ONLY_AXIS}], indirect=True)
def test_bulk_does_not_crash_on_categorical_axis_referencing_a_material_without_an_extractor(preference):
    """上のテストのCategoricalShape版。categorical材料はdtype=objectのnumpy配列
    （np.emptyでNone初期化）のため、boolean/numeric材料とは別の初期化コードパスを通る
    （evaluation.py: material_arraysの構築、dtype分岐参照）。designation
    （dtype="categorical"、extractor未設定）を参照する軸でも同様にクラッシュしないこと。"""
    graph = RoadGraph(
        graph_version="test",
        nodes={
            "a": Node(node_id="a", latitude=35.0, longitude=139.0),
            "b": Node(node_id="b", latitude=35.0, longitude=139.001),
        },
        edges={
            "e0": DirectedEdge(
                edge_id="e0",
                from_node_id="a",
                to_node_id="b",
                geometry=[[35.0, 139.0], [35.0, 139.001]],
                distance_m=100.0,
                osm_way_id=1,
                highway="residential",
                bearing_deg=0.0,
            )
        },
    )

    results = compute_edge_costs_bulk(
        graph, {}, {}, preference, way_tags={"e0": {}}, weights=preference.weights
    )

    assert results["e0"].allowed is True
    assert results["e0"].difficulty is not None
    assert results["e0"].cost is not None
