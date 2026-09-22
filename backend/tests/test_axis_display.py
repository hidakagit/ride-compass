"""`domain/axis_display.py`——軸を地図にどう出すか。

材料カタログと軸カタログはこのファイルが丸ごと差し替える。実在の材料・軸に由来する事実は
1つも持ち込まない——このモジュールが決めているのは「与えられた材料の性質と軸の形から何が
導けるか」であって、どの材料が実在するかではない。
"""

import pytest

from app.domain import axis_display
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
from app.domain.axis_display import (
    _adjacent_midpoint_thresholds,
    _boolean_score_tile_input,
    _boolean_terms_thresholds,
    _drop_thresholds_that_share_a_score,
    _rescale_tile_input,
    axis_display_for,
)
from app.domain.material_catalog import CoverageExcluded, MaterialSpec, WayMaterialCoverageSpec
from app.domain.registry import TileInputSpec


def _spec(material_id: str, dtype: str = "numeric", missing="", **overrides) -> MaterialSpec:
    """欠損の意味を指定しない材料は欠損率を測らない扱いにする（`bool_default`は"false"）。"""
    overrides.setdefault("tile_property", f"t_{material_id}")
    coverage = (
        WayMaterialCoverageSpec(missing_condition="FALSE", source="テスト用", missing_semantics=missing)
        if missing
        else CoverageExcluded(reason="テスト用", missing_semantics="definite")
    )
    return MaterialSpec(
        material_id=material_id,
        label=material_id,
        description=f"架空の材料[{material_id}]",
        dtype=dtype,
        coverage=coverage,
        **overrides,
    )


#: 表示の判断に効く性質だけを変えた材料。名前は性質を表すだけで、実在の材料を指さない。
MATERIALS = {
    "num_a": _spec("num_a"),
    "num_b": _spec("num_b"),
    "num_scaled": _spec("num_scaled", tile_property_needs_runtime_scale=True),
    "num_directed": _spec("num_directed", tile_property_direction_dependent=True),
    "num_offtile": _spec("num_offtile", tile_property=None),
    "bool_unknown": _spec("bool_unknown", dtype="boolean", missing="unknown"),
    "bool_certain": _spec("bool_certain", dtype="boolean", missing="definite"),
    "cat_kind": _spec("cat_kind", dtype="categorical"),
}


@pytest.fixture(autouse=True)
def catalogs(monkeypatch) -> dict[str, AxisDefinition]:
    """材料と軸をこのファイルのものへ差し替える。返る辞書へ入れた軸だけが参照先になる。"""
    axes: dict[str, AxisDefinition] = {}
    monkeypatch.setattr(axis_display, "MATERIAL_CATALOG", MATERIALS)
    monkeypatch.setattr(axis_display, "AXIS_DEFINITIONS", axes)
    return axes


def _axis(shape, axis_id="subject", **overrides) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id, shape=shape, default_weight=0.1, label="対象軸", **overrides
    )


def _linear(terms, breakpoints=((0.0, 0.0), (10.0, 100.0)), preprocess="identity"):
    return BreakpointLinearShape(
        terms=list(terms), breakpoints=[tuple(bp) for bp in breakpoints], preprocess=preprocess
    )


class TestCategoricalAxes:
    def test_a_two_valued_boolean_axis_is_painted_from_the_two_scores(self):
        display = axis_display_for(
            _axis(CategoricalShape(material="bool_unknown", mapping={True: 0.0, False: 80.0}))
        )

        assert display.kind == "ramp"
        assert display.label == "対象軸"
        assert display.tile_inputs == [
            TileInputSpec(
                property="t_bool_unknown",
                boolean=True,
                true_value=0.0,
                false_value=80.0,
                has_unknown_fallback=True,
            )
        ]
        assert display.thresholds == [40.0]

    def test_a_material_whose_missing_value_means_false_gets_no_unknown_band(self):
        display = axis_display_for(
            _axis(CategoricalShape(material="bool_certain", mapping={True: 0.0, False: 80.0}))
        )

        assert display.tile_inputs[0].has_unknown_fallback is False

    def test_a_many_valued_axis_carries_its_mapping_and_bands_the_distinct_scores(self):
        display = axis_display_for(
            _axis(CategoricalShape(material="cat_kind", mapping={"a": 2.0, "b": 4.0, "c": 4.0}))
        )

        assert display.tile_inputs[0].categories == {"a": 2.0, "b": 4.0, "c": 4.0}
        # 未登録の値は寄与0ではなく「不明」へ倒す。
        assert display.tile_inputs[0].has_unknown_fallback is True
        assert display.thresholds == [3.0]

    def test_a_mapping_with_a_single_distinct_score_has_nothing_to_paint(self):
        display = axis_display_for(
            _axis(CategoricalShape(material="cat_kind", mapping={"a": 2.0, "b": 2.0}))
        )

        assert display.kind == "none"

    def test_a_mapping_mixing_booleans_and_strings_is_not_painted(self):
        display = axis_display_for(
            _axis(CategoricalShape(material="cat_kind", mapping={True: 1.0, "a": 2.0}))
        )

        assert display.kind == "none"


