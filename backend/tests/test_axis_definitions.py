import numpy as np
import pytest

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    AxisInternalAxisPublishError,
    AxisMaterialConflictError,
    AxisPublishedImmutableError,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    check_internal_axis_not_published,
    check_material_exclusivity,
    check_publish_immutability,
    is_cosmetic_only_update,
    axis_raw_value_array,
    evaluate_axis_scalar,
)


def _boolean_terms_axis() -> AxisDefinition:
    """負の重みを持つ真偽値の項だけからなる軸。該当するほど合計が下がり、得点も下がる。"""
    return AxisDefinition(
        axis_id="synthetic_bool_sum",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="bool_a", weight=-2.0),
                MaterialTerm(material="bool_b", weight=-1.0),
            ],
            breakpoints=[(-2.0, 0.0), (0.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
    )


def test_boolean_terms_axis_sums_weights_without_keeping_priority():
    """真偽値の項は重み付き和になるため、重い項の「優先」は同時成立時に保たれない。

    単独なら重い項ほど低い得点になるが、複数が同時に立つと和が両者と異なる値へ動く。
    飽和（breakpointsの両端クランプ）はその和が範囲外へ出たときにだけ効く。
    """
    axis = _boolean_terms_axis()
    base = {"bool_a": False, "bool_b": False}

    def score(**flags: bool) -> float | None:
        return evaluate_axis_scalar(axis, {**base, **flags})

    assert score() == 100.0
    assert score(bool_b=True) == 50.0
    assert score(bool_a=True) == 0.0
    # 同時成立は単純な線形和（-2 + -1 = -3）で、下端クランプが効いて0.0になる。
    assert score(bool_a=True, bool_b=True) == 0.0


def _definition(axis_id: str, material: str, is_published: bool = False) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material=material)], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label=f"テスト軸[{axis_id}]",
        description="テスト用ダミー軸",
        category="推定",
        is_published=is_published,
    )


def test_every_registered_axis_passes_exclusivity_check():
    # 登録済みの全軸を「自分以外の全軸」に対して検査する（材料の二重帰属が無いこと）。
    for axis_id, definition in AXIS_DEFINITIONS.items():
        others = {other_id: other for other_id, other in AXIS_DEFINITIONS.items() if other_id != axis_id}
        check_material_exclusivity(definition, others)  # 例外が出ないことを確認


def test_rejects_new_axis_reusing_existing_material():
    existing = {"gradient": AXIS_DEFINITIONS["gradient"]}
    candidate = _definition("gradient_variant", "gradient_percent")

    with pytest.raises(AxisMaterialConflictError) as exc_info:
        check_material_exclusivity(candidate, existing)

    assert exc_info.value.overlapping_materials == {"gradient_percent"}
    assert exc_info.value.conflicting_axis_id == "gradient"


def test_allows_disjoint_materials():
    existing = {"gradient": AXIS_DEFINITIONS["gradient"]}
    candidate = _definition("new_axis", "brand_new_material")

    check_material_exclusivity(candidate, existing)  # 例外が出ないことを確認


def test_update_skips_self_comparison():
    # 更新時、existing辞書に自分自身（同じaxis_id）が含まれていても衝突扱いしない。
    existing = {"gradient": AXIS_DEFINITIONS["gradient"]}
    candidate = _definition("gradient", "gradient_percent")

    check_material_exclusivity(candidate, existing)  # 例外が出ないことを確認


def test_check_publish_immutability_allows_draft():
    draft = _definition("draft_axis", "material_a", is_published=False)

    check_publish_immutability(draft, "updated")  # 例外が出ないことを確認


def test_check_publish_immutability_rejects_published():
    published = _definition("published_axis", "material_a", is_published=True)

    with pytest.raises(AxisPublishedImmutableError) as exc_info:
        check_publish_immutability(published, "deleted")

    assert exc_info.value.axis_id == "published_axis"
    assert exc_info.value.action == "deleted"


def test_check_publish_immutability_rejects_published_semantic_change():
    # 表示専用フィールド以外（ここではdefault_weight）
    # が変わっていれば、candidateを渡しても拒否する。
    published = _definition("published_axis", "material_a", is_published=True)
    candidate = published.model_copy(update={"default_weight": 0.9})

    with pytest.raises(AxisPublishedImmutableError):
        check_publish_immutability(published, "updated", candidate)


def test_check_publish_immutability_allows_published_cosmetic_only_change():
    # 表示専用フィールド（icon_id等）だけの差分ならcandidateを渡すことで
    # 公開済み軸への更新を例外的に許可する。
    published = _definition("published_axis", "material_a", is_published=True)
    candidate = published.model_copy(update={"icon_id": "new_icon", "chip_label": "新略称"})

    check_publish_immutability(published, "updated", candidate)  # 例外が出ないことを確認


