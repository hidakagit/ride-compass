"""`domain/axis_definitions.py`——軸の宣言と、その評価。

ここで見ないもの:
- 依存順の並べ替え・0次条件の短絡・分類shapeの文字列キー → `test_axis_hierarchy.py`
- 地図表示（ramp）の導出 → `test_axis_display.py`
- 折れ点補間そのもの・テーブル引きそのもの → `test_axis_templates.py`

**材料カタログの中身には踏み込まない。** 「どれが材料でどれが軸参照か」「材料がどの一次属性
に属するか」はカタログ側の話なので、差し替えて与える。
"""

from contextlib import contextmanager

import numpy as np
import pytest

from app.domain import material_catalog
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    AxisInternalAxisPublishError,
    AxisMaterialConflictError,
    AxisPublishedImmutableError,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    axis_raw_value_array,
    check_internal_axis_not_published,
    check_material_exclusivity,
    check_publish_immutability,
    default_axis_weights,
    evaluate_axes_scalar,
    evaluate_axis_array,
    evaluate_axis_scalar,
    has_axis_raw_value_array,
    is_cosmetic_only_update,
    primary_attribute_ids_for,
    referenced_materials,
    time_scoped_weights,
)

LINE = [(0.0, 0.0), (10.0, 100.0)]


def _axis(axis_id: str = "axis", materials: list[str] | None = None, **overrides) -> AxisDefinition:
    """区分線形の軸。見たい性質だけを上書きで与える。"""
    terms = [MaterialTerm(material=m) for m in (materials or ["m_a"])]
    return AxisDefinition(
        axis_id=axis_id,
        shape=overrides.pop("shape", BreakpointLinearShape(terms=terms, breakpoints=LINE)),
        default_weight=overrides.pop("default_weight", 0.1),
        label=overrides.pop("label", f"軸[{axis_id}]"),
        **overrides,
    )


def _linear(terms: list[MaterialTerm], breakpoints=LINE, preprocess: str = "identity", **overrides):
    return _axis(shape=BreakpointLinearShape(terms=terms, preprocess=preprocess, breakpoints=breakpoints), **overrides)


@contextmanager
def _catalog(material_ids: set[str], primary_attributes: dict[str, str] | None = None):
    """どのidが材料か（残りは軸参照）と、材料がどの一次属性に属するかを差し替える。"""
    attributes = primary_attributes or {}
    specs = {m: type("Spec", (), {"primary_attribute_id": attributes.get(m)})() for m in material_ids}
    known, catalog = material_catalog.is_known_material, material_catalog.MATERIAL_CATALOG
    material_catalog.is_known_material = lambda m: m in material_ids
    material_catalog.MATERIAL_CATALOG = specs
    try:
        yield
    finally:
        material_catalog.is_known_material, material_catalog.MATERIAL_CATALOG = known, catalog


@contextmanager
def _registry(definitions: dict[str, AxisDefinition]):
    """`AXIS_DEFINITIONS`を丸ごと差し替える（プロセス内の可変な大域辞書のため）。"""
    original = dict(AXIS_DEFINITIONS)
    AXIS_DEFINITIONS.clear()
    AXIS_DEFINITIONS.update(definitions)
    try:
        yield
    finally:
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(original)


