"""`domain/axis_definitions.py`——軸が軸を参照する構造の、並べ替えと優先確定。

軸1本の評価（折れ点・欠損・排他チェック・公開の不変性）は`test_axis_definitions.py`、
折れ点補間とテーブル引きそのものは`test_axis_templates.py`、地図表示の導出は
`test_axis_display.py`が持つ。

**材料カタログは差し替える。** 「どのidが材料でどれが軸参照か」はカタログ側の話で、
ここが負うのは「軸参照と分かったあと、どう並べ、どう短絡するか」だけ。
"""

import numpy as np
import pytest

from app.domain import material_catalog
from app.domain.axis_definitions import (
    AxisDefinition,
    AxisDependencyCycleError,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
    REQUEST_DYNAMIC_MATERIAL_IDS,
    axis_dependencies,
    dynamic_axis_topological_order,
    evaluate_axis_array,
    evaluate_axis_values,
    topological_axis_order,
)

DYNAMIC = next(iter(REQUEST_DYNAMIC_MATERIAL_IDS))


def score_of_one(definition, materials):
    """1区間ぶんの材料（Pythonの値）の得点。区間インスペクタ・地図の値配信と同じ入口を長さ1で通す。"""
    return evaluate_axis_values(definition, {k: [v] for k, v in materials.items()}, 1)[0]


@pytest.fixture
def catalog(monkeypatch):
    """材料と認めるidを差し替える。ここに無いidは軸参照の候補になる。"""
    known = {"num_a", "num_b", DYNAMIC}
    monkeypatch.setattr(material_catalog, "is_known_material", lambda m: m in known)
    return known


def _axis(axis_id: str, materials: list[str], **overrides) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        label=f"軸[{axis_id}]",
        default_weight=1.0,
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material=m) for m in materials],
            breakpoints=[(0.0, 0.0), (1.0, 100.0)],
        ),
        **overrides,
    )


def _definitions(*axes: AxisDefinition) -> dict[str, AxisDefinition]:
    return {axis.axis_id: axis for axis in axes}


def _categorical_axis(mapping: dict) -> AxisDefinition:
    return AxisDefinition(
        axis_id="axis",
        label="軸",
        default_weight=1.0,
        shape=CategoricalShape(material="num_b", mapping=mapping),
    )


class TestWhichReferencesAreAxes:
    def test_an_id_that_is_not_a_material_and_is_a_known_axis_is_a_dependency(self):
        definition = _axis("outer", ["num_a", "inner"])

        assert axis_dependencies(definition, {"outer", "inner"}) == {"inner"}

    def test_a_material_is_never_a_dependency(self, catalog):
        """材料と同じ名前の軸を作れる。材料側を依存として扱うと、存在しない軸を辿る。"""
        definition = _axis("outer", ["num_a", "num_b"])

        assert axis_dependencies(definition, {"outer", "num_a"}) == set()

    def test_an_id_nobody_knows_is_not_a_dependency(self):
        """綴り違いの参照で並べ替えごと落とさない。評価の側が欠損として扱う。"""
        definition = _axis("outer", ["no_such_thing"])

        assert axis_dependencies(definition, {"outer"}) == set()


class TestTheEvaluationOrder:
    def test_a_chain_is_ordered_from_the_leaf_up(self):
        definitions = _definitions(
            _axis("top", ["middle"]), _axis("middle", ["bottom"]), _axis("bottom", ["num_a"])
        )

        assert topological_axis_order(definitions) == ["bottom", "middle", "top"]

    def test_axes_without_dependencies_keep_the_order_they_were_declared_in(self):
        """並びが実行ごとに変わると、同じ入力から出る合計がビット単位で揺れる
        （Neumaier加算の順序依存）。
        """
        definitions = _definitions(
            _axis("c", ["num_a"]), _axis("a", ["num_a"]), _axis("b", ["num_a"])
        )

        assert topological_axis_order(definitions) == ["c", "a", "b"]

    def test_a_cycle_is_reported_with_the_chain_that_forms_it(self):
        """どの軸を直せばよいかが分からないと、軸スタジオで循環を解けない。"""
        definitions = _definitions(_axis("a", ["b"]), _axis("b", ["a"]))

        with pytest.raises(AxisDependencyCycleError) as caught:
            topological_axis_order(definitions)

        assert "a" in caught.value.cycle and "b" in caught.value.cycle
        assert "->" in str(caught.value)

    def test_an_axis_that_references_itself_is_a_cycle(self):
        definitions = _definitions(_axis("a", ["a"]))

        with pytest.raises(AxisDependencyCycleError):
            topological_axis_order(definitions)

    def test_every_axis_appears_exactly_once(self):
        definitions = _definitions(
            _axis("outer", ["inner", "num_a"]), _axis("inner", ["num_a"]), _axis("lone", ["num_b"])
        )

        order = topological_axis_order(definitions)

        assert sorted(order) == ["inner", "lone", "outer"]
        assert len(order) == len(set(order))


