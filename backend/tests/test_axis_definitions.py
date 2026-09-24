"""`domain/axis_definitions.py`——軸1本の宣言と評価、軸の集合に対する登録時の検査。

ここで見ないもの:
- 軸が軸を参照するときの並べ替え（依存順・動的軸の抽出・循環の検出）と、0次条件
  （`priority_overrides`）による得点の優先確定 → `test_axis_hierarchy.py`
- 折れ点補間とテーブル引きそのもの → `test_axis_templates.py`
- 地図表示の導出 → `test_axis_display.py`

**材料カタログは差し替える。** 「どのidが材料か」「材料がどの一次属性に属するか」は
カタログ側の話なので、性質だけを持つ架空の材料を与える。
"""

import math

import numpy as np
import pytest
from pydantic import ValidationError

from app.domain import axis_definitions, material_catalog
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.domain.registry import PrimaryAttributeSpec

LINEAR_0_100 = [(0.0, 0.0), (10.0, 100.0)]


def material(material_id: str, dtype: str = "numeric", primary_attribute_id: str | None = None):
    return material_catalog.MaterialSpec(
        material_id=material_id,
        label=material_id,
        description=material_id,
        dtype=dtype,
        primary_attribute=None
        if primary_attribute_id is None
        else PrimaryAttributeSpec(attr_id=primary_attribute_id, label=primary_attribute_id, geometry="line"),
        coverage=material_catalog.CoverageExcluded(reason="テスト用", missing_semantics="unknown"),
    )


@pytest.fixture
def catalog(monkeypatch):
    """架空の材料だけのカタログ。軸idはここに載らないので「軸の参照」として扱われる。"""
    specs = {
        "num_a": material("num_a", primary_attribute_id="attr_x"),
        "num_b": material("num_b", primary_attribute_id="attr_x"),
        "num_c": material("num_c", primary_attribute_id="attr_y"),
        "bool_a": material("bool_a", dtype="boolean"),
        "cat_a": material("cat_a", dtype="categorical"),
    }
    monkeypatch.setattr(material_catalog, "MATERIAL_CATALOG", specs)
    return specs


def term(material_id: str, weight: float = 1.0, required: bool = True) -> MaterialTerm:
    return MaterialTerm(material=material_id, weight=weight, required=required)


def linear_axis(axis_id: str, *terms: MaterialTerm | str, breakpoints=LINEAR_0_100, **fields) -> AxisDefinition:
    shape_fields = {k: fields.pop(k) for k in ("preprocess",) if k in fields}
    shape = BreakpointLinearShape(
        terms=[t if isinstance(t, MaterialTerm) else term(t) for t in terms],
        breakpoints=breakpoints,
        **shape_fields,
    )
    return AxisDefinition(
        axis_id=axis_id, label=axis_id, default_weight=fields.pop("default_weight", 1.0), shape=shape, **fields
    )


def categorical_axis(axis_id: str, material_id: str, mapping: dict, **fields) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        label=axis_id,
        default_weight=1.0,
        shape=CategoricalShape(material=material_id, mapping=mapping),
        **fields,
    )


@pytest.fixture
def axes(monkeypatch):
    """`AXIS_DEFINITIONS`をこのテストの間だけ差し替える。"""

    def install(*definitions: AxisDefinition) -> dict[str, AxisDefinition]:
        table = {d.axis_id: d for d in definitions}
        monkeypatch.setattr(axis_definitions, "AXIS_DEFINITIONS", table)
        return table

    return install


