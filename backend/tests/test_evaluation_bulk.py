"""compute_edge_costs_bulk（numpyベクトル化版、改善計画T221/T240）の回帰テスト。

`compute_edge_cost`を1件ずつ呼んだ結果（スカラー版、既存の実装）と`compute_edge_costs_bulk`
（配列版、新実装）が、多様なEdge（highway種別・タグ組み合わせ・欠損データパターンを
網羅する合成グラフ）に対して完全に一致することを確認する。スカラー版は削除しておらず、
本テストのオラクルとして使い続ける。
"""

import itertools
import math
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
from app.domain.material_catalog import (
    EXTRACTABLE_MATERIAL_IDS,
    MATERIAL_CATALOG,
    MaterialExtractionContext,
    resolve_materials,
)
from app.domain.traffic import POI_COUNT_KINDS
from app.domain.evaluation import (
    _evaluate_axes_bulk,
    compute_edge_axis_scores,
    compute_edge_cost,
    compute_edge_costs_bulk,
)
from app.domain.route_preference import RoutePreference
from tests.metrics_fixtures import edge_metrics, merge_metrics
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
                MaterialTerm(material="poi_signal_per_km"),
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
def _synthetic_axis_definitions_only(axes: dict[str, AxisDefinition]):
    """AXIS_DEFINITIONSを`axes`だけへ差し替える（`_SYNTHETIC_AXES`を混ぜない）。"""
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(axes)
        yield axes


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
    wind_speed_ms=5.0,
    wind_direction_deg=45.0,
    wind_direction_label="北東",
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
    way_tags: dict[str, dict[str, str]] = {}
    intersection_counts: dict[str, int] = {}
    accident_counts: dict[str, int] = {}
    landcover: dict[str, tuple[float, float]] = {}
    poi_counts: dict[str, dict[str, float]] = {}
    curvatures: dict[str, float] = {}
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
        # 単一タグ生値の材料（smoothness/tracktype）。11件・13件に1件はタグ自体が無い。
        if idx % 11 != 4:
            tags["smoothness"] = ["good", "bad", "excellent", "intermediate"][idx % 4]
        if idx % 13 != 7:
            tags["tracktype"] = ["grade1", "grade2", "grade3"][idx % 3]
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
        if idx % 5 != 2:
            intersection_counts[edge_id] = idx % 3
        if idx % 6 != 3:
            accident_counts[edge_id] = idx % 4
        # 土地被覆（openness軸の材料）。7件に1件は行自体が無い＝材料欠損。
        if idx % 7 != 5:
            landcover[edge_id] = (float(idx % 101), float((idx * 3) % 101))
        # 蛇行（度/km）。9件に1件は未計算＝材料欠損。
        if idx % 9 != 4:
            curvatures[edge_id] = float((idx * 37) % 1200)
        # 停止要因POIの種別別カウント。8件に1件は未集計（行なし）、それ以外は一部の種別を
        # 省いた辞書（載っていないキーは0件と確定できる、という意味論の確認も兼ねる）。
        if idx % 8 != 6:
            poi_counts[edge_id] = {kind: float((idx + i) % 3) for i, kind in enumerate(POI_COUNT_KINDS) if (idx + i) % 4}
        way_tags[edge_id] = tags
        if idx % 9 == 0:
            designated_edge_ids.add(edge_id)

    graph = RoadGraph(graph_version="test", nodes=nodes, edges=edges)
    # スカラー版（compute_edge_cost）もベクトル版（compute_edge_costs_bulk）も、件数・
    # 土地被覆・停止要因POIを**同じ1つの`metrics`**として受け取る（片方だけスカラー引数で
    # 渡す形にすると、材料を1つ増やしたときに片方だけ取り残されても両方が同じ欠損値を
    # 返して「一致した」と誤判定しうる）。
    metrics = merge_metrics(
        *(
            edge_metrics(
                edge_id,
                intersection=intersection_counts.get(edge_id),
                accident=accident_counts.get(edge_id),
                poi=poi_counts.get(edge_id),
                trees=landcover.get(edge_id, (None, None))[0],
                built=landcover.get(edge_id, (None, None))[1],
                curvature=curvatures.get(edge_id),
            )
            for edge_id in edges
        )
    )

    materials = dict(
        elevation_attributes=elevation_attributes,
        surface_attributes=surface_attributes,
        way_tags=way_tags,
        designated_edge_ids=designated_edge_ids,
        metrics=metrics,
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
            way_tags=materials["way_tags"].get(edge_id),
            metrics=materials["metrics"],
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
        way_tags=materials["way_tags"],
        metrics=materials["metrics"],
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
            way_tags=materials["way_tags"].get(edge_id),
            metrics=materials["metrics"],
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
        way_tags=materials["way_tags"],
        metrics=materials["metrics"],
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


def _single_material_axis(material_id: str) -> AxisDefinition:
    """材料1つだけを見る合成軸。dtypeごとに、その材料の値がそのまま結果へ現れる最小の
    shapeを選ぶ（材料が片方の経路へ届いていなければ、その軸だけが欠損して差が出る）。"""
    dtype = MATERIAL_CATALOG[material_id].dtype
    if dtype == "categorical":
        # 実データに現れる値を網羅する必要はない（未登録値・欠損はどちらの経路でも
        # 同じく「該当なし」になる）。値が届いているかどうかだけを見る。
        return AxisDefinition(
            axis_id=f"wiring_{material_id}",
            shape=CategoricalShape(
                material=material_id,
                mapping={value: float(10 * (i + 1)) for i, value in enumerate(_CATEGORICAL_PROBE_VALUES[material_id])},
            ),
            default_weight=1.0,
            label=material_id,
            is_published=True,
        )
    breakpoints = [(0.0, 0.0), (1.0, 100.0)] if dtype == "boolean" else [(-100.0, 0.0), (100.0, 100.0)]
    return AxisDefinition(
        axis_id=f"wiring_{material_id}",
        shape=BreakpointLinearShape(terms=[MaterialTerm(material=material_id)], breakpoints=breakpoints),
        default_weight=1.0,
        label=material_id,
        is_published=True,
    )


# categorical材料の探り値（`_build_diverse_graph`が実際にタグへ入れる値のうち代表的なもの）。
_CATEGORICAL_PROBE_VALUES: dict[str, tuple[str, ...]] = {
    "highway": ("residential", "primary", "cycleway"),
    "surface": ("asphalt", "gravel", "paved"),
    "smoothness": ("good", "bad"),
    "tracktype": ("grade1", "grade3"),
}


def test_every_extractable_material_reaches_both_paths():
    """extractorを持つ全材料について、その材料だけを見る合成軸を作り、スカラー経路
    （`compute_edge_axis_scores`）とベクトル経路（`_evaluate_axes_bulk`）が軸ごとに
    一致することを確認する。

    材料の解決はどちらの経路も`MATERIAL_CATALOG`のextractor宣言1つから行うが、
    「経路ごとに材料の一覧を手書きする」形へ戻ると、片方の経路にだけ材料が届かず、
    その材料を使う軸が**その経路でだけ**静かに欠損する。合成コストではなく軸ごとの
    difficultyを突き合わせるのは、(1) 材料1件＝軸1本にして「どの材料か」を差の形で
    特定できるようにするため、(2) 合成コストの比較は多数の軸を足し合わせる順序差
    （Neumaier補償加算とPythonのfloat加算）で0.1程度の丸め差が出うるため。
    """
    graph, materials = _build_diverse_graph()
    axes = {f"wiring_{m}": _single_material_axis(m) for m in EXTRACTABLE_MATERIAL_IDS}

    with _synthetic_axis_definitions_only(axes):
        scalar_scores = {
            edge_id: compute_edge_axis_scores(
                edge,
                materials["elevation_attributes"].get(edge_id),
                materials["surface_attributes"].get(edge_id),
                way_tags=materials["way_tags"].get(edge_id),
                metrics=materials["metrics"],
                accident_years_covered=3,
                is_designated=edge_id in materials["designated_edge_ids"],
            )
            for edge_id, edge in graph.edges.items()
        }
        bulk = _evaluate_axes_bulk(
            graph,
            materials["elevation_attributes"],
            materials["surface_attributes"],
            None,
            None,
            materials["way_tags"],
            3,
            materials["designated_edge_ids"],
            materials["metrics"],
        )

    mismatches: list[str] = []
    for row, edge_id in enumerate(bulk.edge_ids):
        for axis_id, array in bulk.axis_arrays.items():
            bulk_value = array[row]
            scalar_value = scalar_scores[edge_id].get(axis_id)
            if math.isnan(bulk_value):
                if scalar_value is not None:
                    mismatches.append(f"{axis_id}/{edge_id}: bulk=欠損 scalar={scalar_value}")
            elif scalar_value is None:
                mismatches.append(f"{axis_id}/{edge_id}: bulk={bulk_value} scalar=欠損")
            # 値の一致は「欠損かどうか」に比べて緩い許容（1段階＝0.1）で見る。両経路は
            # difficultyを小数1桁へ丸めるが、丸め前の値が.x5ちょうどに乗ると
            # numpy（`round1_array`）とPython組み込み`round`で最後の桁が1つずれうる。
            # 値そのものの厳密一致は`test_bulk_matches_scalar_for_every_edge`（合成コスト
            # まで含めた突き合わせ）が担当し、ここは配線の有無を見る。
            elif abs(bulk_value - scalar_value) > 0.1 + 1e-9:
                mismatches.append(f"{axis_id}/{edge_id}: bulk={bulk_value} scalar={scalar_value}")
    assert not mismatches, f"{len(mismatches)}件不一致: {mismatches[:5]}"


def test_diverse_graph_actually_supplies_every_extractable_material():
    """上のテストが空振り（全材料が両経路とも欠損で一致）にならないことの確認。

    `_build_diverse_graph`が材料を1件も供給していない場合、両経路とも同じNaNを返して
    「一致」してしまう。材料ごとに、少なくとも1本のEdgeで値が求まることを別途固定する。
    """
    graph, materials = _build_diverse_graph()
    supplied: set[str] = set()
    for edge_id, edge in graph.edges.items():
        resolved = resolve_materials(
            MaterialExtractionContext(
                edge_id=edge_id,
                highway=edge.highway,
                way_tags=materials["way_tags"].get(edge_id),
                distance_km=edge.distance_m / 1000,
                elevation_attributes=materials["elevation_attributes"],
                surface_attributes=materials["surface_attributes"],
                designated_edge_ids=materials["designated_edge_ids"],
                metrics=materials["metrics"],
                accident_years_covered=3,
            )
        )
        supplied.update(material_id for material_id, value in resolved.items() if value is not None)

    missing = sorted(set(EXTRACTABLE_MATERIAL_IDS) - supplied)
    assert not missing, f"パリティテストのグラフが値を1件も供給していない材料: {missing}"