class TestReferencedMaterials:
    """片方が0次条件を見落とすと、検証を素通りした軸が実行時に落ちる。"""

    def test_a_linear_shape_lists_every_term(self):
        shape = BreakpointLinearShape(
            terms=[MaterialTerm(material="m_a"), MaterialTerm(material="m_b")], breakpoints=LINE
        )

        assert referenced_materials(shape, []) == ["m_a", "m_b"]

    def test_a_categorical_shape_lists_its_single_material(self):
        assert referenced_materials(CategoricalShape(material="m_a", mapping={True: 0.0}), []) == ["m_a"]

    def test_priority_conditions_are_listed_too(self):
        from app.domain.axis_definitions import PriorityCondition

        shape = BreakpointLinearShape(terms=[MaterialTerm(material="m_a")], breakpoints=LINE)
        overrides = [PriorityCondition(material="m_b", equals="true", value=0.0)]

        assert referenced_materials(shape, overrides) == ["m_a", "m_b"]

    def test_a_material_used_twice_appears_once_in_declaration_order(self):
        from app.domain.axis_definitions import PriorityCondition

        shape = BreakpointLinearShape(
            terms=[MaterialTerm(material="m_b"), MaterialTerm(material="m_a")], breakpoints=LINE
        )
        overrides = [PriorityCondition(material="m_a", equals="true", value=0.0)]

        assert referenced_materials(shape, overrides) == ["m_b", "m_a"]


class TestPublishedAxesAreImmutable:

    def test_a_draft_can_be_changed_freely(self):
        existing = _axis(is_published=False)

        check_publish_immutability(existing, "update", _axis(label="別の名前"))

    def test_a_published_axis_cannot_be_deleted(self):
        """削除は差分を伴わないため、一律で拒否する。"""
        with pytest.raises(AxisPublishedImmutableError):
            check_publish_immutability(_axis(is_published=True), "delete")

    def test_a_published_axis_can_have_its_display_fields_changed(self):
        existing = _axis(is_published=True)
        candidate = existing.model_copy(update={"chip_label": "別のチップ", "show_map_icon": False})

        check_publish_immutability(existing, "update", candidate)

    def test_a_published_axis_cannot_have_its_calculation_changed(self):
        existing = _axis(is_published=True)
        candidate = existing.model_copy(
            update={"shape": BreakpointLinearShape(terms=[MaterialTerm(material="m_b")], breakpoints=LINE)}
        )

        with pytest.raises(AxisPublishedImmutableError):
            check_publish_immutability(existing, "update", candidate)

    def test_the_cosmetic_check_sees_through_every_display_field(self):
        """表示専用フィールドを1つでも見落とすと、その項目だけ公開後に直せなくなる。"""
        existing = _axis(is_published=True)
        cosmetic = existing.model_copy(
            update={
                "icon_id": "incline",
                "chip_label": "チップ",
                "panel_hint": "説明",
                "show_map_icon": False,
                "display_thresholds_override": [1.0],
                "display_band_labels_override": ["低", "高"],
            }
        )

        assert is_cosmetic_only_update(existing, cosmetic) is True

    def test_a_change_outside_the_display_fields_is_not_cosmetic(self):
        existing = _axis(is_published=True)

        assert is_cosmetic_only_update(existing, existing.model_copy(update={"label": "別"})) is False


class TestMaterialExclusivity:

    def test_two_axes_sharing_a_material_are_rejected(self):
        with _catalog({"m_a", "m_b"}):
            with pytest.raises(AxisMaterialConflictError):
                check_material_exclusivity(
                    _axis("new", ["m_a"]), {"old": _axis("old", ["m_a", "m_b"])}
                )

    def test_disjoint_materials_are_allowed(self):
        with _catalog({"m_a", "m_b"}):
            check_material_exclusivity(_axis("new", ["m_a"]), {"old": _axis("old", ["m_b"])})

    def test_an_axis_is_not_compared_with_itself(self):
        """更新のたびに自分の材料と衝突しては、公開済み軸の表示を直すこともできない。"""
        with _catalog({"m_a"}):
            check_material_exclusivity(_axis("same", ["m_a"]), {"same": _axis("same", ["m_a"])})

    def test_a_shared_internal_axis_is_not_a_conflict(self):
        with _catalog({"m_a"}):
            check_material_exclusivity(
                _axis("new", ["inner"]), {"old": _axis("old", ["inner"])}
            )

    def test_the_error_names_both_axes_and_the_overlap(self):
        with _catalog({"m_a"}):
            with pytest.raises(AxisMaterialConflictError) as caught:
                check_material_exclusivity(_axis("new", ["m_a"]), {"old": _axis("old", ["m_a"])})

        assert "new" in str(caught.value)
        assert "old" in str(caught.value)
        assert "m_a" in str(caught.value)


