from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
from app.domain.axis_display import derive_ramp_inputs
from app.domain.registry import TileInputSpec


def test_categorical_shape_derives_two_band_ramp():
    # surface_q: 材料surface_good（真偽値、tile_property="surface_good"）、mapping True=0.0/False=80.0
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["surface_q"])

    assert ramp is not None
    assert len(ramp.tile_inputs) == 1
    tile_input = ramp.tile_inputs[0]
    assert tile_input.property == "surface_good"
    assert tile_input.boolean is True
    assert tile_input.invert is False
    assert tile_input.true_value == 0.0
    assert tile_input.false_value == 80.0
    assert ramp.thresholds == [40.0]
    # レビュー指摘の修正確認: CategoricalShapeはタイル欠損が「true/falseどちらでもない
    # 不明」を表すため、has_unknown_fallback=Trueを立てる（フロントはtrue_value/
    # false_valueどちらにも倒さず灰色「不明」表示にする）。
    assert tile_input.has_unknown_fallback is True


def test_categorical_shape_with_str_multi_value_material_is_not_auto_derived():
    # 改善計画T292回帰テスト: CategoricalShape.mappingがstr多値材料（highway等、3値以上）
    # にも対応した後、export_openapi.pyの自動ramp化ループがcar_stress_highway_base等の
    # 内部軸へderive_ramp_inputsを呼んでKeyError(shape.mapping[True])でクラッシュする
    # 実障害が発覚した。str多値のmappingは2色rampで表現できないためNone（ramp化不可）を
    # 返すべきで、例外は送出しない。
    definition = AxisDefinition(
        axis_id="highway_like_axis",
        shape=CategoricalShape(
            material="highway",
            mapping={"residential": 2.0, "primary": 4.0, "trunk": 4.0},
        ),
        default_weight=0.0,
        label="テスト軸",
        is_published=False,
    )

    assert derive_ramp_inputs(definition) is None


def test_flag_sum_shape_derives_subset_sum_thresholds():
    # night: no_lit(材料、tile_property="lit"の否定)50点 + has_tunnel(tile_property="tunnel")50点、cap100
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["night"])

    assert ramp is not None
    assert len(ramp.tile_inputs) == 2
    no_lit_input = next(t for t in ramp.tile_inputs if t.property == "lit")
    assert no_lit_input.invert is True
    assert no_lit_input.true_value == 50.0
    tunnel_input = next(t for t in ramp.tile_inputs if t.property == "tunnel")
    assert tunnel_input.invert is False
    assert tunnel_input.true_value == 50.0
    # 達成しうる合計{0,50,100}の隣接中間点
    assert ramp.thresholds == [25.0, 75.0]
    # FlagSumShapeはタグ不在に既に軸定義側の安全側デフォルト意味（無灯火・非トンネル）が
    # あるため、欠損を「不明」として特別扱いしない（CategoricalShapeとの違いの確認）。
    assert no_lit_input.has_unknown_fallback is False
    assert tunnel_input.has_unknown_fallback is False


def test_breakpoint_linear_shape_with_inverted_material_is_not_auto_derived():
    # レビュー指摘の修正確認: tile_property_invertedはboolean材料の否定（no_lit⟵lit）
    # のためだけに定義された概念で、数値材料の「反転」は未定義（フロントの
    # buildAxisRampValueExpressionも数値分岐ではinvertを読まない）。誤って色分けが
    # 反転したまま気づかれないより、自動導出対象外（None）にする方が安全。
    definition = AxisDefinition(
        axis_id="synthetic_inverted_numeric",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="no_lit", weight=1.0)],
            breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト軸",
        category="推定",
    )
    # no_litは実際はboolean材料だが、ここではtile_property_inverted=Trueを持つ材料を
    # BreakpointLinearShape（数値材料前提）に使った場合の挙動だけを検証する目的で使う。

    ramp = derive_ramp_inputs(definition)

    assert ramp is None


def test_single_term_breakpoint_linear_reuses_breakpoints_as_thresholds():
    definition = AxisDefinition(
        axis_id="synthetic_single_term",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="surface_good", weight=1.0)],
            breakpoints=[(0.0, 0.0), (10.0, 50.0), (20.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト軸",
        category="推定",
    )
    # surface_goodは実際は真偽値材料だが、ここでは単一材料weight=1.0のBreakpointLinear
    # 経路（数値材料ケース）のみを検証する目的で使う。
    ramp = derive_ramp_inputs(definition)

    assert ramp is not None
    assert ramp.tile_inputs == [TileInputSpec(property="surface_good", weight=1.0)]
    assert ramp.thresholds == [10.0, 20.0]


def test_multi_term_breakpoint_linear_is_not_auto_derived():
    # stop_density: 複数材料の重み付き結合。既存の統計的経験則thresholds[1,2,4]を
    # 単純な折れ点流用では再現できないため自動導出対象外（改善計画T278の制約3）。
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["stop_density"])

    assert ramp is None


def test_tile_independent_material_is_not_auto_derived():
    # gradient: 材料gradient_percentがタイル非依存（GSI APIから都度取得）。
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["gradient"])

    assert ramp is None


def test_recipe_composed_material_is_not_auto_derived():
    # car_stress: 材料car_stress_levelがレシピ合成値でタイル非依存。
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["car_stress"])

    assert ramp is None


def test_runtime_scale_material_is_not_auto_derived():
    # accident: 材料accident_count_per_km_yearは年正規化済みだがタイル生値
    # (accident_per_km)は年正規化前で実行時に変動するスケール係数が必要なため
    # 自動導出対象外（改善計画T278の制約2）。
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["accident"])

    assert ramp is None