class TestDeclarationInvariants:
    @pytest.mark.parametrize("xs", [(0.0, 0.0), (5.0, 1.0)], ids=["同じx", "降順"])
    def test_breakpoints_must_rise_strictly_in_x(self, xs):
        with pytest.raises(ValidationError, match="小さい順に並べてください"):
            BreakpointLinearShape(terms=[term("num_a")], breakpoints=[(xs[0], 0.0), (xs[1], 100.0)])

    def test_a_single_breakpoint_is_a_valid_curve(self):
        BreakpointLinearShape(terms=[term("num_a")], breakpoints=[(0.0, 50.0)])

    @pytest.mark.parametrize("thresholds", [[1.0, 1.0], [2.0, 1.0]], ids=["同値", "降順"])
    def test_display_thresholds_must_rise_strictly(self, thresholds):
        with pytest.raises(ValidationError, match="小さい順に並べてください"):
            linear_axis("a", "num_a", display_thresholds_override=thresholds)

    def test_band_labels_need_fixed_thresholds(self):
        with pytest.raises(ValidationError, match="色分けのしきい値も上書きしてください"):
            linear_axis("a", "num_a", display_band_labels_override=["低", "高"])

    @pytest.mark.parametrize("labels", [["低"], ["低", "中", "高"]])
    def test_band_labels_must_be_one_per_band(self, labels):
        with pytest.raises(ValidationError, match="段のラベルは2件にしてください"):
            linear_axis("a", "num_a", display_thresholds_override=[5.0], display_band_labels_override=labels)

    def test_band_labels_one_per_band_are_accepted(self):
        definition = linear_axis(
            "a", "num_a", display_thresholds_override=[5.0], display_band_labels_override=["低", "高"]
        )

        assert definition.display_band_labels_override == ["低", "高"]


class TestCategoricalMappingKeys:
    """JSONのキーは文字列なので、真偽の材料の対応表は"true"/"false"で届く。"""

    def test_true_and_false_are_read_as_the_flag_values(self):
        shape = CategoricalShape.model_validate({"material": "bool_a", "mapping": {"true": 10.0, "false": 20.0}})

        assert shape.mapping == {True: 10.0, False: 20.0}
        assert all(isinstance(key, bool) for key in shape.mapping)

    def test_every_other_spelling_stays_the_value_name_it_was_written_as(self):
        """真偽として読める綴り（"yes"・"on"・"1"等）も、対応表では値の名前。"""
        names = ["yes", "no", "on", "off", "1", "0", "y", "n", "t", "f", "True", "FALSE"]

        shape = CategoricalShape.model_validate(
            {"material": "cat_a", "mapping": {name: float(i) for i, name in enumerate(names)}}
        )

        assert list(shape.mapping) == names


class TestReferencedMaterials:
    def test_linear_axis_lists_terms_then_override_materials_once_each(self):
        definition = linear_axis(
            "a",
            "num_a",
            "num_b",
            priority_overrides=[
                PriorityCondition(material="num_a", equals="1", value=0.0),
                PriorityCondition(material="bool_a", equals="true", value=0.0),
            ],
        )

        assert definition.materials == ["num_a", "num_b", "bool_a"]

    def test_categorical_axis_lists_its_material_and_override_materials(self):
        definition = categorical_axis(
            "a",
            "cat_a",
            {"x": 1.0},
            priority_overrides=[PriorityCondition(material="bool_a", equals="true", value=0.0)],
        )

        assert definition.materials == ["cat_a", "bool_a"]


class TestPublishImmutability:
    def test_draft_axes_can_be_changed_and_deleted(self):
        draft = linear_axis("a", "num_a")

        axis_definitions.check_publish_immutability(draft, "deleted")
        axis_definitions.check_publish_immutability(draft, "updated", draft.model_copy(update={"default_weight": 9.0}))

    def test_published_axis_cannot_be_deleted(self):
        published = linear_axis("a", "num_a", is_published=True)

        with pytest.raises(axis_definitions.AxisPublishedImmutableError) as excinfo:
            axis_definitions.check_publish_immutability(published, "deleted")

        assert (excinfo.value.axis_id, excinfo.value.action) == ("a", "deleted")

    def test_published_axis_accepts_a_change_that_only_affects_how_it_looks(self):
        published = linear_axis("a", "num_a", is_published=True)
        candidate = published.model_copy(update={"chip_label": "新", "show_map_icon": False})

        axis_definitions.check_publish_immutability(published, "updated", candidate)

    @pytest.mark.parametrize(
        "update",
        [{"default_weight": 2.0}, {"default_weight": 2.0, "chip_label": "新"}],
        ids=["評価に効く項目", "見た目と評価の両方"],
    )
    def test_published_axis_rejects_a_change_that_affects_evaluation(self, update):
        published = linear_axis("a", "num_a", is_published=True)

        with pytest.raises(axis_definitions.AxisPublishedImmutableError):
            axis_definitions.check_publish_immutability(published, "updated", published.model_copy(update=update))


