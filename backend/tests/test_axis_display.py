from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    UNSIGNALED_INTERSECTION_WEIGHT,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
from app.domain.axis_display import (
    ACCIDENT_DISPLAY,
    CAR_STRESS_DISPLAY,
    STOP_DENSITY_DISPLAY,
    axis_display_for,
    derive_ramp_inputs,
)
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialSpec
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


def test_categorical_shape_with_str_multi_value_material_derives_ramp():
    # 改善計画T292でCategoricalShape.mappingがstr多値材料（highway等、3値以上）にも
    # 対応した当初は、export_openapi.pyの自動ramp化ループがcar_stress_highway_base等の
    # 内部軸へderive_ramp_inputsを呼んでKeyError(shape.mapping[True])でクラッシュする
    # 実障害があったため、str多値のmappingは自動導出対象外（None）にしていた。
    # 改善計画T308で、`registry.py: TileInputSpec.categories`（既にN値文字列材料に
    # 対応済み）を使ってstr多値もbool2値と同じ理屈で一般化した。
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

    ramp = derive_ramp_inputs(definition)

    assert ramp is not None
    assert len(ramp.tile_inputs) == 1
    tile_input = ramp.tile_inputs[0]
    assert tile_input.property == "highway"
    assert tile_input.categories == {"residential": 2.0, "primary": 4.0, "trunk": 4.0}
    # 改善計画T297の教訓通り、未登録値は「不明」（灰色）へ倒す（寄与0ではない）。
    assert tile_input.has_unknown_fallback is True
    # 達成しうるスコア{2.0, 4.0}の隣接中間点。
    assert ramp.thresholds == [3.0]


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


def test_multi_term_breakpoint_linear_derives_ramp_with_coarser_thresholds():
    # stop_density: 複数材料の重み付き結合。改善計画T278時点では単一term・weight=1.0限定
    # だったため自動導出対象外だったが、改善計画T308でtotal=Σ(material_value×term.weight)が
    # 評価側とタイル表示側で完全に同一の演算であることを踏まえ、term数・重みによらず
    # shape.breakpointsのx値を閾値として流用できるよう一般化した。
    #
    # ただし、これは`registry_defaults.py`の既存手書きthresholds[1.0, 2.0, 4.0]
    # （統計的経験則による4段階）とは**一致しない**——stop_densityのbreakpointsは
    # [(0.0, 0.0), (4.0, 100.0)]の2点（1本の線形区間）しか無く、この関数が流用できる
    # x値は[4.0]の1つだけ（2段階）に留まる。既存の手書きdisplayの方が段階が細かいため、
    # `axis_display_for()`は既存7軸のうちstop_density/accident/car_stressについては
    # 引き続き手書きoverrideを優先する（本関数はより粗い代替として動作するだけで、
    # 既存の手書きを置き換えるものではないことをこのテストで明示する）。
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["stop_density"])

    assert ramp is not None
    assert ramp.tile_inputs == [
        TileInputSpec(property="stop_per_km", weight=1.0),
        TileInputSpec(property="intersection_per_km", weight=UNSIGNALED_INTERSECTION_WEIGHT),
    ]
    assert ramp.thresholds == [4.0]


def test_tile_independent_material_is_not_auto_derived():
    # gradient: 材料gradient_percentがタイル非依存（GSI APIから都度取得）。
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["gradient"])

    assert ramp is None


def test_axis_referencing_breakpoint_linear_is_not_auto_derived():
    # car_stress（改善計画T292）: BreakpointLinearShapeのtermsが材料ではなく他の軸
    # （car_stress_highway_base等、is_published=Falseの内部軸）を参照する。
    # MATERIAL_CATALOGには存在しないためspecがNoneとなり自動導出対象外になる
    # （tile_inputs/thresholdsはregistry_defaults.pyへ直接手書きしている）。
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["car_stress"])

    assert ramp is None