class TestInternalAxesStayUnpublished:

    def test_an_unpublished_axis_is_always_allowed(self):
        with _catalog({"m_a"}):
            check_internal_axis_not_published(
                _axis("inner", ["m_a"], is_published=False), {"outer": _axis("outer", ["inner"])}
            )

    def test_publishing_a_referenced_axis_is_rejected(self):
        with _catalog({"m_a"}):
            with pytest.raises(AxisInternalAxisPublishError):
                check_internal_axis_not_published(
                    _axis("inner", ["m_a"], is_published=True), {"outer": _axis("outer", ["inner"])}
                )

    def test_publishing_an_unreferenced_axis_is_allowed(self):
        with _catalog({"m_a", "m_b"}):
            check_internal_axis_not_published(
                _axis("free", ["m_a"], is_published=True), {"other": _axis("other", ["m_b"])}
            )

    def test_an_axis_referencing_itself_is_not_counted(self):
        with _catalog({"m_a"}):
            check_internal_axis_not_published(
                _axis("same", ["m_a"], is_published=True), {"same": _axis("same", ["same"])}
            )


class TestPrimaryAttributeIds:

    def test_it_descends_through_referenced_axes(self):
        inner = _axis("inner", ["m_a"])
        outer = _axis("outer", ["inner", "m_b"])

        with _registry({"inner": inner, "outer": outer}):
            with _catalog({"m_a", "m_b"}, {"m_a": "attr_a", "m_b": "attr_b"}):
                assert set(primary_attribute_ids_for(outer)) == {"attr_a", "attr_b"}

    def test_a_material_without_a_primary_attribute_does_not_appear(self):
        axis = _axis("axis", ["m_a", "m_b"])

        with _registry({"axis": axis}):
            with _catalog({"m_a", "m_b"}, {"m_a": "attr_a"}):
                assert primary_attribute_ids_for(axis) == ["attr_a"]

    def test_the_same_attribute_is_listed_once(self):
        axis = _axis("axis", ["m_a", "m_b"])

        with _registry({"axis": axis}):
            with _catalog({"m_a", "m_b"}, {"m_a": "shared", "m_b": "shared"}):
                assert primary_attribute_ids_for(axis) == ["shared"]

    def test_a_cycle_between_axes_stops_instead_of_hanging(self):
        a = _axis("a", ["b", "m_a"])
        b = _axis("b", ["a"])

        with _registry({"a": a, "b": b}):
            with _catalog({"m_a"}, {"m_a": "attr_a"}):
                assert primary_attribute_ids_for(a) == ["attr_a"]


class TestDefaultAxisWeights:
    def test_only_published_axes_get_a_default_weight(self):
        """ここへ混ぜると、リクエストの検証が内部軸の指定を要求し始める。"""
        with _registry(
            {
                "shown": _axis("shown", default_weight=0.3, is_published=True),
                "inner": _axis("inner", default_weight=0.9, is_published=False),
            }
        ):
            assert default_axis_weights() == {"shown": 0.3}

    def test_an_empty_registry_gives_an_empty_mapping(self):
        with _registry({}):
            assert default_axis_weights() == {}


