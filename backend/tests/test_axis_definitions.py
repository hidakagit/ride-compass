"""`domain/axis_definitions.py`——軸1本の宣言（モデルの検証・軸の外に照らす検査・書き込みのガード）と、軸1本の評価。

入口:
- モデルの組み立て（`AxisDefinition`・`BreakpointLinearShape`・`CategoricalShape`。管理APIの本文もDBの行もここを通る）
- 軸の外に照らす検査（`check_axis_definition`）と書き込みのガード（`check_publish_immutability`・
  `check_material_exclusivity`・`check_internal_axis_not_published`）
- 軸1本の評価（`evaluate_axis_array`・`evaluate_axis_values`）と生値（`axis_raw_value_array`・`raw_values`・
  `first_term_points`・`BreakpointLinearShape.score_at`）

ここで見ないもの:
- 軸が軸を参照するときの並べ替え・軸の集合の評価・既定の重みと時間帯 → `test_axis_hierarchy.py`
- 折れ線の補間と対応表の引き方そのもの → `test_axis_templates.py`
- 難易度の桁への丸めの中身 → `test_difficulty.py`
- 検証の誤り・断りを管理APIが422・409で返すこと → `test_axis_admin_routes.py`
- 軸カタログが配る一次属性と気象のチップ → `test_axis_catalog_routes.py`

**材料カタログは差し替える。** 軸の外に照らす検査が見るのは材料の型と表示名だけなので、その性質だけを持つ
架空の材料を与える。評価はカタログを読まない。
"""

import math

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from app.domain import axis_definitions, material_catalog
from app.domain.attributes import CategoricalColumn
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)

NAN = float("nan")
DYNAMIC = next(iter(axis_definitions.REQUEST_DYNAMIC_MATERIAL_IDS))


def material(material_id: str, label: str, dtype: material_catalog.MaterialDType) -> material_catalog.MaterialSpec:
    return material_catalog.MaterialSpec(
        material_id=material_id,
        label=label,
        description=label,
        dtype=dtype,
        tile_property=None,
        coverage=material_catalog.CoverageExcluded(reason="テスト用", missing_semantics="unknown"),
    )


@pytest.fixture
def catalog(monkeypatch):
    specs = {
        "num_a": material("num_a", "数値A", "numeric"),
        "num_b": material("num_b", "数値B", "numeric"),
        "flag": material("flag", "旗", "boolean"),
        "cat": material("cat", "種類", "categorical"),
        DYNAMIC: material(DYNAMIC, "時刻の材料", "numeric"),
    }
    monkeypatch.setattr(material_catalog, "MATERIAL_CATALOG", specs)
    return specs


def linear(*terms: MaterialTerm, breakpoints=((0.0, 0.0), (10.0, 100.0)), preprocess="identity") -> BreakpointLinearShape:
    return BreakpointLinearShape(terms=list(terms), breakpoints=list(breakpoints), preprocess=preprocess)


def axis(axis_id: str = "axis_a", shape=None, **fields) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=shape if shape is not None else linear(MaterialTerm(material="num_a")),
        **{"default_weight": 1.0, "label": "軸", **fields},
    )


def axis_errors(error: ValidationError) -> list[tuple[str, str]]:
    return [(e["type"], e["msg"]) for e in error.errors()]


def assert_refused(make, fragment: str) -> None:
    """検証の誤りは管理画面にそのまま出るので、前置きの無い日本語の文1件で返る。"""
    with pytest.raises(ValidationError) as caught:
        make()
    [(kind, message)] = axis_errors(caught.value)
    assert kind == "axis_definition"
    assert fragment in message


