"""軸の階層構造（改善計画T292）の基盤機構のテスト。

- `priority_overrides`（0次条件）: shape計算をスキップして値を確定させる機構
  （`evaluate_axis_scalar`/`evaluate_axis_array`）。
- `topological_axis_order`/`axis_dependencies`: 軸が他の軸をmaterialとして参照する
  依存関係を解決する順序決定（循環参照はAxisDependencyCycleError）。
- `compute_edge_axis_scores`が実際にこの依存順評価を使い、内部軸→公開軸の階層を
  1回のcompute_edge_axis_scores呼び出しで再現できることの統合確認。

車ストレス軸自体の内部軸への再定義（改善計画T292の次段階）はここでは扱わない。
本ファイルは階層構造を支える汎用機構だけを検証する。
"""

import numpy as np
import pytest

from app.domain.attributes import ElevationAttribute
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    AxisDependencyCycleError,
    BreakpointLinearShape,
    MaterialTerm,
    PriorityCondition,
    axis_dependencies,
    evaluate_axis_array,
    evaluate_axis_scalar,
    topological_axis_order,
)
from app.domain.evaluation import compute_edge_axis_scores
from app.domain.graph import DirectedEdge


def _linear_axis(
    axis_id: str,
    material: str,
    priority_overrides: list[PriorityCondition] | None = None,
    is_published: bool = False,
) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material=material)], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label=f"テスト軸[{axis_id}]",
        priority_overrides=priority_overrides or [],
        is_published=is_published,
    )


# --- CategoricalShapeのstrキー対応（改善計画T292、highway/bicycle_infra等の多値材料） ---


def _categorical_axis(axis_id: str, material: str, mapping: dict) -> AxisDefinition:
    from app.domain.axis_definitions import CategoricalShape

    return AxisDefinition(
        axis_id=axis_id,
        shape=CategoricalShape(material=material, mapping=mapping),
        default_weight=0.1,
        label=f"テスト軸[{axis_id}]",
        is_published=False,
    )


def test_evaluate_axis_scalar_categorical_shape_accepts_str_keys():
    definition = _categorical_axis("test", "bicycle_infra", {"separated": -2.0, "lane": -1.0, "roadway": 1.0})
    assert evaluate_axis_scalar(definition, {"bicycle_infra": "separated"}) == -2.0
    assert evaluate_axis_scalar(definition, {"bicycle_infra": "roadway"}) == 1.0


def test_evaluate_axis_scalar_categorical_shape_unmatched_str_is_none():
    definition = _categorical_axis("test", "bicycle_infra", {"separated": -2.0})
    assert evaluate_axis_scalar(definition, {"bicycle_infra": "prohibited"}) is None


def test_evaluate_axis_array_categorical_shape_accepts_str_keys():
    definition = _categorical_axis("test", "bicycle_infra", {"separated": -2.0, "lane": -1.0, "roadway": 1.0})
    materials = {"bicycle_infra": np.array(["separated", "roadway", "unknown"], dtype=object)}
    result = evaluate_axis_array(definition, materials)
    assert result[0] == -2.0
    assert result[1] == 1.0
    assert np.isnan(result[2])


def test_evaluate_axis_array_categorical_shape_still_accepts_bool_keys():
    # 既存軸（surface_q等）のbool材料が引き続き正しく動くことの回帰確認。
    definition = _categorical_axis("test", "surface_good", {True: 0.0, False: 80.0})
    materials = {"surface_good": np.array([True, False])}
    result = evaluate_axis_array(definition, materials)
    assert result[0] == 0.0
    assert result[1] == 80.0


# --- priority_overrides（0次条件） ---


def test_evaluate_axis_scalar_priority_override_short_circuits_shape():
    definition = _linear_axis(
        "test",
        "raw_material",
        priority_overrides=[PriorityCondition(material="bicycle_infra", equals="prohibited", value=999.0)],
    )
    assert evaluate_axis_scalar(definition, {"raw_material": 5.0, "bicycle_infra": "prohibited"}) == 999.0


def test_evaluate_axis_scalar_priority_override_falls_through_when_not_matching():
    definition = _linear_axis(
        "test",
        "raw_material",
        priority_overrides=[PriorityCondition(material="bicycle_infra", equals="prohibited", value=999.0)],
    )
    # raw_material=5.0はbreakpoints(0,0)-(10,100)の中間なので通常計算で50.0になる。
    assert evaluate_axis_scalar(definition, {"raw_material": 5.0, "bicycle_infra": "lane"}) == 50.0


def test_evaluate_axis_scalar_priority_override_missing_material_falls_through():
    definition = _linear_axis(
        "test",
        "raw_material",
        priority_overrides=[PriorityCondition(material="bicycle_infra", equals="prohibited", value=999.0)],
    )
    assert evaluate_axis_scalar(definition, {"raw_material": 5.0}) == 50.0