def test_runtime_scale_material_is_not_auto_derived():
    # accident: 材料accident_count_per_km_yearは年正規化済みだがタイル生値
    # (accident_per_km)は年正規化前で実行時に変動するスケール係数が必要なため
    # 自動導出対象外（改善計画T278の制約2）。
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["accident"])

    assert ramp is None


def test_direction_dependent_material_is_not_auto_derived(monkeypatch):
    # 改善計画T308: 進行方向で値が変わる（有向）材料は、1本の線を単色で塗るramp表示には
    # 単純化できない（時間依存の風・降水ナウキャストと同じく専用表示が要る）。現行
    # MATERIAL_CATALOGに実例が無いため、テスト専用の材料を一時的に登録して検証する。
    monkeypatch.setitem(
        MATERIAL_CATALOG,
        "test_direction_dependent_material",
        MaterialSpec(
            material_id="test_direction_dependent_material",
            label="テスト用有向材料",
            dtype="numeric",
            tile_property="test_direction_dependent_property",
            tile_property_direction_dependent=True,
        ),
    )
    definition = AxisDefinition(
        axis_id="synthetic_direction_dependent",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="test_direction_dependent_material", weight=1.0)],
            breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト軸",
        category="推定",
    )

    ramp = derive_ramp_inputs(definition)

    assert ramp is None


def test_axis_display_for_prefers_hand_written_override():
    # 改善計画T308: stop_density/accident/car_stressはderive_ramp_inputsが自動導出できる
    # ようになった（stop_densityはT308一般化後は非Noneになる）場合でも、統計的経験則の
    # 手書きthresholds（axis_display.py）を優先して返す。
    assert axis_display_for(AXIS_DEFINITIONS["stop_density"]) is STOP_DENSITY_DISPLAY
    assert axis_display_for(AXIS_DEFINITIONS["accident"]) is ACCIDENT_DISPLAY
    assert axis_display_for(AXIS_DEFINITIONS["car_stress"]) is CAR_STRESS_DISPLAY


def test_axis_display_for_falls_back_to_auto_derivation():
    # surface_q・nightは手書きoverrideが無いため、derive_ramp_inputsの結果をそのまま使う。
    display = axis_display_for(AXIS_DEFINITIONS["surface_q"])
    assert display.kind == "ramp"
    assert display.label == AXIS_DEFINITIONS["surface_q"].label
    ramp = derive_ramp_inputs(AXIS_DEFINITIONS["surface_q"])
    assert ramp is not None
    assert display.tile_inputs == ramp.tile_inputs
    assert display.thresholds == ramp.thresholds


def test_axis_display_for_returns_none_kind_when_not_derivable():
    # gradient: 材料gradient_percentがタイル非依存のため自動導出不可、手書きoverrideも無い。
    display = axis_display_for(AXIS_DEFINITIONS["gradient"])
    assert display.kind == "none"
    assert display.label == AXIS_DEFINITIONS["gradient"].label
    assert display.tile_inputs == []
    assert display.thresholds == []


def test_axis_display_for_derives_gui_created_axis_display():
    # 改善計画T308の目的そのもの: 軸スタジオ（GUI）が作る典型的な軸（複数材料の重み付き
    # 結合）は、手書きoverride無しでもramp表示が導出される。
    definition = AxisDefinition(
        axis_id="gui_created_axis",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="lanes_count", weight=1.0),
                MaterialTerm(material="maxspeed_kmh", weight=0.5),
            ],
            breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト用GUI軸",
        category="推定",
        is_published=True,
    )

    display = axis_display_for(definition)

    assert display.kind == "ramp"
    assert display.label == "テスト用GUI軸"
    assert display.tile_inputs == [
        TileInputSpec(property="lanes_count", weight=1.0),
        TileInputSpec(property="maxspeed_kmh", weight=0.5),
    ]
    assert display.thresholds == [10.0]