class TestShapeModels:
    def test_breakpoints_must_rise_strictly_along_the_value_axis(self):
        assert_refused(lambda: linear(MaterialTerm(material="m"), breakpoints=[(0.0, 0.0), (0.0, 50.0)]), "小さい順")

    def test_an_empty_mapping_is_refused(self):
        assert_refused(lambda: CategoricalShape(material="m", mapping={}), "1件")

    def test_only_true_and_false_are_read_as_flags_in_a_mapping(self):
        shape = CategoricalShape(material="m", mapping={"true": 1.0, "false": 2.0, "yes": 3.0, "1": 4.0})

        assert shape.mapping == {True: 1.0, False: 2.0, "yes": 3.0, "1": 4.0}

    def test_a_shape_reports_only_the_errors_of_its_own_kind(self):
        with pytest.raises(ValidationError) as caught:
            AxisDefinition.model_validate(
                {
                    "axis_id": "a",
                    "label": "軸",
                    "default_weight": 1.0,
                    "shape": {"kind": "categorical", "material": "m", "mapping": {}},
                }
            )

        assert [kind for kind, _ in axis_errors(caught.value)] == ["axis_definition"]

    @pytest.mark.parametrize(
        ("shape", "expected"),
        [
            ({"material": "m", "mapping": {"x": 1.0}}, CategoricalShape),
            ({"terms": [{"material": "m"}], "breakpoints": [[0.0, 0.0]]}, BreakpointLinearShape),
        ],
    )
    def test_a_shape_without_its_kind_is_told_apart_by_its_contents(self, shape, expected):
        definition = AxisDefinition.model_validate({"axis_id": "a", "label": "軸", "default_weight": 1.0, "shape": shape})

        assert isinstance(definition.shape, expected)


class TestAxisModel:
    def test_an_empty_label_is_refused(self):
        assert_refused(lambda: axis(label=""), "表示名")

    @pytest.mark.parametrize(("thresholds", "fragment"), [([], "1件以上"), ([10.0, 10.0], "小さい順")])
    def test_overridden_thresholds_must_be_present_and_rise_strictly(self, thresholds, fragment):
        assert_refused(lambda: axis(display_thresholds_override=thresholds), fragment)

    def test_band_labels_need_overridden_thresholds(self):
        assert_refused(lambda: axis(display_band_labels_override=["弱", "強"]), "しきい値も上書き")

    def test_band_labels_must_match_the_number_of_bands(self):
        assert_refused(
            lambda: axis(display_thresholds_override=[1.0, 2.0], display_band_labels_override=["弱", "強"]), "3件"
        )

    def test_band_labels_one_more_than_the_thresholds_are_accepted(self):
        definition = axis(display_thresholds_override=[1.0, 2.0], display_band_labels_override=["弱", "中", "強"])

        assert definition.display_band_labels_override == ["弱", "中", "強"]

    @pytest.mark.parametrize(
        ("shape", "expected"),
        [
            (linear(MaterialTerm(material="num_b"), MaterialTerm(material="flag")), ["num_b", "flag", "cat"]),
            (CategoricalShape(material="cat", mapping={"x": 1.0}), ["cat", "flag"]),
        ],
    )
    def test_materials_list_the_shape_then_the_conditions_once_each(self, shape, expected):
        definition = axis(
            shape=shape,
            priority_overrides=[
                PriorityCondition(material="cat", equals="x", value=0.0),
                PriorityCondition(material="flag", equals="true", value=0.0),
            ],
        )

        assert definition.materials == expected


def refused_by_check(definition: AxisDefinition, fragment: str, axes=None) -> None:
    with pytest.raises(PydanticCustomError) as caught:
        axis_definitions.check_axis_definition(definition, axes or {})
    assert caught.value.type == "axis_definition"
    assert fragment in str(caught.value)