def test_evaluate_axis_scalar_priority_override_matches_bool_material():
    # motor_vehicle_no等のbool材料はPythonのTrue/Falseがそのままmaterialsへ入る。
    # PriorityCondition.equalsは文字列固定("true"/"false")なので正規化して比較する
    # （改善計画T292、最初の適用例）。
    definition = _linear_axis(
        "test",
        "raw_material",
        priority_overrides=[PriorityCondition(material="motor_vehicle_no", equals="true", value=0.0)],
    )
    assert evaluate_axis_scalar(definition, {"raw_material": 5.0, "motor_vehicle_no": True}) == 0.0
    assert evaluate_axis_scalar(definition, {"raw_material": 5.0, "motor_vehicle_no": False}) == 50.0


def test_evaluate_axis_scalar_priority_override_first_match_wins():
    definition = _linear_axis(
        "test",
        "raw_material",
        priority_overrides=[
            PriorityCondition(material="flag_a", equals="x", value=1.0),
            PriorityCondition(material="flag_b", equals="y", value=2.0),
        ],
    )
    materials = {"raw_material": 5.0, "flag_a": "x", "flag_b": "y"}
    assert evaluate_axis_scalar(definition, materials) == 1.0


def test_evaluate_axis_array_priority_override_short_circuits_shape():
    definition = _linear_axis(
        "test",
        "raw_material",
        priority_overrides=[PriorityCondition(material="bicycle_infra", equals="prohibited", value=999.0)],
    )
    materials = {
        "raw_material": np.array([5.0, 5.0]),
        "bicycle_infra": np.array(["prohibited", "lane"], dtype=object),
    }
    result = evaluate_axis_array(definition, materials)
    assert result[0] == 999.0
    assert result[1] == 50.0


def test_evaluate_axis_array_priority_override_matches_bool_material():
    definition = _linear_axis(
        "test",
        "raw_material",
        priority_overrides=[PriorityCondition(material="motor_vehicle_no", equals="true", value=0.0)],
    )
    materials = {
        "raw_material": np.array([5.0, 5.0]),
        "motor_vehicle_no": np.array([True, False]),
    }
    result = evaluate_axis_array(definition, materials)
    assert result[0] == 0.0
    assert result[1] == 50.0


def test_evaluate_axis_array_priority_override_first_match_wins():
    definition = _linear_axis(
        "test",
        "raw_material",
        priority_overrides=[
            PriorityCondition(material="flag_a", equals="x", value=1.0),
            PriorityCondition(material="flag_b", equals="y", value=2.0),
        ],
    )
    materials = {
        "raw_material": np.array([5.0]),
        "flag_a": np.array(["x"], dtype=object),
        "flag_b": np.array(["y"], dtype=object),
    }
    result = evaluate_axis_array(definition, materials)
    assert result[0] == 1.0


# --- topological_axis_order / axis_dependencies ---


def test_topological_axis_order_orders_dependencies_before_dependents():
    definitions = {
        "c": _linear_axis("c", "b"),
        "a": _linear_axis("a", "raw_material"),
        "b": _linear_axis("b", "a"),
    }
    order = topological_axis_order(definitions)
    assert order.index("a") < order.index("b") < order.index("c")


def test_topological_axis_order_preserves_insertion_order_when_no_dependencies():
    # 既存7軸のように軸間参照が無い場合、挿入順のまま返る（compute_edge_axis_scoresの
    # 出力順・浮動小数点の加算順が既存挙動から変わらないことの確認、改善計画T292）。
    definitions = {"a": _linear_axis("a", "m1"), "b": _linear_axis("b", "m2"), "c": _linear_axis("c", "m3")}
    assert topological_axis_order(definitions) == ["a", "b", "c"]


def test_topological_axis_order_raises_on_direct_cycle():
    definitions = {"x": _linear_axis("x", "y"), "y": _linear_axis("y", "x")}
    with pytest.raises(AxisDependencyCycleError):
        topological_axis_order(definitions)


def test_topological_axis_order_raises_on_self_reference():
    definitions = {"x": _linear_axis("x", "x")}
    with pytest.raises(AxisDependencyCycleError):
        topological_axis_order(definitions)


def test_axis_dependencies_ignores_material_catalog_entries():
    definition = _linear_axis("public_axis", "gradient_percent")
    assert axis_dependencies(definition, known_axis_ids={"gradient", "public_axis"}) == set()


def test_axis_dependencies_returns_referenced_axis_ids():
    definition = _linear_axis("public_axis", "internal_axis")
    assert axis_dependencies(definition, known_axis_ids={"internal_axis", "public_axis"}) == {"internal_axis"}


