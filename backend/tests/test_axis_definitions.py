
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


# 改善計画T292由来の旧`_CAR_STRESS_BICYCLE_INFRA_MAPPING`と同じ5値
# （axis_definitions.py参照、地図表示ramp用に現在も定数として維持している）。
_OLD_BICYCLE_INFRA_MAPPING = {
    "separated": -2.0,
    "lane": -1.0,
    "shared_busway": 0.0,
    "shared_pedestrian": 0.0,
    "roadway": 1.0,
}




def test_bicycle_infra_quality_flag_combinations():
    """旧内部軸（1材料1軸
    原則T268違反のため廃止）が持っていた「正規化フラグ材料の線形結合」を、公開軸
    bicycle_infra_qualityが直接引き継いだ後も、単独成立時の値が正しいスケール
    （0=最も走りやすい・100=最も走りにくい）で計算されること。

    旧内部軸は優先順位保持（track/highway=cyclewayが最優先）を線形結合の飽和
    （breakpointsによる圧縮）で模していたが、bicycle_infra_qualityは飽和を持たない
    単純な重み付き線形結合のため、複数フラグが同時成立するケースでは優先順位を保持
    しない（実データ検証済み、T353: 4フラグ同時成立は86,642件中1件のみで実害僅少）。"""
    axis = AXIS_DEFINITIONS["bicycle_infra_quality"]
    base = {
        "highway_is_cycleway": False,
        "cycleway_has_track": False,
        "cycleway_has_lane": False,
        "cycleway_has_shared": False,
        "shared_pedestrian_path": False,
    }

    def score(**flags: bool) -> float | None:
        return evaluate_axis_scalar(axis, {**base, **flags})

    assert score() == 100.0  # roadway相当（何も該当しない既定状態、最も走りにくい）
    assert score(cycleway_has_shared=True) == 66.7  # shared_busway相当
    assert score(cycleway_has_lane=True) == 33.3  # lane相当
    assert score(cycleway_has_track=True) == 0.0  # separated相当（最も走りやすい）
    assert score(highway_is_cycleway=True) == 0.0  # separated相当（highway=cycleway側）
    # 改善計画T359: 河川敷サイクリングロード等（highway=footway/pathかつbicycle=yes/
    # designated）はtrack/highway=cyclewayと同格の重みで最も走りやすい扱いにする。
    assert score(shared_pedestrian_path=True) == 0.0
    # 優先順位を保持しない: lane+shared同時成立は単純な線形和（-2+-1=-3）になり、
    # laneまたはshared単独時のどちらとも異なる値になる。
    assert score(cycleway_has_lane=True, cycleway_has_shared=True) == 16.6
    # track/highway=cyclewayが1つでも混ざれば飽和（breakpoints両端クランプ）で0.0になる。
    assert score(cycleway_has_track=True, cycleway_has_lane=True, cycleway_has_shared=True) == 0.0
    assert score(highway_is_cycleway=True, cycleway_has_lane=True) == 0.0




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


def test_builtin_seven_axes_pass_exclusivity_check():
    # 改善計画T268完了条件: 既存7軸のシードデータが検査を通過する（現状の共有設計と
    # 矛盾しない）ことの確認。各軸を「自分以外の全軸」に対して検査する。
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


PUBLISHED_AXIS_IDS = frozenset(
    {
        "gradient",
        "wind",
        "surface_q",
        "stop_density",
        "accident",
        "night",
        "bicycle_infra_quality",
        "openness",
    }
)


def test_builtin_seven_axes_are_all_published():
    # 改善計画T271完了条件: 既存7軸（本番稼働中、一般ユーザーへ既に公開済み）は
    # is_published=Trueでなければならない（backfill漏れ・既定値の取り違えを防ぐ）。
    # 改善計画T347でbicycle_infra_qualityが加わり公開軸は8つになった（関数名は歴史的名残）。
    for axis_id in PUBLISHED_AXIS_IDS:
        assert AXIS_DEFINITIONS[axis_id].is_published is True


def test_internal_axes_are_not_published():
    # 上のテストと対になる確認: 公開軸以外はis_published=Falseのまま運用する。
    for axis_id, definition in AXIS_DEFINITIONS.items():
        if axis_id not in PUBLISHED_AXIS_IDS:
            assert definition.is_published is False, axis_id


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
    # 改善計画T501: candidateを渡しても、表示専用フィールド以外（ここではdefault_weight）
    # が変わっていれば従来どおり拒否する。
    published = _definition("published_axis", "material_a", is_published=True)
    candidate = published.model_copy(update={"default_weight": 0.9})

    with pytest.raises(AxisPublishedImmutableError):
        check_publish_immutability(published, "updated", candidate)


def test_check_publish_immutability_allows_published_cosmetic_only_change():
    # 改善計画T501: 表示専用フィールド（icon_id等）だけの差分ならcandidateを渡すことで
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


# --- check_internal_axis_not_published（T311フォローアップ回帰テスト） ---
# 軸スタジオを開くと未公開の推定軸（内部軸）がルート設定画面に漏れ出た実障害
# （migration適用ラグでDB読み込みが失敗し続け、汚染データが隠れていたケース）を受けて
# 追加したガード。内部軸（他の軸から参照されている軸）をis_published=Trueで保存
# しようとした場合に拒否する。


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


# --- 折れ点を通す前の生値（軸単体で経路を判断するための絶対値、docs/records/tasks/T687.md） ---


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