@pytest.mark.usefixtures("catalog")
class TestCheckAxisDefinition:
    def test_a_label_on_the_map_chip_fits_its_tile(self):
        axis_definitions.check_axis_definition(axis(label="四文字軸"), {})
        axis_definitions.check_axis_definition(axis(label="五文字の軸", chip_label="略称"), {})

        refused_by_check(axis(label="五文字の軸"), "略称")

    @pytest.mark.parametrize(
        ("definition", "fragment"),
        [
            (axis(shape=linear(MaterialTerm(material=DYNAMIC), MaterialTerm(material="num_a"))), "「数値A」"),
            (
                axis(
                    shape=linear(MaterialTerm(material=DYNAMIC)),
                    priority_overrides=[PriorityCondition(material="flag", equals="true", value=0.0)],
                ),
                "「旗」",
            ),
        ],
        ids=["term", "condition"],
    )
    def test_materials_that_change_by_the_hour_are_not_mixed_with_static_ones(self, definition, fragment):
        refused_by_check(definition, fragment)

    def test_an_hourly_material_may_be_combined_with_another_axis(self):
        definition = axis(shape=linear(MaterialTerm(material=DYNAMIC), MaterialTerm(material="other_axis")))

        axis_definitions.check_axis_definition(definition, {"other_axis": axis("other_axis")})

    def test_a_reference_that_is_neither_a_material_nor_a_given_axis_is_refused_by_its_id(self):
        refused_by_check(axis(shape=linear(MaterialTerm(material="nowhere"))), "nowhere")

    @pytest.mark.parametrize(
        ("shape", "fragment"),
        [
            (linear(MaterialTerm(material="cat")), "「種類」"),
            (CategoricalShape(material="num_a", mapping={"1": 1.0}), "「数値A」"),
        ],
    )
    def test_a_material_of_a_type_the_shape_cannot_read_is_refused_by_its_name(self, shape, fragment):
        refused_by_check(axis(shape=shape), fragment)

    def test_a_sum_may_mix_numbers_and_flags(self):
        axis_definitions.check_axis_definition(axis(shape=linear(MaterialTerm(material="num_a"), MaterialTerm(material="flag"))), {})

    @pytest.mark.parametrize(
        ("material_id", "mapping", "fragment"),
        [("flag", {"yes": 1.0}, "「はい」「いいえ」"), ("cat", {"true": 1.0}, "値の名前")],
    )
    def test_mapping_keys_must_be_of_the_materials_type(self, material_id, mapping, fragment):
        refused_by_check(axis(shape=CategoricalShape(material=material_id, mapping=mapping)), fragment)

    @pytest.mark.parametrize(("material_id", "mapping"), [("flag", {"true": 1.0}), ("cat", {"x": 1.0})])
    def test_mapping_keys_of_the_materials_type_are_accepted(self, material_id, mapping):
        axis_definitions.check_axis_definition(axis(shape=CategoricalShape(material=material_id, mapping=mapping)), {})

    def test_a_mapping_over_another_axis_is_not_type_checked(self):
        definition = axis(shape=CategoricalShape(material="other_axis", mapping={"x": 1.0}))

        axis_definitions.check_axis_definition(definition, {"other_axis": axis("other_axis")})

    @pytest.mark.parametrize(
        ("condition", "fragment"),
        [
            (PriorityCondition(material="nowhere", equals="true", value=0.0), "nowhere"),
            (PriorityCondition(material="other_axis", equals="true", value=0.0), "軸です"),
            (PriorityCondition(material="num_a", equals="true", value=0.0), "数値の材料"),
            (PriorityCondition(material="flag", equals="yes", value=0.0), "「yes」"),
            (PriorityCondition(material="cat", equals="true", value=0.0), "「true」"),
        ],
    )
    def test_a_condition_that_can_match_no_road_is_refused(self, condition, fragment):
        definition = axis(priority_overrides=[condition])

        refused_by_check(definition, fragment, axes={"other_axis": axis("other_axis", label="ほかの軸")})

    @pytest.mark.parametrize("condition", [("flag", "true"), ("cat", "residential")])
    def test_a_condition_on_a_value_the_material_has_is_accepted(self, condition):
        material_id, equals = condition
        definition = axis(priority_overrides=[PriorityCondition(material=material_id, equals=equals, value=0.0)])

        axis_definitions.check_axis_definition(definition, {})