class TestTheOrderIsCachedByContent:
    def test_replacing_the_contents_of_the_same_dict_gives_the_new_order(self):
        """起動時の読み込みは`AXIS_DEFINITIONS`を`clear()`+`update()`で**同じオブジェクトの
        まま**差し替える。オブジェクトの同一性で覚えると、差し替え後も古い順序を返し、
        新しい軸が未評価のまま参照される。
        """
        definitions = _definitions(_axis("outer", ["inner"]), _axis("inner", ["num_a"]))
        assert topological_axis_order(definitions).index("inner") == 0

        definitions.clear()
        definitions.update(_definitions(_axis("outer", ["num_a"]), _axis("inner", ["outer"])))

        assert topological_axis_order(definitions).index("outer") == 0

    def test_the_dynamic_set_is_also_keyed_by_content(self):
        """同じオブジェクトのまま差し替えたあとに古い集合を返すと、風を参照するように
        なった軸がリクエスト時の再評価から漏れ、風を織り込まない値が出続ける。
        """
        definitions = _definitions(_axis("a", ["num_a"]))
        assert dynamic_axis_topological_order(definitions) == []

        definitions.clear()
        definitions.update(_definitions(_axis("a", [DYNAMIC])))

        assert dynamic_axis_topological_order(definitions) == ["a"]

    def test_a_cycle_is_not_remembered(self):
        """軸スタジオでの試行錯誤中に一時的な循環を経て直したとき、直した結果が
        評価されないと直せたことが分からない。
        """
        definitions = _definitions(_axis("a", ["b"]), _axis("b", ["a"]))
        with pytest.raises(AxisDependencyCycleError):
            topological_axis_order(definitions)

        definitions["b"] = _axis("b", ["num_a"])

        assert topological_axis_order(definitions) == ["b", "a"]


class TestWhichAxesDependOnRequestTimeMaterials:
    """探索範囲の静的スコア行列はそのまま使い、ここが返す軸だけをリクエスト時に
    再評価する。取りこぼすと、その軸だけ風を織り込まない古い値が出る。
    """

    def test_an_axis_that_reads_a_dynamic_material_is_included(self):
        definitions = _definitions(_axis("windy", [DYNAMIC]), _axis("static", ["num_a"]))

        assert dynamic_axis_topological_order(definitions) == ["windy"]

    def test_an_axis_that_only_reaches_it_through_another_axis_is_included(self):
        """軸スタジオが作った軸が既存の風の軸を参照しただけでも、ハードコード無しで
        入る必要がある。
        """
        definitions = _definitions(_axis("outer", ["inner"]), _axis("inner", [DYNAMIC]))

        assert dynamic_axis_topological_order(definitions) == ["inner", "outer"]

    def test_a_long_chain_is_followed_to_the_end(self):
        definitions = _definitions(
            _axis("top", ["middle"]), _axis("middle", ["bottom"]), _axis("bottom", [DYNAMIC])
        )

        assert dynamic_axis_topological_order(definitions) == ["bottom", "middle", "top"]

    def test_nothing_is_returned_when_no_axis_reads_one(self):
        definitions = _definitions(_axis("static", ["num_a"]))

        assert dynamic_axis_topological_order(definitions) == []

    def test_the_result_keeps_the_dependency_order(self):
        definitions = _definitions(
            _axis("outer", ["inner"]), _axis("inner", [DYNAMIC]), _axis("static", ["num_a"])
        )

        order = dynamic_axis_topological_order(definitions)
        full = topological_axis_order(definitions)

        assert order == [axis_id for axis_id in full if axis_id in set(order)]