def test_is_cosmetic_only_update_true_for_display_fields_only():
    existing = _definition("axis_a", "material_a", is_published=True)
    candidate = existing.model_copy(
        update={
            "icon_id": "x",
            "chip_label": "略称",
            "panel_hint": "ヒント",
            "show_map_icon": False,
            "display_thresholds_override": [1.0, 2.0],
            "display_band_labels_override": ["低い", "中くらい", "高い"],
        }
    )

    assert is_cosmetic_only_update(existing, candidate) is True


def test_is_cosmetic_only_update_false_when_shape_changes():
    existing = _definition("axis_a", "material_a", is_published=True)
    candidate = existing.model_copy(update={"default_weight": existing.default_weight + 0.1})

    assert is_cosmetic_only_update(existing, candidate) is False


# --- check_internal_axis_not_published ---
# 他の軸から参照されている軸（内部軸）をis_published=Trueで保存しようとしたら拒否する。
# 通ってしまうと、内部軸が一般向けのルート設定画面へ漏れる。


def _referencing_definition(axis_id: str, referenced_axis_id: str, is_published: bool = True) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material=referenced_axis_id)], breakpoints=[(0.0, 0.0), (10.0, 100.0)]
        ),
        default_weight=0.1,
        label=f"テスト軸[{axis_id}]",
        description="テスト用ダミー軸",
        category="推定",
        is_published=is_published,
    )


def test_check_internal_axis_not_published_allows_draft():
    internal = _definition("internal_axis", "material_a", is_published=False)
    existing = {"public_axis": _referencing_definition("public_axis", "internal_axis")}

    check_internal_axis_not_published(internal, existing)  # 例外が出ないことを確認


def test_check_internal_axis_not_published_allows_unreferenced_publish():
    unreferenced = _definition("standalone_axis", "material_a", is_published=True)
    existing = {"public_axis": _referencing_definition("public_axis", "internal_axis")}

    check_internal_axis_not_published(unreferenced, existing)  # 例外が出ないことを確認


def test_check_internal_axis_not_published_rejects_publishing_referenced_axis():
    internal = _definition("internal_axis", "material_a", is_published=True)
    existing = {"public_axis": _referencing_definition("public_axis", "internal_axis")}

    with pytest.raises(AxisInternalAxisPublishError) as exc_info:
        check_internal_axis_not_published(internal, existing)

    assert exc_info.value.axis_id == "internal_axis"
    assert exc_info.value.referencing_axis_id == "public_axis"


def test_check_internal_axis_not_published_skips_self_comparison():
    # 更新時、existing辞書に自分自身（同じaxis_id）が含まれていても自己参照とは見なさない。
    existing = {"public_axis": _referencing_definition("public_axis", "public_axis", is_published=True)}
    candidate = existing["public_axis"]

    check_internal_axis_not_published(candidate, existing)  # 例外が出ないことを確認


# --- 折れ点を通す前の生値（軸単体で経路を判断するための絶対値） ---


def test_axis_raw_value_array_returns_weighted_sum_before_breakpoints():
    definition = AxisDefinition(
        axis_id="synthetic_raw_sum",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="poi_signal_per_km", weight=1.0),
                MaterialTerm(material="intersection_count_per_km", weight=0.3, required=False),
            ],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
    )
    materials = {
        "poi_signal_per_km": np.array([0.5, 8.0]),
        "intersection_count_per_km": np.array([2.0, 10.0]),
    }

    raw = axis_raw_value_array(definition, materials)

    # 折れ点（4回/kmで100点）で頭打ちになる得点と違い、生値は上限を持たない——
    # 「満点に張り付いた区間どうしの優劣」も生値なら見分けられる。
    assert raw is not None
    np.testing.assert_allclose(raw, [1.1, 11.0])


def test_axis_raw_value_array_applies_preprocess():
    # 勾配は符号付き材料をabsしてから折れ点へ通す。生値も同じ前処理を経た値
    # （そうしないと周回ルートの距離加重平均が自己打ち消しで0になる）。
    definition = AxisDefinition(
        axis_id="synthetic_raw_abs",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (15.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
    )

    raw = axis_raw_value_array(definition, {"gradient_percent": np.array([-6.0, 6.0])})

    assert raw is not None
    np.testing.assert_allclose(raw, [6.0, 6.0])


def test_axis_raw_value_array_is_nan_only_when_every_material_is_missing():
    definition = AxisDefinition(
        axis_id="synthetic_raw_missing",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="poi_signal_per_km", weight=1.0, required=False),
                MaterialTerm(material="intersection_count_per_km", weight=0.3, required=False),
            ],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
    )
    materials = {
        "poi_signal_per_km": np.array([np.nan, np.nan]),
        "intersection_count_per_km": np.array([2.0, np.nan]),
    }

    raw = axis_raw_value_array(definition, materials)

    assert raw is not None
    # 片方だけ欠損: required=Falseの規約どおり欠損を0として足す。両方欠損: 値が無い。
    np.testing.assert_allclose(raw[0], 0.6)
    assert np.isnan(raw[1])