class TestPublishImmutability:
    def test_a_draft_may_be_deleted(self):
        axis_definitions.check_publish_immutability(axis(), "deleted")

    def test_a_published_axis_is_not_deleted(self):
        with pytest.raises(axis_definitions.AxisPublishedImmutableError) as caught:
            axis_definitions.check_publish_immutability(axis(is_published=True), "deleted")

        assert (caught.value.axis_id, caught.value.action) == ("axis_a", "deleted")
        assert "削除できません" in str(caught.value)

    def test_a_published_axis_is_not_updated_without_knowing_the_new_contents(self):
        with pytest.raises(axis_definitions.AxisPublishedImmutableError) as caught:
            axis_definitions.check_publish_immutability(axis(is_published=True), "updated")

        assert "表示以外は変えられません" in str(caught.value)

    def test_a_published_axis_may_change_how_it_is_shown(self):
        published = axis(is_published=True)
        shown_differently = published.model_copy(
            update={
                "icon_id": "icon",
                "chip_label": "略",
                "panel_hint": "説明",
                "show_map_icon": False,
                "display_thresholds_override": [1.0],
                "display_band_labels_override": ["弱", "強"],
            }
        )

        axis_definitions.check_publish_immutability(published, "updated", shown_differently)

    def test_a_published_axis_may_not_change_anything_else(self):
        published = axis(is_published=True)

        with pytest.raises(axis_definitions.AxisPublishedImmutableError):
            axis_definitions.check_publish_immutability(published, "updated", published.model_copy(update={"default_weight": 2.0}))


@pytest.mark.usefixtures("catalog")
class TestMaterialExclusivity:
    def test_a_material_already_counted_by_another_axis_is_refused(self):
        existing = {"axis_b": axis("axis_b", label="先の軸", shape=linear(MaterialTerm(material="num_a")))}
        candidate = axis("axis_a", shape=linear(MaterialTerm(material="num_a"), MaterialTerm(material="num_b")))

        with pytest.raises(axis_definitions.AxisMaterialConflictError) as caught:
            axis_definitions.check_material_exclusivity(candidate, existing)

        error = caught.value
        assert (error.axis_id, error.conflicting_axis_id, error.overlapping_materials) == ("axis_a", "axis_b", {"num_a"})
        assert "「数値A」" in str(error) and "「先の軸」" in str(error)

    def test_a_material_in_a_condition_also_counts(self):
        existing = {"axis_b": axis("axis_b", shape=linear(MaterialTerm(material="num_b")),
                                   priority_overrides=[PriorityCondition(material="flag", equals="true", value=0.0)])}
        candidate = axis("axis_a", shape=CategoricalShape(material="flag", mapping={"true": 1.0}))

        with pytest.raises(axis_definitions.AxisMaterialConflictError):
            axis_definitions.check_material_exclusivity(candidate, existing)

    def test_two_axes_may_share_an_internal_axis(self):
        existing = {
            "inner": axis("inner"),
            "axis_b": axis("axis_b", shape=linear(MaterialTerm(material="inner"))),
        }

        axis_definitions.check_material_exclusivity(axis("axis_a", shape=linear(MaterialTerm(material="inner"))), existing)

    def test_an_axis_does_not_conflict_with_its_own_saved_version(self):
        axis_definitions.check_material_exclusivity(axis("axis_a"), {"axis_a": axis("axis_a")})


@pytest.mark.usefixtures("catalog")
class TestInternalAxisPublish:
    EXISTING = {"outer": axis("outer", label="外の軸", shape=linear(MaterialTerm(material="inner")))}

    def test_an_axis_another_axis_reads_is_not_published(self):
        with pytest.raises(axis_definitions.AxisInternalAxisPublishError) as caught:
            axis_definitions.check_internal_axis_not_published(axis("inner", is_published=True), self.EXISTING)

        assert (caught.value.axis_id, caught.value.referencing_axis_id) == ("inner", "outer")
        assert "「外の軸」" in str(caught.value)

    def test_an_axis_another_axis_reads_may_stay_a_draft(self):
        axis_definitions.check_internal_axis_not_published(axis("inner"), self.EXISTING)

    def test_an_axis_no_one_reads_may_be_published(self):
        axis_definitions.check_internal_axis_not_published(axis("lonely", is_published=True), self.EXISTING)


