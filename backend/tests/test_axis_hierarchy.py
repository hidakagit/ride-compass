"""`domain/axis_definitions.py`——軸が軸を読む階層と、軸の集合（`AXIS_DEFINITIONS`）を相手にする入口。

入口: 依存の解決（`axis_dependencies`・`topological_axis_order`・`dynamic_axis_topological_order`）・全軸の評価
（`evaluate_axes_array`・`evaluate_axes_values`・`evaluate_axes_inputs`）・葉の材料の一次属性（`primary_attribute_ids_for`）・
既定の重みと時間帯（`default_axis_weights`・`time_scoped_weights`）。

ここで見ないもの:
- 軸1本の宣言の検証・評価（折れ点・欠損・対応表・0次条件）と書き込みのガード → `test_axis_definitions.py`
- 循環を管理APIが拒むこと・書いた後の全軸を読み込みと同じ判定へ通すこと → `test_axis_registry_service.py`
- 軸カタログが配る一次属性と気象のチップ → `test_axis_catalog_routes.py`
- `evaluate_axes_values`が返す軸の並び——読み手の区間インスペクタは軸の id で引き、画面は軸カタログの順で出すので、
  並びは外へ出ない（依存の順に評価することは、軸を読む軸の値が出ることが示す）

**材料カタログと軸の集合は差し替える。** 軸の参照か材料かは材料カタログにあるかで決まるので、葉の材料だけを持つ
架空のカタログを与える。軸の集合は見たい階層だけをテストごとに組み立てる。
"""

import math

import numpy as np
import pytest

from app.domain import axis_definitions, material_catalog
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from tests.axis_system_fixture import replaced_axis_definitions

NAN = float("nan")
DYNAMIC = next(iter(axis_definitions.REQUEST_DYNAMIC_MATERIAL_IDS))

pytestmark = pytest.mark.usefixtures("catalog")


def attribute(attr_id: str) -> material_catalog.PrimaryAttributeSpec:
    return material_catalog.PrimaryAttributeSpec(attr_id=attr_id, label=attr_id, geometry="line")


def material(material_id: str, dtype="numeric", primary_attribute=None) -> material_catalog.MaterialSpec:
    return material_catalog.MaterialSpec(
        material_id=material_id,
        label=material_id,
        description=material_id,
        dtype=dtype,
        tile_property=None,
        coverage=material_catalog.CoverageExcluded(reason="テスト用", missing_semantics="unknown"),
        primary_attribute=primary_attribute,
    )


@pytest.fixture
def catalog(monkeypatch):
    attr_x, attr_y = attribute("attr_x"), attribute("attr_y")
    specs = {
        "num_a": material("num_a", primary_attribute=attr_x),
        "num_b": material("num_b", primary_attribute=attr_y),
        "num_c": material("num_c", primary_attribute=attr_x),
        "num_plain": material("num_plain"),
        "cat": material("cat", dtype="categorical"),
        DYNAMIC: material(DYNAMIC),
    }
    monkeypatch.setattr(material_catalog, "MATERIAL_CATALOG", specs)
    return specs


def axis(axis_id: str, *refs: str, published: bool = False, **fields) -> AxisDefinition:
    """`refs`を重み1で足し、0〜10を0〜100へ写す軸。"""
    shape = BreakpointLinearShape(
        terms=[MaterialTerm(material=ref) for ref in refs or ("num_a",)], breakpoints=[(0.0, 0.0), (10.0, 100.0)]
    )
    return AxisDefinition(
        axis_id=axis_id, shape=shape, is_published=published, **{"default_weight": 1.0, "label": axis_id, **fields}
    )


def axes(*definitions: AxisDefinition) -> dict[str, AxisDefinition]:
    return {d.axis_id: d for d in definitions}


class TestDependencies:
    @pytest.mark.parametrize(
        ("definition", "known", "expected"),
        [
            (
                axis("outer", "num_a", "inner", priority_overrides=[PriorityCondition(material="flag_axis", equals="x", value=0.0)]),
                {"inner", "flag_axis", "outer"},
                {"inner", "flag_axis"},
            ),
            (axis("outer", "inner"), {"outer"}, set()),
            (axis("outer", "num_a"), {"num_a", "outer"}, set()),
        ],
        ids=["known-axes", "unknown-axis", "also-a-material"],
    )
    def test_the_known_axes_an_axis_reads_other_than_materials_are_its_dependencies(self, definition, known, expected):
        assert axis_definitions.axis_dependencies(definition, known) == expected


