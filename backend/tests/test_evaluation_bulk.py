"""材料の配列から静的スコア行列を組むまで（`build_static_edge_score_matrix`）の回帰テスト。

本番の評価はDBが導出した材料の列（`MaterialSpec.value_sql`）だけを入力に取る。ここは
その入力を与えて、**全ての材料が軸まで届くこと**と、材料が届かない/持てない場合に
壊れず欠損として畳まれることを見る。値式そのものの正しさは`tests/test_material_sql.py`が
持つ。
"""

from contextlib import contextmanager

import numpy as np
import pytest

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
from app.domain.evaluation import (
    StaticEdgeScoreMatrix,
    build_static_edge_score_matrix,
    combine_static_edge_score_matrices,
)
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.material_catalog import MATERIAL_CATALOG, material_value_sql
from app.domain.route_preference import RoutePreference
from tests.live_evaluation import edge_costs
from tests.material_arrays import material_arrays
from tests.realistic_axis_fixtures import axis_definitions_snapshot


@contextmanager
def _only_axes(axes: dict[str, AxisDefinition]):
    """AXIS_DEFINITIONSを`axes`だけへ差し替える（テスト終了後に復元）。"""
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(axes)
        yield axes


@pytest.fixture
def preference(request):
    """テスト用の軸セットへ差し替え、全軸へ重み1.0を置いたRoutePreferenceを渡す。"""
    with _only_axes(dict(getattr(request, "param", None) or {})) as axes:
        yield RoutePreference(
            weights={axis_id: 1.0 for axis_id, d in axes.items() if d.is_published}
        )


def _one_edge_graph(highway: str | None = "residential") -> RoadGraph:
    return RoadGraph(
        graph_version="test",
        nodes={
            "a": Node(node_id="a", latitude=35.0, longitude=139.0),
            "b": Node(node_id="b", latitude=35.0, longitude=139.001),
        },
        edges={
            "e0": DirectedEdge(
                edge_id="e0", from_node_id="a", to_node_id="b",
                geometry=[[35.0, 139.0], [35.0, 139.001]], distance_m=100.0,
                osm_way_id=1, highway=highway, bearing_deg=0.0,
            )
        },
    )


# --- 0次フィルタの上書き ---


_ANY_AXIS = {
    "test_axis": AxisDefinition(
        axis_id="test_axis",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]
        ),
        default_weight=1.0,
        label="テスト軸",
        is_published=True,
    )
}


@pytest.mark.parametrize("preference", [_ANY_AXIS], indirect=True)
def test_hard_filters_empty_allows_bicycle_no_edge(preference):
    """no_bicycleフィルタが無効化されている場合、bicycle=noの区間も除外されない
    （改善計画T266で修正したバグの直接的な回帰確認）。"""
    graph = _one_edge_graph()
    materials = material_arrays(graph, ["e0"], no_bicycle_edge_ids={"e0"})

    excluded = edge_costs(graph, materials, preference)
    assert excluded["e0"].allowed is False

    included = edge_costs(
        graph, materials, preference, hard_filters=frozenset({"motorway", "trunk"})
    )
    assert included["e0"].allowed is True


# --- 値式を持たない材料を参照する軸 ---


_N10_ONLY_AXIS = {
    "custom_n10_only_axis": AxisDefinition(
        axis_id="custom_n10_only_axis",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="is_emergency_transport")],
            breakpoints=[(0.0, 0.0), (1.0, 100.0)],
        ),
        default_weight=1.0,
        label="テスト用N10軸",
        category="推定",
        is_published=True,
    )
}

_DESIGNATION_ONLY_AXIS = {
    "custom_designation_only_axis": AxisDefinition(
        axis_id="custom_designation_only_axis",
        shape=CategoricalShape(material="designation", mapping={"emergency_transport": 100.0}),
        default_weight=1.0,
        label="テスト用designation軸",
        category="推定",
        is_published=True,
    )
}