class TestMaterialExclusivity:
    def test_a_material_already_used_by_another_axis_is_rejected(self, catalog):
        existing = {"other": linear_axis("other", "num_a", "num_b")}
        candidate = linear_axis(
            "cand", "num_b", priority_overrides=[PriorityCondition(material="num_a", equals="1", value=0.0)]
        )

        with pytest.raises(axis_definitions.AxisMaterialConflictError) as excinfo:
            axis_definitions.check_material_exclusivity(candidate, existing)

        error = excinfo.value
        assert (error.axis_id, error.conflicting_axis_id, error.overlapping_materials) == (
            "cand",
            "other",
            {"num_a", "num_b"},
        )

    def test_updating_an_axis_does_not_conflict_with_its_own_previous_version(self, catalog):
        axis_definitions.check_material_exclusivity(
            linear_axis("a", "num_a"), {"a": linear_axis("a", "num_a", "num_b")}
        )

    def test_several_axes_may_reference_the_same_axis(self, catalog):
        existing = {"inner": linear_axis("inner", "num_a"), "pub1": linear_axis("pub1", "inner")}

        axis_definitions.check_material_exclusivity(linear_axis("pub2", "inner", "num_b"), existing)


class TestAxisDependencies:
    def test_only_references_to_known_axes_are_dependencies(self, catalog):
        definition = linear_axis("a", "num_a", "inner", "ghost")

        assert axis_definitions.axis_dependencies(definition, {"a", "inner"}) == {"inner"}


class TestInternalAxisPublication:
    def test_an_axis_another_axis_reads_cannot_be_published(self, catalog):
        existing = {"inner": linear_axis("inner", "num_a"), "outer": linear_axis("outer", "inner")}

        with pytest.raises(axis_definitions.AxisInternalAxisPublishError) as excinfo:
            axis_definitions.check_internal_axis_not_published(
                linear_axis("inner", "num_a", is_published=True), existing
            )

        assert (excinfo.value.axis_id, excinfo.value.referencing_axis_id) == ("inner", "outer")

    def test_an_axis_another_axis_reads_can_stay_a_draft(self, catalog):
        existing = {"outer": linear_axis("outer", "inner")}

        axis_definitions.check_internal_axis_not_published(linear_axis("inner", "num_a"), existing)

    def test_an_axis_nobody_reads_can_be_published(self, catalog):
        existing = {"a": linear_axis("a", "num_a"), "b": linear_axis("b", "num_b")}

        axis_definitions.check_internal_axis_not_published(linear_axis("a", "num_a", is_published=True), existing)


class TestPrimaryAttributes:
    def test_follows_referenced_axes_down_to_their_materials(self, catalog, axes):
        """参照先の軸が同じ軸を共有していても（ひし形）、属性は最初に現れた順に1回ずつ。
        一次属性を持たない材料・カタログに無いidは現れない。"""
        axes(
            linear_axis("base", "num_c"),
            linear_axis("left", "base", "num_a"),
            linear_axis("right", "base"),
        )
        outer = linear_axis("outer", "left", "right", "bool_a", "num_b", "ghost")

        assert axis_definitions.primary_attribute_ids_for(outer) == ["attr_y", "attr_x"]