class TestLinearAxes:
    def test_numeric_terms_become_weighted_inputs_and_the_breakpoints_become_bands(self):
        display = axis_display_for(
            _axis(
                _linear(
                    [
                        MaterialTerm(material="num_a", weight=2.0),
                        MaterialTerm(material="num_b", weight=-1.0),
                    ],
                    breakpoints=[(0.0, 0.0), (10.0, 50.0), (20.0, 100.0)],
                )
            )
        )

        assert display.tile_inputs == [
            TileInputSpec(property="t_num_a", weight=2.0),
            TileInputSpec(property="t_num_b", weight=-1.0),
        ]
        assert display.thresholds == [10.0, 20.0]

    def test_a_material_whose_tile_value_needs_a_runtime_factor_is_marked_for_the_front(self):
        display = axis_display_for(_axis(_linear([MaterialTerm(material="num_scaled")])))

        assert display.tile_inputs[0].needs_runtime_scale is True

    def test_boolean_terms_contribute_their_weight_and_band_every_reachable_sum(self):
        display = axis_display_for(
            _axis(
                _linear(
                    [
                        MaterialTerm(material="bool_certain", weight=10.0),
                        MaterialTerm(material="bool_unknown", weight=20.0),
                    ],
                    breakpoints=[(0.0, 0.0), (30.0, 100.0)],
                )
            )
        )

        assert display.tile_inputs == [
            TileInputSpec(
                property="t_bool_certain", boolean=True, true_value=10.0, false_value=0.0
            ),
            # 欠損が「不明」を意味する材料は、軸の形が変わっても灰色の帯を保つ。落とすと
            # 未観測の道が寄与0＝最良の色で塗られる。
            TileInputSpec(
                property="t_bool_unknown",
                boolean=True,
                true_value=20.0,
                false_value=0.0,
                has_unknown_fallback=True,
            ),
        ]
        # 取りうる合計は 0 / 10 / 20 / 30 の4通り。
        assert display.thresholds == [5.0, 15.0, 25.0]

    def test_too_many_boolean_terms_are_not_painted(self):
        terms = [MaterialTerm(material="bool_certain", weight=float(i)) for i in range(1, 14)]

        display = axis_display_for(_axis(_linear(terms, breakpoints=[(0.0, 0.0), (91.0, 100.0)])))

        assert display.kind == "none"

    def test_an_axis_that_folds_the_sign_away_is_not_painted(self):
        display = axis_display_for(
            _axis(_linear([MaterialTerm(material="num_a")], preprocess="abs"))
        )

        assert display.kind == "none"


class TestMaterialsTheMapCannotPaint:
    @pytest.mark.parametrize(
        "material",
        ["num_offtile", "num_directed", "ghost"],
        ids=["タイルに無い", "進行方向で変わる", "存在しない"],
    )
    def test_the_axis_is_not_painted(self, material):
        display = axis_display_for(_axis(_linear([MaterialTerm(material=material)])))

        assert display.kind == "none"