class TestTimeScopedWeights:
    """時間帯限定の軸は、その時間帯の外では効かせない。"""

    def test_an_always_axis_is_untouched(self):
        with _registry({"a": _axis("a", time_scope="always")}):
            assert time_scoped_weights({"a": 0.5}, frozenset()) == {"a": 0.5}

    def test_a_scoped_axis_is_zeroed_outside_its_scope(self):
        with _registry({"n": _axis("n", time_scope="night_only")}):
            assert time_scoped_weights({"n": 0.5}, frozenset()) == {"n": 0.0}

    def test_a_scoped_axis_keeps_its_weight_inside_its_scope(self):
        with _registry({"n": _axis("n", time_scope="night_only")}):
            assert time_scoped_weights({"n": 0.5}, frozenset({"night_only"})) == {"n": 0.5}

    def test_a_weight_for_an_axis_that_no_longer_exists_is_left_alone(self):
        with _registry({"n": _axis("n", time_scope="night_only")}):
            assert time_scoped_weights({"gone": 0.5}, frozenset()) == {"gone": 0.5}

    def test_the_given_mapping_is_not_modified(self):
        original = {"n": 0.5}

        with _registry({"n": _axis("n", time_scope="night_only")}):
            time_scoped_weights(original, frozenset())

        assert original == {"n": 0.5}


class TestEvaluateAxisScalar:

    def test_a_value_between_breakpoints_is_interpolated(self):
        assert evaluate_axis_scalar(_linear([MaterialTerm(material="m_a")], [(0.0, 0.0), (10.0, 50.0)]), {"m_a": 4.0}) == 20.0

    def test_values_outside_the_range_clamp_to_the_declared_ends(self):
        axis = _linear([MaterialTerm(material="m_a")], [(0.0, 10.0), (10.0, 50.0)])

        assert evaluate_axis_scalar(axis, {"m_a": -5.0}) == 10.0
        assert evaluate_axis_scalar(axis, {"m_a": 99.0}) == 50.0

    def test_the_abs_preprocess_makes_the_sign_irrelevant(self):
        axis = _linear([MaterialTerm(material="m_a")], preprocess="abs")

        assert evaluate_axis_scalar(axis, {"m_a": -4.0}) == evaluate_axis_scalar(axis, {"m_a": 4.0})

    def test_the_score_is_rounded_to_one_decimal(self):
        axis = _linear([MaterialTerm(material="m_a")], [(0.0, 0.0), (3.0, 100.0)])

        assert evaluate_axis_scalar(axis, {"m_a": 1.0}) == 33.3

    def test_a_missing_required_material_makes_the_axis_unevaluable(self):
        axis = _linear(
            [MaterialTerm(material="m_a", required=True), MaterialTerm(material="m_b", required=False)]
        )

        assert evaluate_axis_scalar(axis, {"m_b": 5.0}) is None

    def test_a_missing_optional_material_only_drops_that_term(self):
        axis = _linear(
            [
                MaterialTerm(material="m_a", weight=1.0, required=False),
                MaterialTerm(material="m_b", weight=1.0, required=False),
            ]
        )

        assert evaluate_axis_scalar(axis, {"m_a": 4.0}) == evaluate_axis_scalar(axis, {"m_a": 4.0, "m_b": 0.0})

    def test_no_term_with_a_value_is_unevaluable_rather_than_zero(self):
        axis = _linear(
            [MaterialTerm(material="m_a", required=False), MaterialTerm(material="m_b", required=False)]
        )

        assert evaluate_axis_scalar(axis, {}) is None

    def test_a_zero_weight_term_does_not_move_the_total(self):
        axis = _linear(
            [MaterialTerm(material="m_a", weight=1.0), MaterialTerm(material="m_b", weight=0.0)]
        )

        assert evaluate_axis_scalar(axis, {"m_a": 4.0, "m_b": 1000.0}) == 40.0

    def test_boolean_terms_are_summed_and_lose_the_heavier_term_s_priority(self):
        """真偽の項は重み付き和になるため、**重い項の「優先」は同時成立時に保たれない**。
        単独なら重い項ほど低い得点になるが、両方立つと和が両者と異なる値へ動く
        （ここでは下端クランプが効いて重い方と同じ0になる）。軸スタジオで「AならXにしたい」
        を表したいなら0次条件を使う。
        """
        axis = _linear(
            [MaterialTerm(material="m_a", weight=-2.0), MaterialTerm(material="m_b", weight=-1.0)],
            [(-2.0, 0.0), (0.0, 100.0)],
        )

        def score(**flags: bool) -> float | None:
            return evaluate_axis_scalar(axis, {"m_a": False, "m_b": False, **flags})

        assert score() == 100.0
        assert score(m_b=True) == 50.0
        assert score(m_a=True) == 0.0
        assert score(m_a=True, m_b=True) == 0.0

    def test_a_categorical_axis_without_its_material_is_unevaluable(self):
        axis = _axis(shape=CategoricalShape(material="m_a", mapping={True: 0.0, False: 80.0}))

        assert evaluate_axis_scalar(axis, {}) is None
        assert evaluate_axis_scalar(axis, {"m_a": False}) == 80.0


