"""`domain/dynamic_way_values.py`——専用way値配信の軸の宣言と、地図が塗る値の種類・段・単位・変換。

ここで見ないもの:
- 地図表示（ramp）そのものの導出と段を落とす規則 → `test_axis_display.py`
- 軸1本の得点の計算 → `test_axis_definitions.py`
- 配信サービス本体と、軸と配信実装の突き合わせ → 各サービスのテストと`api/dependencies.py`の利用者

**名前空間の外向きの参照は差し替える**——軸の集合・材料カタログは架空のもので、地図表示の導出と
軸の評価は`bound()`で本物の署名へ当てた代役で与える。
"""

import pytest

from app.domain import dynamic_way_values, material_catalog
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.domain.registry import AxisDisplaySpec
from tests.bound_fake import bound

FLAG_CONDITION = PriorityCondition(material="flag", equals="true", value=0.0)


def linear(*materials, breakpoints=((0.0, 0.0), (10.0, 100.0)), preprocess="identity"):
    return BreakpointLinearShape(
        terms=[MaterialTerm(material=m) for m in materials], breakpoints=list(breakpoints), preprocess=preprocess
    )


def axis(axis_id, shape, **fields):
    return AxisDefinition(axis_id=axis_id, label=f"{axis_id}の名前", default_weight=1.0, shape=shape, **fields)


@pytest.fixture
def catalog(monkeypatch):
    specs = {
        m: material_catalog.MaterialSpec(
            material_id=m,
            label=m,
            description=m,
            dtype="numeric",
            unit=unit,
            coverage=material_catalog.CoverageExcluded(reason="テスト用", missing_semantics="unknown"),
        )
        for m, unit in (("grade", "%"), ("speed", "km/h"))
    }
    monkeypatch.setattr(dynamic_way_values, "MATERIAL_CATALOG", specs)


@pytest.fixture
def map_display(monkeypatch):
    """地図表示の導出を差し替え、軸ごとに返す表示を決める（既定は地図に出ない）。"""
    displays: dict[str, object] = {}

    def axis_display_for(definition):
        return displays.get(definition.axis_id, AxisDisplaySpec(kind="none", label=definition.label))

    monkeypatch.setattr(
        dynamic_way_values, "axis_display_for", bound(dynamic_way_values.axis_display_for, axis_display_for)
    )
    return displays


class TestDedicatedWayValueAxes:
    def test_only_axes_declaring_the_layer_are_listed_with_what_they_depend_on(self, monkeypatch):
        monkeypatch.setattr(
            dynamic_way_values,
            "AXIS_DEFINITIONS",
            {
                "wind": axis(
                    "wind",
                    linear("speed"),
                    dedicated_way_value_layer=True,
                    dynamic_way_value_needs_time=True,
                    dynamic_way_value_needs_speed=True,
                ),
                "slope": axis(
                    "slope", linear("grade"), dedicated_way_value_layer=True, dynamic_way_value_needs_bearing=True
                ),
                "plain": axis("plain", linear("grade")),
            },
        )

        assert dynamic_way_values.dedicated_way_value_axes() == {
            "wind": dynamic_way_values.DedicatedWayValueAxis(
                axis_id="wind", label="windの名前", needs_time=True, needs_bearing=False, needs_speed=True
            ),
            "slope": dynamic_way_values.DedicatedWayValueAxis(
                axis_id="slope", label="slopeの名前", needs_time=False, needs_bearing=True, needs_speed=False
            ),
        }

    def test_axes_changed_while_running_are_seen_on_the_next_call(self, monkeypatch):
        """軸の集合は起動時の読み込み・管理APIの書き込みで、同じ辞書のまま中身が入れ替わる。"""
        definitions = {"a": axis("a", linear("grade"))}
        monkeypatch.setattr(dynamic_way_values, "AXIS_DEFINITIONS", definitions)
        assert dynamic_way_values.dedicated_way_value_axes() == {}

        definitions.clear()
        definitions.update({"a": axis("a", linear("grade"), dedicated_way_value_layer=True)})

        assert list(dynamic_way_values.dedicated_way_value_axes()) == ["a"]


@pytest.mark.usefixtures("catalog")
class TestMapValueKind:
    def test_a_single_material_scored_by_magnitude_is_painted_as_its_signed_value(self):
        definition = axis("a", linear("grade", preprocess="abs"))

        assert dynamic_way_values.map_value_kind(definition) == "signed_material"
        assert dynamic_way_values.map_value_material(definition) == "grade"
        assert dynamic_way_values.map_value_unit(definition) == "%"

    @pytest.mark.parametrize(
        "shape",
        [
            linear("grade"),
            linear("grade", "speed", preprocess="abs"),
            linear("other_axis", preprocess="abs"),
            CategoricalShape(material="grade", mapping={"x": 1.0}),
        ],
        ids=["符号を畳まない", "複数の項", "軸を参照する項", "分類"],
    )
    def test_everything_else_is_painted_as_difficulty_without_a_unit(self, shape):
        definition = axis("a", shape)

        assert dynamic_way_values.map_value_kind(definition) == "difficulty"
        assert dynamic_way_values.map_value_material(definition) is None
        assert dynamic_way_values.map_value_unit(definition) == ""

    def test_an_axis_with_a_priority_condition_is_painted_as_difficulty(self):
        """生値は条件の当たる道でも生値のままで、評価（条件の値）と食い違う。"""
        definition = axis("a", linear("grade", preprocess="abs"), priority_overrides=[FLAG_CONDITION])

        assert dynamic_way_values.map_value_kind(definition) == "difficulty"