class TestAxesThatReferenceOtherAxes:
    def test_a_referenced_categorical_axis_is_resolved_and_scaled_by_the_outer_weight(
        self, catalogs
    ):
        catalogs["inner"] = _axis(
            CategoricalShape(material="bool_certain", mapping={True: 10.0, False: 0.0}),
            axis_id="inner",
        )

        display = axis_display_for(
            _axis(_linear([MaterialTerm(material="inner", weight=0.5)]), axis_id="outer")
        )

        assert display.tile_inputs == [
            TileInputSpec(property="t_bool_certain", boolean=True, true_value=5.0, false_value=0.0)
        ]

    def test_a_referenced_single_term_axis_becomes_a_self_converting_input(self, catalogs):
        catalogs["inner"] = _axis(
            _linear([MaterialTerm(material="num_a")], breakpoints=[(0.0, 0.0), (4.0, 100.0)]),
            axis_id="inner",
        )

        display = axis_display_for(
            _axis(_linear([MaterialTerm(material="inner", weight=0.5)]), axis_id="outer")
        )

        assert display.tile_inputs == [
            TileInputSpec(property="t_num_a", breakpoints=[(0.0, 0.0), (4.0, 100.0)], weight=0.5)
        ]

    @pytest.mark.parametrize(
        "inner_shape",
        [
            _linear([MaterialTerm(material="num_a"), MaterialTerm(material="num_b")]),
            _linear([MaterialTerm(material="num_a", weight=2.0)]),
            _linear([MaterialTerm(material="num_a")], preprocess="abs"),
            _linear([MaterialTerm(material="bool_certain")]),
        ],
        ids=["複数の項", "内側の重みが1でない", "符号を畳む", "真偽値の材料"],
    )
    def test_a_referenced_axis_the_tile_cannot_reproduce_is_not_painted(
        self, catalogs, inner_shape
    ):
        catalogs["inner"] = _axis(inner_shape, axis_id="inner")

        display = axis_display_for(
            _axis(_linear([MaterialTerm(material="inner")]), axis_id="outer")
        )

        assert display.kind == "none"

    def test_a_two_level_reference_is_not_painted(self, catalogs):
        catalogs["middle"] = _axis(_linear([MaterialTerm(material="inner")]), axis_id="middle")
        catalogs["inner"] = _axis(_linear([MaterialTerm(material="num_a")]), axis_id="inner")

        display = axis_display_for(
            _axis(_linear([MaterialTerm(material="middle")]), axis_id="outer")
        )

        assert display.kind == "none"

    def test_axes_that_reference_each_other_terminate_without_painting(self, catalogs):
        catalogs["a"] = _axis(_linear([MaterialTerm(material="b")]), axis_id="a")
        catalogs["b"] = _axis(_linear([MaterialTerm(material="a")]), axis_id="b")

        assert axis_display_for(catalogs["a"]).kind == "none"

    def test_an_axis_that_references_itself_terminates_without_painting(self, catalogs):
        catalogs["loop"] = _axis(_linear([MaterialTerm(material="loop")]), axis_id="loop")

        assert axis_display_for(catalogs["loop"]).kind == "none"

    def test_a_referenced_categorical_axis_that_cannot_be_painted_stops_the_outer_axis(
        self, catalogs
    ):
        catalogs["inner"] = _axis(
            CategoricalShape(material="cat_kind", mapping={"a": 2.0, "b": 2.0}), axis_id="inner"
        )

        display = axis_display_for(
            _axis(_linear([MaterialTerm(material="inner")]), axis_id="outer")
        )

        assert display.kind == "none"

    def test_a_categorical_axis_whose_value_comes_from_another_axis_is_not_painted(self, catalogs):
        catalogs["inner"] = _axis(_linear([MaterialTerm(material="num_a")]), axis_id="inner")

        display = axis_display_for(
            _axis(CategoricalShape(material="inner", mapping={"a": 2.0, "b": 4.0}), axis_id="outer")
        )

        assert display.kind == "none"


class TestBands:
    def test_an_override_replaces_the_derived_bands(self):
        display = axis_display_for(
            _axis(
                _linear([MaterialTerm(material="num_a")]),
                display_thresholds_override=[3.0, 7.0],
            )
        )

        assert display.thresholds == [3.0, 7.0]

    def test_an_override_still_drops_bands_the_curve_cannot_separate(self):
        display = axis_display_for(
            _axis(
                _linear([MaterialTerm(material="num_a")], breakpoints=[(0.0, 0.0), (5.0, 100.0)]),
                display_thresholds_override=[2.0, 7.0, 12.0],
            )
        )

        # 5で100へ達するため、7と12は同じ評価になる。
        assert display.thresholds == [2.0, 7.0]

    def test_an_axis_that_cannot_be_painted_keeps_its_label_and_paints_nothing(self):
        display = axis_display_for(_axis(_linear([MaterialTerm(material="num_directed")])))

        assert (display.kind, display.label, display.tile_inputs, display.thresholds) == (
            "none",
            "対象軸",
            [],
            [],
        )