class TestEvaluateAxesScalar:

    def test_it_returns_only_published_axes(self):
        inner = _axis("inner", ["m_a"], is_published=False)
        outer = _axis("outer", ["inner"], is_published=True)

        with _registry({"inner": inner, "outer": outer}):
            with _catalog({"m_a"}):
                scores, _ = evaluate_axes_scalar({"m_a": 5.0})

        assert set(scores) == {"outer"}

    def test_the_inner_result_feeds_the_outer_axis(self):
        inner = _axis("inner", ["m_a"], is_published=False)
        outer = _axis("outer", ["inner"], is_published=True)

        with _registry({"inner": inner, "outer": outer}):
            with _catalog({"m_a"}):
                scores, materials = evaluate_axes_scalar({"m_a": 5.0})

        # 内部軸は m_a=5 → 50点。外側はそれを材料として同じ折れ線へ通すので上端で止まる。
        assert materials["inner"] == 50.0
        assert scores["outer"] == 100.0

    def test_an_unevaluable_published_axis_keeps_its_key(self):
        """キーごと落とすと、呼び出し側が「軸が無い」と「評価できなかった」を区別できない。"""
        axis = _axis("axis", ["m_a"], is_published=True)

        with _registry({"axis": axis}):
            with _catalog({"m_a"}):
                scores, _ = evaluate_axes_scalar({})

        assert scores == {"axis": None}

    def test_the_second_value_carries_the_inner_axes_too(self):
        inner = _axis("inner", ["m_a"], is_published=False)

        with _registry({"inner": inner}):
            with _catalog({"m_a"}):
                _, materials = evaluate_axes_scalar({"m_a": 5.0})

        assert "inner" in materials
        assert materials["m_a"] == 5.0


class TestAxisRawValueArray:

    def test_a_linear_axis_reports_the_weighted_total(self):
        axis = _linear([MaterialTerm(material="m_a", weight=2.0)])

        assert axis_raw_value_array(axis, {"m_a": np.array([3.0])}).tolist() == [6.0]

    def test_the_preprocess_is_applied(self):
        axis = _linear([MaterialTerm(material="m_a")], preprocess="abs")

        assert axis_raw_value_array(axis, {"m_a": np.array([-3.0])}).tolist() == [3.0]

    def test_an_element_is_missing_only_when_every_term_is_missing(self):
        """1つでも観測できていれば生値は出る。どれか欠けただけで欠損にすると、生値が
        ほとんどの区間で出なくなる。
        """
        axis = _linear(
            [
                MaterialTerm(material="m_a", weight=1.0, required=False),
                MaterialTerm(material="m_b", weight=1.0, required=False),
            ]
        )

        result = axis_raw_value_array(
            axis, {"m_a": np.array([3.0, np.nan]), "m_b": np.array([np.nan, np.nan])}
        )

        assert result[0] == 3.0
        assert np.isnan(result[1])

    def test_a_categorical_axis_has_no_raw_value(self):
        axis = _axis(shape=CategoricalShape(material="m_a", mapping={True: 0.0}))

        assert axis_raw_value_array(axis, {"m_a": np.array([True])}) is None

    def test_whether_there_is_a_raw_value_is_decided_without_data(self):
        assert has_axis_raw_value_array(_linear([MaterialTerm(material="m_a")])) is True
        assert has_axis_raw_value_array(_axis(shape=CategoricalShape(material="m_a", mapping={True: 0.0}))) is False