@pytest.mark.usefixtures("catalog")
class TestMapValueThresholds:
    """地図に出ない軸（専用配信）は地図が塗る値そのものの境界を、地図に出る軸は地図の段を難易度の目盛りへ写した境界を返す。"""

    def test_an_axis_off_the_map_uses_its_override_as_given(self, map_display):
        definition = axis("a", linear("grade", preprocess="abs"), display_thresholds_override=[-1.0, 2.0])

        assert dynamic_way_values.map_value_thresholds(definition) == [-1.0, 2.0]

    def test_a_signed_axis_off_the_map_bands_symmetrically_at_its_breakpoints(self, map_display):
        definition = axis(
            "a",
            linear(
                "grade",
                preprocess="abs",
                breakpoints=[(-2.0, 50.0), (0.0, 0.0), (3.0, 20.0), (8.0, 100.0), (9.0, 100.0)],
            ),
        )

        assert dynamic_way_values.map_value_thresholds(definition) == [-9.0, -8.0, -3.0, 3.0, 8.0, 9.0]

    @pytest.mark.parametrize(
        "shape",
        [
            linear("grade"),
            linear("grade", "speed", preprocess="abs"),
            linear("other_axis", preprocess="abs"),
            CategoricalShape(material="grade", mapping={"x": 1.0}),
        ],
        ids=["符号を畳まない", "複数の項", "項が材料でなく軸", "分類"],
    )
    def test_other_axes_off_the_map_have_no_bands(self, map_display, shape):
        assert dynamic_way_values.map_value_thresholds(axis("a", shape)) is None

    def test_a_linear_axis_on_the_map_maps_its_bands_onto_the_difficulty_scale(self, map_display):
        definition = axis("a", linear("grade", breakpoints=[(0.0, 0.0), (3.0, 10.0)]))
        map_display["a"] = AxisDisplaySpec(
            kind="ramp", label="aの名前", tile_inputs=[{"property": "grade"}], thresholds=[1.0, 2.0, 5.0]
        )

        assert dynamic_way_values.map_value_thresholds(definition) == [3.3, 6.7, 10.0]

    def test_an_axis_on_the_map_that_folds_the_sign_is_refused(self, map_display):
        """地図に塗れる軸を符号を畳まない形に限るのは地図表示の導出で、そこが変われば負の境界が正の側へ
        折り返り、ルート線が全区間同じ帯になる。黙って写さずに止める。"""
        definition = axis("a", linear("grade", "speed", preprocess="abs"))
        map_display["a"] = AxisDisplaySpec(
            kind="ramp", label="aの名前", tile_inputs=[{"property": "grade"}], thresholds=[-1.0, 1.0]
        )

        with pytest.raises(ValueError, match="folds the sign"):
            dynamic_way_values.map_value_thresholds(definition)

    def test_a_categorical_axis_on_the_map_keeps_its_bands_which_are_already_scores(self, map_display):
        definition = axis("a", CategoricalShape(material="grade", mapping={"x": 0.0, "z": 100.0}))
        map_display["a"] = AxisDisplaySpec(
            kind="ramp", label="aの名前", tile_inputs=[{"property": "grade"}], thresholds=[50.0]
        )

        assert dynamic_way_values.map_value_thresholds(definition) == [50.0]


@pytest.mark.usefixtures("catalog")
class TestTransformDedicatedWayValues:
    def test_a_signed_axis_passes_the_values_through(self):
        values = {"w1": -3.0, "w2": 4.0}

        assert (
            dynamic_way_values.transform_dedicated_way_values(
                axis("a", linear("grade", preprocess="abs")), "grade", values
            )
            == values
        )

    def test_a_difficulty_axis_scores_each_distinct_value_once_and_drops_the_unscorable(self, monkeypatch):
        calls = []

        def evaluate_axis_scalar(definition, materials):
            calls.append(materials)
            value = materials["speed"]
            return None if value < 0 else value * 10

        monkeypatch.setattr(
            dynamic_way_values,
            "evaluate_axis_scalar",
            bound(dynamic_way_values.evaluate_axis_scalar, evaluate_axis_scalar),
        )

        result = dynamic_way_values.transform_dedicated_way_values(
            axis("a", linear("speed")), "speed", {"w1": 2.0, "w2": 2.0, "w3": -1.0, "w4": 3.0}
        )

        assert result == {"w1": 20.0, "w2": 20.0, "w4": 30.0}
        assert calls == [{"speed": 2.0}, {"speed": -1.0}, {"speed": 3.0}]

    def test_a_condition_on_a_material_the_layer_does_not_serve_leaves_every_road_unscored(self):
        """配信は1つの材料の値しか持たず、ほかの材料に置いた条件が当たるかを決められない。当たらないものと
        して塗ると、条件の当たる道でルート選びと違う色になる。"""
        definition = axis("a", linear("speed"), priority_overrides=[FLAG_CONDITION])

        assert dynamic_way_values.transform_dedicated_way_values(definition, "speed", {"w1": 2.0}) == {}