class TestWeights:
    def test_default_weights_cover_published_axes_only(self, axes):
        axes(
            linear_axis("pub", "num_a", is_published=True, default_weight=2.0),
            linear_axis("draft", "num_b", default_weight=3.0),
        )

        assert axis_definitions.default_axis_weights() == {"pub": 2.0}

    @pytest.fixture
    def scoped_axes(self, axes):
        axes(
            linear_axis("day", "num_a", is_published=True),
            linear_axis("night", "num_b", is_published=True, time_scope="night_only"),
        )

    def test_an_axis_outside_the_active_time_scopes_weighs_nothing(self, scoped_axes):
        weights = {"day": 1.0, "night": 2.0, "unknown": 3.0}

        assert axis_definitions.time_scoped_weights(weights, frozenset()) == {"day": 1.0, "night": 0.0, "unknown": 3.0}
        assert weights == {"day": 1.0, "night": 2.0, "unknown": 3.0}

    def test_an_axis_inside_the_active_time_scopes_keeps_its_weight(self, scoped_axes):
        weights = {"day": 1.0, "night": 2.0}

        assert axis_definitions.time_scoped_weights(weights, frozenset({"night_only"})) == weights

    def test_axes_absent_from_the_weights_are_not_added(self, scoped_axes):
        assert axis_definitions.time_scoped_weights({"day": 1.0}, frozenset()) == {"day": 1.0}


class TestEvaluateAxisScalar:
    def test_linear_axis_scores_the_weighted_sum_rounded_to_one_decimal(self):
        definition = linear_axis(
            "a", "num_a", term("num_b", weight=2.0), term("bool_a", weight=0.25), breakpoints=[(0.0, 0.0), (3.0, 10.0)]
        )

        assert axis_definitions.evaluate_axis_scalar(definition, {"num_a": 0.5, "num_b": 0.25, "bool_a": True}) == 4.2

    def test_a_missing_required_material_leaves_the_axis_unevaluated(self):
        definition = linear_axis("a", "num_a", "num_b")

        assert axis_definitions.evaluate_axis_scalar(definition, {"num_a": 1.0}) is None

    def test_a_missing_optional_material_contributes_nothing(self):
        definition = linear_axis("a", "num_a", term("num_b", required=False))

        assert axis_definitions.evaluate_axis_scalar(definition, {"num_a": 1.0}) == 10.0

    def test_an_axis_whose_materials_are_all_missing_is_unevaluated_even_if_optional(self):
        definition = linear_axis("a", term("num_a", required=False), term("num_b", required=False))

        assert axis_definitions.evaluate_axis_scalar(definition, {}) is None

    def test_abs_preprocessing_scores_the_magnitude(self):
        definition = linear_axis("a", "num_a", preprocess="abs")

        assert axis_definitions.evaluate_axis_scalar(definition, {"num_a": -3.0}) == 30.0

    @pytest.mark.parametrize(("materials", "expected"), [({"cat_a": "x"}, 40.0), ({"cat_a": "y"}, None), ({}, None)])
    def test_categorical_axis_scores_registered_values_only(self, materials, expected):
        definition = categorical_axis("a", "cat_a", {"x": 40.0})

        assert axis_definitions.evaluate_axis_scalar(definition, materials) == expected


@pytest.mark.parametrize(
    "evaluate",
    [
        lambda definition, value: axis_definitions.evaluate_axis_scalar(definition, {"num_a": value}),
        lambda definition, value: axis_definitions.evaluate_axis_array(definition, {"num_a": np.array([value])})[0],
    ],
    ids=["区間1本", "配列"],
)
@pytest.mark.parametrize(("value", "expected"), [(0.15, 0.1), (0.25, 0.2), (0.35, 0.3), (0.45, 0.5)])
def test_a_score_on_a_tenths_boundary_rounds_by_its_actual_binary_value(evaluate, value, expected):
    """区間の表示とルート選びは同じ得点を使う。0.15は2進では0.1499…なので0.1、0.45は0.4500…なので0.5。"""
    definition = linear_axis("a", "num_a", breakpoints=[(0.0, 0.0), (1.0, 1.0)])

    assert evaluate(definition, value) == expected