class TestEvaluateAxisArray:

    def test_it_agrees_with_the_scalar_version(self):
        axis = _linear([MaterialTerm(material="m_a")], [(0.0, 0.0), (10.0, 50.0)])
        values = [0.0, 4.0, 10.0, 99.0]

        array = evaluate_axis_array(axis, {"m_a": np.array(values)})

        assert array.tolist() == [evaluate_axis_scalar(axis, {"m_a": v}) for v in values]

    def test_a_required_material_propagates_its_missing_marker(self):
        axis = _linear([MaterialTerm(material="m_a", required=True)])

        assert np.isnan(evaluate_axis_array(axis, {"m_a": np.array([np.nan])})).all()

    def test_an_optional_missing_material_contributes_nothing(self):
        axis = _linear(
            [
                MaterialTerm(material="m_a", weight=1.0, required=False),
                MaterialTerm(material="m_b", weight=1.0, required=False),
            ]
        )

        result = evaluate_axis_array(
            axis, {"m_a": np.array([4.0]), "m_b": np.array([np.nan])}
        )

        assert result.tolist() == [40.0]

    def test_an_element_with_every_term_missing_is_unevaluable_rather_than_zero(self):
        axis = _linear(
            [MaterialTerm(material="m_a", required=False), MaterialTerm(material="m_b", required=False)]
        )

        result = evaluate_axis_array(
            axis, {"m_a": np.array([np.nan]), "m_b": np.array([np.nan])}
        )

        assert np.isnan(result).all()

    def test_a_boolean_material_has_no_missing_elements(self):
        axis = _linear([MaterialTerm(material="m_a", weight=10.0)])

        result = evaluate_axis_array(axis, {"m_a": np.array([True, False])})

        assert result.tolist() == [100.0, 0.0]

    def test_a_categorical_axis_is_looked_up_element_by_element(self):
        axis = _axis(shape=CategoricalShape(material="m_a", mapping={True: 0.0, False: 80.0}))

        assert evaluate_axis_array(axis, {"m_a": np.array([True, False])}).tolist() == [0.0, 80.0]

    def test_a_priority_condition_overrides_the_shape(self):
        from app.domain.axis_definitions import PriorityCondition

        axis = _linear(
            [MaterialTerm(material="m_a")],
            priority_overrides=[PriorityCondition(material="m_b", equals="hit", value=999.0)],
        )

        result = evaluate_axis_array(
            axis, {"m_a": np.array([5.0, 5.0]), "m_b": np.array(["hit", "miss"], dtype=object)}
        )

        assert result.tolist() == [999.0, 50.0]

    def test_the_first_matching_condition_wins(self):
        """条件を順に重ねると最後のものが残るため、逆順に重ねる。"""
        from app.domain.axis_definitions import PriorityCondition

        axis = _linear(
            [MaterialTerm(material="m_a")],
            priority_overrides=[
                PriorityCondition(material="m_b", equals="hit", value=1.0),
                PriorityCondition(material="m_b", equals="hit", value=2.0),
            ],
        )

        result = evaluate_axis_array(axis, {"m_a": np.array([5.0]), "m_b": np.array(["hit"], dtype=object)})

        assert result.tolist() == [1.0]

    def test_a_boolean_condition_is_compared_as_a_word(self):
        from app.domain.axis_definitions import PriorityCondition

        axis = _linear(
            [MaterialTerm(material="m_a")],
            priority_overrides=[PriorityCondition(material="m_b", equals="true", value=7.0)],
        )

        result = evaluate_axis_array(axis, {"m_a": np.array([5.0, 5.0]), "m_b": np.array([True, False])})

        assert result.tolist() == [7.0, 50.0]