def scores(values) -> list:
    """NaNをNoneへ（配列の比較を読みやすくする）。"""
    return [None if math.isnan(v) else v for v in np.asarray(values, dtype=float).tolist()]


A2_B1 = linear(MaterialTerm(material="a", weight=2.0), MaterialTerm(material="b", weight=1.0))


class TestBreakpointScores:
    def test_the_weighted_sum_is_mapped_by_the_breakpoints(self):
        result = axis_definitions.evaluate_axis_array(axis(shape=A2_B1), {"a": np.array([2.0]), "b": np.array([1.0])})

        assert scores(result) == [50.0]

    def test_a_missing_required_material_leaves_the_road_unscored(self):
        result = axis_definitions.evaluate_axis_array(axis(shape=A2_B1), {"a": np.array([1.0, NAN]), "b": np.array([NAN, 1.0])})

        assert scores(result) == [None, None]

    def test_a_missing_optional_material_adds_nothing(self):
        shape = linear(MaterialTerm(material="a", weight=2.0), MaterialTerm(material="b", required=False))

        result = axis_definitions.evaluate_axis_array(axis(shape=shape), {"a": np.array([2.0]), "b": np.array([NAN])})

        assert scores(result) == [40.0]

    def test_a_road_with_every_material_missing_is_unscored_even_when_all_are_optional(self):
        shape = linear(MaterialTerm(material="a", required=False), MaterialTerm(material="b", required=False))

        result = axis_definitions.evaluate_axis_array(
            axis(shape=shape), {"a": np.array([NAN, NAN]), "b": np.array([NAN, 0.0])}
        )

        assert scores(result) == [None, 0.0]

    def test_a_flag_counts_as_one_when_set_and_is_never_missing(self):
        shape = linear(MaterialTerm(material="flag", weight=5.0))

        result = axis_definitions.evaluate_axis_array(axis(shape=shape), {"flag": np.array([True, False])})

        assert scores(result) == [50.0, 0.0]

    def test_python_values_score_the_same_way_with_none_as_missing(self):
        definition = axis(shape=A2_B1)

        result = axis_definitions.evaluate_axis_values(
            definition, {"a": [2.0, None, 1.0], "b": [1.0, 1.0, True], "unrelated": ["x", "y", "z"]}, 3
        )

        assert result == [50.0, None, 30.0]

    def test_python_values_without_a_material_leave_every_road_unscored(self):
        assert axis_definitions.evaluate_axis_values(axis(shape=A2_B1), {"a": [1.0, 2.0]}, 2) == [None, None]

    @given(st.floats(min_value=0.0, max_value=100.0))
    @example(0.15)
    @example(0.25)
    @example(0.35)
    def test_scores_round_to_one_decimal_as_python_round_does(self, x):
        """`.x5`の値は2進の実際の値で丸める（0.15と0.35は下へ、ちょうど表せる0.25は偶数の側へ）。"""
        shape = linear(MaterialTerm(material="a"), breakpoints=((0.0, 0.0), (100.0, 100.0)))

        assert shape.score_at(x) == round(x, 1)

    @given(
        st.lists(st.integers(-1000, 1000), min_size=1, max_size=6, unique=True),
        st.lists(st.floats(0.0, 100.0), min_size=6, max_size=6),
        st.floats(-1100.0, 1100.0),
    )
    def test_a_score_lies_on_the_line_through_the_breakpoints(self, xs, ys, x):
        points = list(zip(sorted(float(v) for v in xs), ys))
        shape = linear(MaterialTerm(material="a"), breakpoints=points)

        assert abs(shape.score_at(x) - on_the_line(points, x)) <= 0.05 + 1e-9

    @given(st.floats(-1000.0, 1000.0))
    def test_abs_scores_both_directions_of_a_signed_material_alike(self, x):
        shape = linear(MaterialTerm(material="a"), breakpoints=((0.0, 0.0), (500.0, 100.0)), preprocess="abs")

        assert axis_definitions.evaluate_axis_values(axis(shape=shape), {"a": [x, -x]}, 2) == [shape.score_at(abs(x))] * 2