# --- compute_edge_axis_scoresの統合確認（内部軸→公開軸の階層が実際に解決される） ---


@pytest.fixture
def isolated_axis_definitions():
    # AXIS_DEFINITIONSはプロセス全体で共有されるグローバル辞書のため、他のテストへ
    # 汚染が漏れないよう必ずスナップショット・復元する（test_axis_registry_service.py:
    # restore_axis_definitionsと同じパターン）。
    snapshot = dict(AXIS_DEFINITIONS)
    yield AXIS_DEFINITIONS
    AXIS_DEFINITIONS.clear()
    AXIS_DEFINITIONS.update(snapshot)


def _edge() -> DirectedEdge:
    return DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-2",
        geometry=[[35.700, 139.700], [35.701, 139.700]],
        distance_m=100.0,
        osm_way_id=1,
        highway="residential",
    )


def test_compute_edge_axis_scores_resolves_internal_axis_reference(isolated_axis_definitions):
    # internal_a（非公開）はgradient_percentから、public_b（公開）はinternal_aの結果値
    # そのものから計算する2段構成。1回のcompute_edge_axis_scores呼び出しで両方の値が
    # 正しく（依存順に）解決されることを確認する。
    isolated_axis_definitions.clear()
    isolated_axis_definitions.update(
        {
            "internal_a": AxisDefinition(
                axis_id="internal_a",
                shape=BreakpointLinearShape(
                    terms=[MaterialTerm(material="gradient_percent")],
                    preprocess="abs",
                    breakpoints=[(0.0, 0.0), (10.0, 100.0)],
                ),
                default_weight=0.1,
                label="内部軸A",
                is_published=False,
            ),
            "public_b": AxisDefinition(
                axis_id="public_b",
                shape=BreakpointLinearShape(
                    terms=[MaterialTerm(material="internal_a")],
                    breakpoints=[(0.0, 0.0), (100.0, 100.0)],
                ),
                default_weight=0.1,
                label="公開軸B",
                is_published=True,
            ),
        }
    )
    elevation = ElevationAttribute(edge_id="edge-1", average_grade=5.0, data_source="test", calculated_at="t")

    scores = compute_edge_axis_scores(_edge(), elevation, surface_type=None)

    # 改善計画T292: compute_edge_axis_scoresの返り値は公開軸のみに絞る（内部軸は
    # 実装詳細のため含めない）。internal_aが正しく計算されたことは、それを参照する
    # public_bの値（50.0）を通じて間接的に確認する。
    assert "internal_a" not in scores
    assert scores["public_b"] == 50.0


def test_compute_edge_axis_scores_resolves_priority_override_through_hierarchy(isolated_axis_definitions):
    # internal_a（0次条件でsurface_good=trueなら0固定、bool材料での0次条件）
    # →public_bが内部軸の結果をそのまま材料として使う。0次条件が階層越しでも
    # 正しく効くことを確認する（surface_goodはcompute_edge_axis_scoresが実際に
    # 解決するbool材料、改善計画T292）。
    isolated_axis_definitions.clear()
    isolated_axis_definitions.update(
        {
            "internal_a": AxisDefinition(
                axis_id="internal_a",
                shape=BreakpointLinearShape(
                    terms=[MaterialTerm(material="gradient_percent")],
                    preprocess="abs",
                    breakpoints=[(0.0, 0.0), (10.0, 100.0)],
                ),
                default_weight=0.1,
                label="内部軸A",
                is_published=False,
                priority_overrides=[PriorityCondition(material="surface_good", equals="true", value=0.0)],
            ),
            "public_b": AxisDefinition(
                axis_id="public_b",
                shape=BreakpointLinearShape(
                    terms=[MaterialTerm(material="internal_a")],
                    breakpoints=[(0.0, 0.0), (100.0, 100.0)],
                ),
                default_weight=0.1,
                label="公開軸B",
                is_published=True,
            ),
        }
    )
    elevation = ElevationAttribute(edge_id="edge-1", average_grade=5.0, data_source="test", calculated_at="t")

    # surface_type="asphalt"はclassify_osm_surfaceでTrue(良路面)と判定される
    # （domain/road.py: GOOD_OSM_SURFACE_TAGS）ため、materials["surface_good"]=Trueになる。
    overridden = compute_edge_axis_scores(_edge(), elevation, surface_type="asphalt")
    assert overridden["public_b"] == 0.0

    # 非舗装（surface_good=False）なら0次条件が発火せず通常のshape計算になる。
    not_overridden = compute_edge_axis_scores(_edge(), elevation, surface_type="ground")
    assert not_overridden["public_b"] == 50.0