class TestEvaluateAxesScalar:
    def test_scores_published_axes_after_the_axes_they_read(self, axes):
        """公開軸だけを返し、評価できなかった公開軸もNoneとして残す。評価できた軸は次の軸の
        材料として混ぜ込まれる。"""
        axes(
            linear_axis("pub", "inner", breakpoints=[(0.0, 0.0), (100.0, 100.0)], is_published=True),
            linear_axis("inner", "num_a"),
            linear_axis("unevaluated", "num_b", is_published=True),
        )

        scores, materials = axis_definitions.evaluate_axes_scalar({"num_a": 5.0})

        assert scores == {"pub": 50.0, "unevaluated": None}
        assert materials == {"num_a": 5.0, "inner": 50.0, "pub": 50.0}


class TestEvaluateAxisArray:
    def test_a_missing_required_material_leaves_the_element_unevaluated(self):
        definition = linear_axis("a", "num_a", "num_b")

        result = axis_definitions.evaluate_axis_array(
            definition, {"num_a": np.array([1.0, np.nan, 1.0]), "num_b": np.array([2.0, 2.0, np.nan])}
        )

        assert result[0] == 30.0
        assert np.isnan(result[1:]).all()

    def test_missing_optional_materials_contribute_nothing_unless_all_are_missing(self):
        definition = linear_axis("a", term("num_a", required=False), term("num_b", required=False))

        result = axis_definitions.evaluate_axis_array(
            definition, {"num_a": np.array([1.0, np.nan]), "num_b": np.array([np.nan, np.nan])}
        )

        assert result[0] == 10.0
        assert math.isnan(result[1])

    def test_a_false_flag_is_an_observation_not_a_missing_value(self):
        definition = linear_axis("a", term("bool_a", weight=4.0, required=False))

        result = axis_definitions.evaluate_axis_array(definition, {"bool_a": np.array([True, False])})

        assert result.tolist() == [40.0, 0.0]

    def test_abs_preprocessing_and_rounding_to_one_decimal(self):
        definition = linear_axis("a", "num_a", preprocess="abs", breakpoints=[(0.0, 0.0), (3.0, 10.0)])

        result = axis_definitions.evaluate_axis_array(definition, {"num_a": np.array([-1.0])})

        assert result.tolist() == [3.3]

    def test_categorical_axis_scores_registered_values_only(self):
        definition = categorical_axis("a", "cat_a", {"x": 40.0})

        result = axis_definitions.evaluate_axis_array(definition, {"cat_a": np.array(["x", "y", None], dtype=object)})

        assert result[0] == 40.0
        assert np.isnan(result[1:]).all()


class TestAxisRawValueArray:
    def test_linear_axis_returns_the_preprocessed_sum_before_the_curve(self):
        definition = linear_axis(
            "a", term("num_a", required=False), term("num_b", weight=2.0, required=False), preprocess="abs"
        )

        raw = axis_definitions.axis_raw_value_array(
            definition, {"num_a": np.array([-3.25, np.nan]), "num_b": np.array([1.0, np.nan])}
        )

        assert axis_definitions.has_axis_raw_value_array(definition) is True
        assert raw[0] == 1.25
        assert math.isnan(raw[1])

    def test_categorical_axis_has_no_raw_value(self):
        definition = categorical_axis("a", "cat_a", {"x": 40.0})

        assert axis_definitions.has_axis_raw_value_array(definition) is False
        assert axis_definitions.axis_raw_value_array(definition, {"cat_a": np.array(["x"], dtype=object)}) is None