class TestPriorityConditions:
    """0次条件は**評価を優先確定する**。道路を探索から外すハードフィルタとは別の機構。"""

    @staticmethod
    def _axis_with_override(*conditions: PriorityCondition) -> AxisDefinition:
        return _axis("axis", ["num_a"], priority_overrides=list(conditions))

    @staticmethod
    def _scores(axis: AxisDefinition, scalar_values: list, array_values: np.ndarray) -> tuple[list, list]:
        """区間の内訳が通るスカラーの入口と、ルート選びが通る配列の入口の両方の得点。"""
        scalar = [score_of_one(axis, {"num_a": 1.0, "num_b": value}) for value in scalar_values]
        array = evaluate_axis_array(axis, {"num_a": np.ones(len(array_values)), "num_b": array_values})
        return scalar, array.tolist()

    @pytest.mark.parametrize(
        ("equals", "scalar_values", "array_values", "expected"),
        [
            ("x", ["x", "y", None], np.array(["x", "y", None], dtype=object), [3.0, 100.0, 100.0]),
            ("true", [True, False], np.array([True, False]), [3.0, 100.0]),
            ("false", [True, False], np.array([True, False]), [100.0, 3.0]),
            ("true", [True, False, None], np.array([1.0, 0.0, np.nan]), [3.0, 100.0, 100.0]),
            ("false", [True, False, None], np.array([1.0, 0.0, np.nan]), [100.0, 3.0, 100.0]),
            ("yes", [True, False], np.array([True, False]), [100.0, 100.0]),
            ("True", [True, False], np.array([True, False]), [100.0, 100.0]),
            ("1", [True, False, None], np.array([1.0, 0.0, np.nan]), [100.0, 100.0, 100.0]),
        ],
        ids=[
            "分類の値の名前",
            "真偽の材料にtrue",
            "真偽の材料にfalse",
            "不明を持つ真偽の材料にtrue",
            "不明を持つ真偽の材料にfalse",
            "真偽と読まない綴りyes",
            "真偽と読まない綴りTrue",
            "不明を持つ真偽の材料に真偽と読まない綴り",
        ],
    )
    def test_the_inspector_and_the_route_decide_the_same_roads(self, equals, scalar_values, array_values, expected):
        """材料の値は入口ごとに別の形で届く（スカラーはPythonの値、配列は材料の型ごとの配列で、
        「不明」を持つ真偽の材料は1.0/0.0/NaNの数値の配列）。形によって答えが変わると、区間を押して
        見える得点とルート選びが使う得点が同じ道で食い違う。`equals`は対応表のキーと同じく
        "true"/"false"だけを真偽と読み、欠損はどの条件にも当たらない。
        """
        axis = self._axis_with_override(PriorityCondition(material="num_b", equals=equals, value=3.0))

        assert self._scores(axis, scalar_values, array_values) == (expected, expected)

    def test_a_material_that_is_not_there_does_not_match(self):
        """欠損を一致として扱うと、値を持たない区間がすべて優先確定へ落ちる。"""
        axis = self._axis_with_override(PriorityCondition(material="num_b", equals="x", value=3.0))

        assert score_of_one(axis, {"num_a": 1.0}) == 100.0

    def test_the_first_condition_that_matches_decides(self):
        """後のものを採用すると、宣言の並びが意味を持たなくなる。配列の入口は要素ごとのマスクを
        重ねるため、重ねる順を誤ると後の条件が勝つ。
        """
        axis = self._axis_with_override(
            PriorityCondition(material="num_b", equals="x", value=3.0),
            PriorityCondition(material="num_b", equals="x", value=9.0),
        )

        assert self._scores(axis, ["x"], np.array(["x"], dtype=object)) == ([3.0], [3.0])


class TestCategoricalKeys:
    def test_the_words_true_and_false_become_booleans(self):
        """DB往復（JSONへ出して読み戻す）でキーが文字列になる。真偽のまま保てないと、
        真偽値材料を使う軸の表引きが全要素で外れる。
        """
        shape = CategoricalShape(material="num_b", mapping={"true": 10.0, "false": 20.0})

        assert set(shape.mapping) == {True, False}

    def test_any_other_word_stays_a_word(self):
        """`"asphalt"`が真偽へ強制変換されると、分類材料の表引きが壊れる。"""
        shape = CategoricalShape(material="num_b", mapping={"asphalt": 10.0, "gravel": 20.0})

        assert set(shape.mapping) == {"asphalt", "gravel"}

    def test_a_categorical_material_is_looked_up_by_its_value(self):
        axis = _categorical_axis({"asphalt": 10.0, "gravel": 20.0})

        assert score_of_one(axis, {"num_b": "gravel"}) == 20.0

    def test_the_array_path_also_normalises_the_boolean_keys(self):
        axis = _categorical_axis({"true": 10.0, "false": 20.0})

        assert evaluate_axis_array(axis, {"num_b": np.array([True, False])}).tolist() == [
            10.0,
            20.0,
        ]

    def test_a_boolean_material_is_looked_up_through_the_normalised_keys(self):
        axis = _categorical_axis({"true": 10.0, "false": 20.0})

        assert score_of_one(axis, {"num_b": True}) == 10.0
        assert score_of_one(axis, {"num_b": False}) == 20.0