class TestAdjacentMidpointThresholds:
    def test_takes_the_midpoint_of_each_adjacent_pair(self):
        assert _adjacent_midpoint_thresholds([0.0, 10.0, 40.0]) == [5.0, 25.0]

    def test_sorts_before_pairing(self):
        assert _adjacent_midpoint_thresholds([40.0, 0.0, 10.0]) == [5.0, 25.0]

    def test_collapses_duplicate_scores(self):
        assert _adjacent_midpoint_thresholds([10.0, 10.0, 30.0]) == [20.0]

    @pytest.mark.parametrize("scores", [[], [7.0], [7.0, 7.0]])
    def test_a_single_distinct_score_has_no_boundary(self, scores):
        assert _adjacent_midpoint_thresholds(scores) == []


class TestBooleanTermsThresholds:
    def test_boundaries_come_from_every_subset_sum_including_none_selected(self):
        assert _boolean_terms_thresholds([10.0, 20.0], cap=None) == [5.0, 15.0, 25.0]

    def test_sums_are_clamped_to_the_cap(self):
        assert _boolean_terms_thresholds([10.0, 20.0], cap=20.0) == [5.0, 15.0]

    def test_negative_weights_widen_the_range_downward(self):
        assert _boolean_terms_thresholds([-50.0, 50.0], cap=50.0) == [-25.0, 25.0]

    def test_no_terms_means_no_boundary(self):
        assert _boolean_terms_thresholds([], cap=None) == []


class TestDropThresholdsThatShareAScore:
    def test_keeps_boundaries_that_the_curve_separates(self):
        shape = _linear([MaterialTerm(material="num_a")])

        assert _drop_thresholds_that_share_a_score([2.0, 4.0, 6.0], shape) == [2.0, 4.0, 6.0]

    def test_drops_boundaries_beyond_the_point_the_curve_saturates(self):
        shape = _linear([MaterialTerm(material="num_a")])

        assert _drop_thresholds_that_share_a_score([5.0, 12.0, 14.0], shape) == [5.0, 12.0]

    def test_drops_a_boundary_whose_score_goes_back_down(self):
        shape = _linear(
            [MaterialTerm(material="num_a")], breakpoints=[(0.0, 0.0), (10.0, 100.0), (20.0, 0.0)]
        )

        assert _drop_thresholds_that_share_a_score([5.0, 15.0], shape) == [5.0]

    def test_abs_preprocess_folds_the_negative_side_onto_the_positive(self):
        shape = _linear([MaterialTerm(material="num_a")], preprocess="abs")

        assert _drop_thresholds_that_share_a_score([-5.0, 5.0], shape) == [-5.0]

    def test_scores_closer_than_one_tenth_of_a_point_are_treated_as_the_same(self):
        shape = _linear(
            [MaterialTerm(material="num_a")], breakpoints=[(0.0, 0.0), (10000.0, 100.0)]
        )

        assert _drop_thresholds_that_share_a_score([1.0, 2.0], shape) == [1.0]


class TestRescaleTileInput:
    def test_category_scores_are_scaled_and_the_weight_field_is_left_alone(self):
        rescaled = _rescale_tile_input(
            TileInputSpec(property="p", categories={"a": 2.0, "b": -4.0}), weight=0.5
        )

        assert rescaled.categories == {"a": 1.0, "b": -2.0}
        assert rescaled.weight == 1.0

    def test_boolean_values_are_scaled_and_the_weight_field_is_left_alone(self):
        rescaled = _rescale_tile_input(
            TileInputSpec(property="p", boolean=True, true_value=10.0, false_value=-2.0),
            weight=0.5,
        )

        assert (rescaled.true_value, rescaled.false_value) == (5.0, -1.0)
        assert rescaled.weight == 1.0

    def test_a_plain_numeric_input_is_scaled_through_the_weight_field(self):
        rescaled = _rescale_tile_input(TileInputSpec(property="p", weight=4.0), weight=0.5)

        assert rescaled.weight == 2.0


class TestBooleanScoreTileInput:
    def test_carries_the_two_scores_onto_the_tile_property(self):
        tile_input = _boolean_score_tile_input(MATERIALS["bool_certain"], 0.0, 80.0)

        assert (tile_input.property, tile_input.boolean) == ("t_bool_certain", True)
        assert (tile_input.true_value, tile_input.false_value) == (0.0, 80.0)