def on_the_line(points: list[tuple[float, float]], x: float) -> float:
    """折れ線の素直な読み方: 両端の外は端の値、内側は挟む2点を結ぶ直線。"""
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    raise AssertionError("unreachable")


class TestMappingScores:
    def test_python_values_score_only_registered_values(self):
        definition = axis(shape=CategoricalShape(material="cat", mapping={"x": 10.0, "y": 20.0}))

        assert axis_definitions.evaluate_axis_values(definition, {"cat": ["y", None, "z"]}, 3) == [20.0, None, None]


class TestPriorityConditions:
    def test_a_matching_condition_decides_the_score_even_where_the_shape_cannot(self):
        definition = axis(priority_overrides=[PriorityCondition(material="flag", equals="true", value=5.0)])

        result = axis_definitions.evaluate_axis_array(
            definition, {"num_a": np.array([NAN, 1.0, NAN]), "flag": np.array([True, False, False])}
        )

        assert scores(result) == [5.0, 10.0, None]

    def test_the_first_matching_condition_in_order_wins(self):
        definition = axis(
            priority_overrides=[
                PriorityCondition(material="flag", equals="true", value=1.0),
                PriorityCondition(material="cat", equals="x", value=2.0),
            ]
        )

        result = axis_definitions.evaluate_axis_values(
            definition, {"num_a": [0.0, 0.0, 0.0], "flag": [True, False, None], "cat": ["x", "x", "y"]}, 3
        )

        assert result == [1.0, 2.0, 0.0]

    def test_an_unknown_flag_matches_neither_true_nor_false(self):
        definition = axis(
            priority_overrides=[
                PriorityCondition(material="flag", equals="true", value=1.0),
                PriorityCondition(material="flag", equals="false", value=2.0),
            ]
        )

        result = axis_definitions.evaluate_axis_array(
            definition, {"num_a": np.zeros(3), "flag": np.array([1.0, 0.0, NAN])}
        )

        assert scores(result) == [1.0, 2.0, 0.0]

    def test_a_coded_column_matches_by_value(self):
        definition = axis(priority_overrides=[PriorityCondition(material="cat", equals="x", value=1.0)])

        result = axis_definitions.evaluate_axis_array(definition, {"num_a": np.zeros(2), "cat": CategoricalColumn.encode(["x", "y"])})

        assert scores(result) == [1.0, 0.0]


class TestRawValues:
    def test_the_raw_value_is_the_sum_before_the_breakpoints(self):
        result = axis_definitions.axis_raw_value_array(
            axis(shape=A2_B1), {"a": np.array([9.0, NAN]), "b": np.array([9.0, 1.0])}
        )

        assert scores(result) == [27.0, None]

    def test_the_raw_value_keeps_an_optional_missing_material_as_nothing_added(self):
        shape = linear(MaterialTerm(material="a", weight=-1.0), MaterialTerm(material="b", required=False), preprocess="abs")

        assert axis_definitions.raw_values(shape, {"a": [4.0, None], "b": [None, None]}, 2) == [4.0, None]

    def test_a_mapping_axis_has_no_raw_value(self):
        shape = CategoricalShape(material="cat", mapping={"x": 1.0})

        assert axis_definitions.axis_raw_value_array(axis(shape=shape), {"cat": np.array(["x"], dtype=object)}) is None
        assert axis_definitions.raw_values(shape, {"cat": ["x", "y"]}, 2) == [None, None]

    def test_points_of_the_first_material_score_as_roads_without_the_others(self):
        shape = linear(MaterialTerm(material="a", weight=-2.0), MaterialTerm(material="b", required=False), preprocess="abs")

        points = axis_definitions.first_term_points(shape, [1.0, 10.0])

        assert [(p.x, p.score) for p in points] == [(2.0, 20.0), (20.0, 100.0)]

    def test_points_are_absent_when_another_material_is_required(self):
        assert axis_definitions.first_term_points(A2_B1, [1.0, 2.0]) == [None, None]