def test_axis_raw_value_array_is_none_for_categorical_shape():
    definition = AxisDefinition(
        axis_id="synthetic_raw_categorical",
        shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
    )

    assert axis_raw_value_array(definition, {"surface_good": np.array([1.0])}) is None


# --- evaluate_axis_scalar が決めていること ---
#
# 分類shapeの文字列キー・未一致・`priority_overrides`の短絡は
# `test_axis_hierarchy.py`が持つ。ここは区分線形の合成と欠損の扱いを見る。


def _linear_axis(
    terms: list[MaterialTerm],
    breakpoints: list[tuple[float, float]],
    preprocess: str = "identity",
) -> AxisDefinition:
    """区分線形の軸を、見たい性質だけ与えて組む。"""
    return AxisDefinition(
        axis_id="synthetic_linear",
        shape=BreakpointLinearShape(terms=terms, preprocess=preprocess, breakpoints=breakpoints),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
    )


def test_value_between_breakpoints_is_interpolated():
    axis = _linear_axis([MaterialTerm(material="num_a")], [(0.0, 0.0), (10.0, 50.0)])

    assert evaluate_axis_scalar(axis, {"num_a": 4.0}) == 20.0


def test_value_outside_breakpoints_clamps_to_the_declared_ends():
    """両端は0・100ではなく、**宣言した端の値**で止まる。"""
    axis = _linear_axis([MaterialTerm(material="num_a")], [(0.0, 10.0), (10.0, 50.0)])

    assert evaluate_axis_scalar(axis, {"num_a": -5.0}) == 10.0
    assert evaluate_axis_scalar(axis, {"num_a": 99.0}) == 50.0


def test_abs_preprocess_makes_the_sign_irrelevant():
    axis = _linear_axis([MaterialTerm(material="num_a")], [(0.0, 0.0), (10.0, 100.0)], preprocess="abs")

    assert evaluate_axis_scalar(axis, {"num_a": -4.0}) == evaluate_axis_scalar(axis, {"num_a": 4.0})


def test_score_is_rounded_to_one_decimal():
    axis = _linear_axis([MaterialTerm(material="num_a")], [(0.0, 0.0), (3.0, 100.0)])

    assert evaluate_axis_scalar(axis, {"num_a": 1.0}) == 33.3


def test_missing_required_material_makes_the_whole_axis_unevaluable():
    """必須の項が1つ欠けるだけで、他の項が揃っていても評価しない。"""
    axis = _linear_axis(
        [
            MaterialTerm(material="num_a", required=True),
            MaterialTerm(material="num_b", required=False),
        ],
        [(0.0, 0.0), (10.0, 100.0)],
    )

    assert evaluate_axis_scalar(axis, {"num_b": 5.0}) is None


def test_missing_optional_material_only_drops_that_term():
    axis = _linear_axis(
        [
            MaterialTerm(material="num_a", weight=1.0, required=False),
            MaterialTerm(material="num_b", weight=1.0, required=False),
        ],
        [(0.0, 0.0), (10.0, 100.0)],
    )

    assert evaluate_axis_scalar(axis, {"num_a": 4.0}) == evaluate_axis_scalar(
        axis, {"num_a": 4.0, "num_b": 0.0}
    )


def test_axis_is_unevaluable_when_no_term_has_a_value():
    """必須でない項だけでも、1つも値が無ければ0点ではなく評価不能。"""
    axis = _linear_axis(
        [MaterialTerm(material="num_a", required=False), MaterialTerm(material="num_b", required=False)],
        [(0.0, 0.0), (10.0, 100.0)],
    )

    assert evaluate_axis_scalar(axis, {}) is None


def test_zero_weight_term_does_not_move_the_total():
    """重み0の項は、値があっても合計を動かさない（登録はされるが寄与しない材料）。"""
    axis = _linear_axis(
        [
            MaterialTerm(material="num_a", weight=1.0),
            MaterialTerm(material="num_b", weight=0.0),
        ],
        [(0.0, 0.0), (10.0, 100.0)],
    )

    assert evaluate_axis_scalar(axis, {"num_a": 4.0, "num_b": 1000.0}) == 40.0


def test_categorical_axis_without_its_material_is_unevaluable():
    axis = AxisDefinition(
        axis_id="synthetic_categorical",
        shape=CategoricalShape(material="bool_a", mapping={True: 0.0, False: 80.0}),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
    )

    assert evaluate_axis_scalar(axis, {}) is None
    assert evaluate_axis_scalar(axis, {"bool_a": False}) == 80.0