class TestTopologicalOrder:
    def test_axes_no_one_reads_keep_their_given_order_and_a_shared_axis_comes_once(self):
        definitions = axes(axis("first", "inner"), axis("second"), axis("third", "inner"), axis("inner"))

        assert axis_definitions.topological_axis_order(definitions) == ["inner", "first", "second", "third"]

    def test_a_cycle_is_refused_naming_the_axes_around_it(self):
        with pytest.raises(axis_definitions.AxisDependencyCycleError) as caught:
            axis_definitions.topological_axis_order(axes(axis("a", "b"), axis("b", "a")))

        assert caught.value.cycle == ["a", "b", "a"]
        assert "「a」→「b」→「a」" in str(caught.value)

    def test_the_order_follows_the_contents_when_the_same_mapping_is_rewritten(self):
        definitions = axes(axis("a", "b"), axis("b"))
        assert axis_definitions.topological_axis_order(definitions) == ["b", "a"]

        definitions.clear()
        definitions.update(axes(axis("a"), axis("b", "a")))

        assert axis_definitions.topological_axis_order(definitions) == ["a", "b"]


class TestDynamicOrder:
    def test_only_axes_reading_an_hourly_material_directly_or_through_axes_are_listed_in_order(self):
        definitions = axes(
            axis("outer", "num_b", "middle"),
            axis("static", "num_a"),
            axis("middle", "wind"),
            axis("wind", DYNAMIC),
        )

        assert axis_definitions.dynamic_axis_topological_order(definitions) == ["wind", "middle", "outer"]

    def test_the_list_follows_the_contents_when_the_same_mapping_is_rewritten(self):
        definitions = axes(axis("wind", DYNAMIC), axis("other", "num_a"))
        assert axis_definitions.dynamic_axis_topological_order(definitions) == ["wind"]

        definitions.clear()
        definitions.update(axes(axis("wind", "num_a"), axis("other", DYNAMIC)))

        assert axis_definitions.dynamic_axis_topological_order(definitions) == ["other"]


def scores(values) -> list:
    return [None if math.isnan(v) else v for v in np.asarray(values, dtype=float).tolist()]


class TestEvaluateAllAxes:
    def test_an_axis_reads_the_score_of_the_axis_it_refers_to(self):
        with replaced_axis_definitions(axes(axis("outer", "inner", published=True), axis("inner", "num_a"))):
            result = axis_definitions.evaluate_axes_array({"num_a": np.array([0.5, 2.0, NAN])})

        assert scores(result["inner"]) == [5.0, 20.0, None]
        assert scores(result["outer"]) == [50.0, 100.0, None]

    def test_python_values_give_published_axes_only(self):
        definitions = axes(
            axis("outer", "inner", published=True), axis("plain", "num_b", published=True), axis("inner", "num_a")
        )

        with replaced_axis_definitions(definitions):
            result = axis_definitions.evaluate_axes_values({"num_a": [0.5, None], "num_b": [1.0, 1.0]}, 2)

        assert result == {"outer": [50.0, None], "plain": [10.0, 10.0]}

    def test_inputs_are_the_raw_sum_or_the_looked_up_value_of_each_published_axis(self):
        definitions = axes(
            axis("outer", "inner", "num_b", published=True),
            AxisDefinition(
                axis_id="kind",
                shape=CategoricalShape(material="cat", mapping={"x": 10.0}),
                default_weight=1.0,
                label="kind",
                is_published=True,
            ),
            axis("inner", "num_a"),
        )

        with replaced_axis_definitions(definitions):
            inputs = axis_definitions.evaluate_axes_inputs(
                {"num_a": [0.5, None], "num_b": [1.0, 2.0], "cat": ["y", None]}, 2
            )

        assert inputs == {"outer": [6.0, None], "kind": ["y", None]}


class TestPrimaryAttributes:
    def test_the_attributes_of_the_leaf_materials_are_listed_once_through_the_axes_read(self):
        definitions = axes(axis("outer", "num_b", "inner", "num_c"), axis("inner", "num_a", "num_plain", "unknown"))

        with replaced_axis_definitions(definitions):
            assert axis_definitions.primary_attribute_ids_for(definitions["outer"]) == ["attr_y", "attr_x"]


class TestWeights:
    def test_default_weights_are_those_of_the_published_axes(self):
        definitions = axes(axis("shown", published=True, default_weight=2.0), axis("inner", default_weight=5.0))

        with replaced_axis_definitions(definitions):
            assert axis_definitions.default_axis_weights() == {"shown": 2.0}

    def test_an_axis_with_a_time_scope_weighs_only_on_the_segments_ridden_in_it(self):
        definitions = axes(axis("always"), axis("night", time_scope="night_only"))
        weights = {"always": 1.0, "night": 3.0}

        with replaced_axis_definitions(definitions):
            scoped = axis_definitions.time_scoped_weights(weights, {"night_only": np.array([False, True])})
            outside_every_scope = axis_definitions.time_scoped_weights(weights, {})

        assert scoped["always"] == 1.0 and scoped["night"].tolist() == [0.0, 3.0]
        assert outside_every_scope == {"always": 1.0, "night": 0.0}
        assert weights == {"always": 1.0, "night": 3.0}

    def test_axes_absent_from_the_weights_are_not_added(self):
        with replaced_axis_definitions(axes(axis("night", time_scope="night_only"))):
            assert axis_definitions.time_scoped_weights({"other": 1.0}, {}) == {"other": 1.0}