@pytest.mark.parametrize(
    "preference", [_N10_ONLY_AXIS, _DESIGNATION_ONLY_AXIS], indirect=True,
    ids=["numeric", "categorical"],
)
def test_axis_referencing_a_material_without_a_value_sql_does_not_crash(preference):
    """改善計画T343回帰テスト: `value_sql`を持たない材料（「トリガー付きDEFER」設計原則9）を
    参照する軸は、軸スタジオ経由でGUI作成できてしまう——`_check_materials_are_known`は
    `is_known_material`のみ検証し、値の求め方があるかは見ない。そのような軸が読み込まれても
    評価が落ちず、データの無い材料として欠損に畳まれることを確認する。numeric/categoricalで
    配列の初期化コードパスが分かれるため両方を通す。
    """
    graph = _one_edge_graph()

    results = edge_costs(graph, material_arrays(graph, ["e0"]), preference)

    assert results["e0"].allowed is True
    assert results["e0"].cost is not None


# --- 全材料が軸まで届くこと ---


# categorical材料の探り値（値そのものに意味は無く、届いたかどうかだけを見る）。
_CATEGORICAL_PROBE_VALUES: dict[str, str] = {
    "highway": "residential",
    "surface": "asphalt",
    "smoothness": "good",
    "tracktype": "grade1",
}


def _single_material_axis(material_id: str) -> AxisDefinition:
    """材料1つだけを見る軸。dtypeごとに、その材料の値がそのまま結果へ現れる最小のshapeを
    選ぶ（材料が行列へ届いていなければ、その軸だけが欠損する）。"""
    dtype = MATERIAL_CATALOG[material_id].dtype
    if dtype == "categorical":
        return AxisDefinition(
            axis_id=f"wiring_{material_id}",
            shape=CategoricalShape(
                material=material_id, mapping={_CATEGORICAL_PROBE_VALUES[material_id]: 50.0}
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


def _probe_value(material_id: str) -> object:
    dtype = MATERIAL_CATALOG[material_id].dtype
    if dtype == "categorical":
        return _CATEGORICAL_PROBE_VALUES[material_id]
    return True if dtype == "boolean" else 1.0


def test_every_material_with_a_value_sql_reaches_the_score_matrix():
    """値式を持つ全材料について、その材料だけを見る軸が値を受け取ることを確認する。

    母集団は`material_value_sql()`——材料を1つ増やせばこのテストの対象も増える。
    材料が行列へ届かなくなると、その材料を使う軸だけが静かに欠損する。
    """
    material_ids = sorted(material_value_sql())
    graph = _one_edge_graph()
    materials = material_arrays(
        graph, ["e0"], {"e0": {material_id: _probe_value(material_id) for material_id in material_ids}}
    )
    axes = {f"wiring_{m}": _single_material_axis(m) for m in material_ids}

    with _only_axes(axes):
        matrix = build_static_edge_score_matrix(graph, materials)

    missing = [
        axis_id
        for column, axis_id in enumerate(matrix.axis_ids)
        if np.isnan(matrix.axis_scores[0, column])
    ]
    assert not missing, f"値を渡したのに軸へ届いていない材料: {missing}"


def test_combine_rejects_matrices_whose_columns_disagree():
    """先頭タイルの列をそのまま全体の列として採用する以上、一致していることを確かめる。

    列数が違えば`np.concatenate`がValueErrorで落ちるが、偶然一致して意味だけ入れ替わると
    例外にならず**別の軸の生値を表示する**。後者を捕まえるために名前で突き合わせる。
    """

    def matrix(raw_ids: list[str]) -> StaticEdgeScoreMatrix:
        return StaticEdgeScoreMatrix(
            edge_ids=["e"],
            axis_ids=["gradient"],
            axis_scores=np.array([[1.0]]),
            distance_m=np.array([1.0]),
            bearing_deg=np.array([np.nan]),
            hard_filter_flags={
                "motorway": np.array([False]),
                "no_bicycle": np.array([False]),
            },
            gradient_percent=np.array([np.nan]),
            mid_lat=np.array([35.0]),
            mid_lon=np.array([139.0]),
            raw_axis_ids=raw_ids,
            axis_raw_values=np.zeros((1, len(raw_ids))),
        )

    with pytest.raises(ValueError, match="raw_axis_ids"):
        combine_static_edge_score_matrices([matrix(["gradient"]), matrix(["stop_density"])])
