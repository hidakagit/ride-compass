from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
from app.domain.axis_display import (
    axis_display_for,
    derive_ramp_inputs,
)
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialSpec
from app.domain.registry import AxisDisplaySpec, TileInputSpec

# 改善計画T350: AXIS_DEFINITIONSのPython literal撤去に伴い、本ファイルのテストは
# derive_ramp_inputs/axis_display_for（純粋関数）の正しさをshapeの種類ごとに検証する
# ことが目的であって、実運用の軸の値を検証したいわけではないため、実軸（AXIS_DEFINITIONS
# の各エントリ）を使わずテストファイル内で定義した合成軸データへ書き換えた。参照する
# material id（surface_good・no_lit・has_tunnel・gradient_percent等）はMATERIAL_CATALOG
# 側の実データで、AXIS_DEFINITIONSとは別レジストリのため引き続き実在するものを使う。


def test_categorical_shape_derives_two_band_ramp():
    # surface_qを模した合成軸: 材料surface_good（真偽値、tile_property="surface_good"）、
    # mapping True=0.0/False=80.0
    definition = AxisDefinition(
        axis_id="synthetic_surface_q",
        shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
    )
    ramp = derive_ramp_inputs(definition)

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


def test_boolean_terms_breakpoint_linear_derives_subset_sum_thresholds():
    # 改善計画T396: 旧FlagSumShapeをBreakpointLinearShapeへ統合。nightを模した合成軸:
    # no_lit(材料、tile_property="lit"の否定)50点 + has_tunnel(tile_property="tunnel")
    # 50点、breakpoints=[(0,0),(100,100)]（cap=100相当）。
    definition = AxisDefinition(
        axis_id="synthetic_night",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="no_lit", weight=50.0),
                MaterialTerm(material="has_tunnel", weight=50.0),
            ],
            breakpoints=[(0.0, 0.0), (100.0, 100.0)],
        ),
        default_weight=0.0,
        label="テスト軸",
        category="観測",
    )
    ramp = derive_ramp_inputs(definition)

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
    # 全termがboolean材料の軸はタグ不在に既に軸定義側の安全側デフォルト意味
    # （無灯火・非トンネル）があるため、欠損を「不明」として特別扱いしない
    # （CategoricalShapeとの違いの確認）。
    assert no_lit_input.has_unknown_fallback is False
    assert tunnel_input.has_unknown_fallback is False


def test_inverted_numeric_material_is_not_auto_derived(monkeypatch):
    # レビュー指摘の修正確認: tile_property_invertedはboolean材料の否定（no_lit⟵lit）
    # のためだけに定義された概念で、数値材料の「反転」は未定義（フロントの
    # buildAxisRampValueExpressionも数値分岐ではinvertを読まない）。誤って色分けが
    # 反転したまま気づかれないより、自動導出対象外（None）にする方が安全。改善計画T396で
    # boolean材料は正しくtrue/false分岐で扱えるようになったため（上のテスト参照）、
    # この安全弁はnumeric dtypeの材料でのみ検証する（テスト専用材料を一時登録）。
    monkeypatch.setitem(
        MATERIAL_CATALOG,
        "test_inverted_numeric_material",
        MaterialSpec(
            material_id="test_inverted_numeric_material",
            label="テスト用反転数値材料",
            description="テスト用の材料。",
            dtype="numeric",
            tile_property="test_inverted_numeric_property",
            tile_property_inverted=True,
        ),
    )
    definition = AxisDefinition(
        axis_id="synthetic_inverted_numeric",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="test_inverted_numeric_material", weight=1.0)],
            breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト軸",
        category="推定",
    )

    ramp = derive_ramp_inputs(definition)

    assert ramp is None


def test_single_term_breakpoint_linear_reuses_breakpoints_as_thresholds():
    # 改善計画T396: 全termがboolean材料の軸は部分和ベースの閾値計算（別テスト
    # test_boolean_terms_breakpoint_linear_derives_subset_sum_thresholds参照）へ分岐する
    # ため、この「breakpointsのx値をそのまま流用する」経路の検証には数値材料
    # （lanes_count）を使う。
    definition = AxisDefinition(
        axis_id="synthetic_single_term",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="lanes_count", weight=1.0)],
            breakpoints=[(0.0, 0.0), (10.0, 50.0), (20.0, 100.0)],
        ),
        default_weight=0.1,
        label="テスト軸",
        category="推定",
    )
    ramp = derive_ramp_inputs(definition)

    assert ramp is not None
    assert ramp.tile_inputs == [TileInputSpec(property="lanes_count", weight=1.0)]
    assert ramp.thresholds == [10.0, 20.0]


def test_multi_term_breakpoint_linear_derives_ramp_with_coarser_thresholds():
    # stop_density: 複数材料の重み付き結合。改善計画T278時点では単一term・weight=1.0限定
    # だったため自動導出対象外だったが、改善計画T308でtotal=Σ(material_value×term.weight)が
    # 評価側とタイル表示側で完全に同一の演算であることを踏まえ、term数・重みによらず
    # shape.breakpointsのx値を閾値として流用できるよう一般化した。
    #
    # ただし、これはstop_density実運用の従来手書きthresholds[1.0, 2.0, 4.0]
    # （統計的経験則による4段階）とは**一致しない**——stop_densityのbreakpointsは
    # [(0.0, 0.0), (4.0, 100.0)]の2点（1本の線形区間）しか無く、この関数が流用できる
    # x値は[4.0]の1つだけ（2段階）に留まる。改善計画T404: 以前は既存7軸のうち
    # stop_density/accident/car_stressについてはこの粗さを理由に手書きdisplay_overrideを
    # 使い続けていたが、T404で「tile_inputsの自動導出」と「色分け段階の細かさ」を
    # 分離し、後者だけをdisplay_thresholds_override（軽量な数値配列の上書き）で
    # 差し替える設計へ移行した（下のtest_axis_display_for_combines_auto_derived_
    # tile_inputs_with_thresholds_override参照）。本関数自体（derive_ramp_inputs）は
    # 変わらず粗いthresholdsを返す。
    # stop_densityを模した合成軸: 材料stop_count_per_km(weight=1.0)+
    # intersection_count_per_km(weight=0.3、旧UNSIGNALED_INTERSECTION_WEIGHT定数の値。
    # T350でAXIS_DEFINITIONS撤去に伴い定数自体は撤去したためここへ直接書く)。
    definition = AxisDefinition(
        axis_id="synthetic_stop_density",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="stop_count_per_km"),
                MaterialTerm(material="intersection_count_per_km", weight=0.3, required=False),
            ],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="テスト軸",
        category="観測",
    )
    ramp = derive_ramp_inputs(definition)

    assert ramp is not None
    assert ramp.tile_inputs == [
        TileInputSpec(property="stop_per_km", weight=1.0),
        TileInputSpec(property="intersection_per_km", weight=0.3),
    ]
    assert ramp.thresholds == [4.0]


def test_tile_independent_material_is_not_auto_derived():
    # gradientを模した合成軸: 材料gradient_percentがタイル非依存（GSI APIから都度取得）。
    definition = AxisDefinition(
        axis_id="synthetic_gradient",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (15.0, 100.0)],
        ),
        default_weight=0.15,
        label="テスト軸",
        category="観測",
    )
    ramp = derive_ramp_inputs(definition)

    assert ramp is None


def test_axis_referencing_unknown_axis_is_not_auto_derived():
    # BreakpointLinearShapeのtermsが材料でも既知の軸idでもない未知の参照を持つ場合、
    # 安全側でNoneを返す（改善計画T404: 材料idの辞書には無いが軸idとしても存在しない、
    # という「本当に未知」なケース。実在の軸を参照するケースは下の
    # test_axis_referencing_categorical_axis_is_recursively_resolved等を参照）。
    definition = AxisDefinition(
        axis_id="synthetic_car_stress",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="synthetic_internal_axis_that_does_not_exist", required=True)],
            breakpoints=[(1.0, 0.0), (5.0, 100.0)],
        ),
        default_weight=0.2,
        label="テスト軸",
        category="推定",
    )
    ramp = derive_ramp_inputs(definition)

    assert ramp is None


def test_axis_referencing_categorical_axis_is_recursively_resolved(monkeypatch):
    # 改善計画T404: car_stress_highway_baseを模した内部軸（CategoricalShape、str多値材料）
    # をAXIS_DEFINITIONSへ一時登録し、それを参照する外側の軸が再帰的に解決できることを
    # 検証する。
    internal = AxisDefinition(
        axis_id="synthetic_highway_base",
        shape=CategoricalShape(material="highway", mapping={"residential": 2.0, "primary": 4.0}),
        default_weight=0.0,
        label="内部軸(道路種別)",
        is_published=False,
    )
    monkeypatch.setitem(AXIS_DEFINITIONS, internal.axis_id, internal)

    outer = AxisDefinition(
        axis_id="synthetic_car_stress",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material=internal.axis_id, weight=1.0, required=True)],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="テスト軸",
        category="推定",
    )

    ramp = derive_ramp_inputs(outer)

    assert ramp is not None
    assert len(ramp.tile_inputs) == 1
    tile_input = ramp.tile_inputs[0]
    assert tile_input.property == "highway"
    assert tile_input.categories == {"residential": 2.0, "primary": 4.0}
    # 外側term.weight=1.0のため内部軸のcategoriesスコアはそのまま流用される。
    assert tile_input.has_unknown_fallback is True
    # 車ストレスと同じ「複数の内部軸を参照する多term」構成のため、thresholdsは
    # outer breakpointsのx値をそのまま流用する（1つのみ、色分け粒度の粗さは
    # display_thresholds_overrideで別途上書きする、下のテスト参照）。
    assert ramp.thresholds == [4.0]


def test_axis_referencing_categorical_axis_rescales_by_outer_weight(monkeypatch):
    # 改善計画T404: 外側term.weightが1.0以外の場合、参照先軸のtile_inputのスコアへ
    # 正しく再スケールされることを検証する（_rescale_tile_input）。
    internal = AxisDefinition(
        axis_id="synthetic_motor_vehicle_adjustment",
        shape=CategoricalShape(material="motor_vehicle_no", mapping={True: -1000.0, False: 0.0}),
        default_weight=0.0,
        label="内部軸(自動車通行不可)",
        is_published=False,
    )
    monkeypatch.setitem(AXIS_DEFINITIONS, internal.axis_id, internal)

    outer = AxisDefinition(
        axis_id="synthetic_car_stress2",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material=internal.axis_id, weight=2.0, required=False)],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="テスト軸",
        category="推定",
    )

    ramp = derive_ramp_inputs(outer)

    assert ramp is not None
    tile_input = ramp.tile_inputs[0]
    assert tile_input.property == "motor_vehicle_no"
    assert tile_input.boolean is True
    assert tile_input.true_value == -2000.0  # -1000.0 * outer weight(2.0)
    assert tile_input.false_value == 0.0
    # motor_vehicle_noのbool_defaultは既定"false"のため、has_unknown_fallbackはFalse
    # （レビュー指摘の修正確認: 以前はCategoricalShape分岐が常にTrueを返していた）。
    assert tile_input.has_unknown_fallback is False


def test_axis_referencing_single_term_breakpoint_linear_axis_is_recursively_resolved(monkeypatch):
    # 改善計画T404: car_stress_maxspeed_adjustmentを模した内部軸（単一term・weight=1.0・
    # preprocess="identity"のBreakpointLinearShape）をAXIS_DEFINITIONSへ一時登録し、
    # TileInputSpec.breakpoints（自己変換材料）として展開されることを検証する。
    internal = AxisDefinition(
        axis_id="synthetic_maxspeed_adjustment",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="maxspeed_kmh", weight=1.0, required=True)],
            breakpoints=[(0.0, -1.0), (30.0, -1.0), (60.0, 1.0), (999.0, 1.0)],
        ),
        default_weight=0.0,
        label="内部軸(制限速度補正)",
        is_published=False,
    )
    monkeypatch.setitem(AXIS_DEFINITIONS, internal.axis_id, internal)

    outer = AxisDefinition(
        axis_id="synthetic_car_stress3",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material=internal.axis_id, weight=1.0, required=False)],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="テスト軸",
        category="推定",
    )

    ramp = derive_ramp_inputs(outer)

    assert ramp is not None
    assert ramp.tile_inputs == [
        TileInputSpec(property="maxspeed_kmh", weight=1.0, breakpoints=internal.shape.breakpoints)
    ]


def test_axis_referencing_multi_term_nested_axis_is_not_auto_derived(monkeypatch):
    # 改善計画T404: 参照先の軸が複数termを持つBreakpointLinearShapeの場合、
    # 「重み付けしてから折れ点変換」という順序をTileInputSpec.breakpointsは表現できないため
    # 安全側でNoneを返す（_resolve_referenced_axis_tile_inputのdocstring参照）。
    internal = AxisDefinition(
        axis_id="synthetic_multi_term_internal",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="lanes_count", weight=1.0),
                MaterialTerm(material="maxspeed_kmh", weight=0.5),
            ],
            breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
        default_weight=0.0,
        label="内部軸(複数term)",
        is_published=False,
    )
    monkeypatch.setitem(AXIS_DEFINITIONS, internal.axis_id, internal)

    outer = AxisDefinition(
        axis_id="synthetic_outer_multi_term_ref",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material=internal.axis_id, weight=1.0, required=False)],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="テスト軸",
        category="推定",
    )

    ramp = derive_ramp_inputs(outer)

    assert ramp is None


def test_circular_axis_reference_is_not_auto_derived(monkeypatch):
    # 改善計画T404: 循環参照は軸スタジオ側で拒否済みの前提だが、derive_ramp_inputsが
    # 直接AXIS_DEFINITIONSを読むため、安全側にvisited集合で保護する（無限再帰しない）。
    axis_a = AxisDefinition(
        axis_id="synthetic_cycle_a",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="synthetic_cycle_b", weight=1.0, required=False)],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.0,
        label="循環A",
        is_published=False,
    )
    axis_b = AxisDefinition(
        axis_id="synthetic_cycle_b",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="synthetic_cycle_a", weight=1.0, required=False)],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.0,
        label="循環B",
        is_published=False,
    )
    monkeypatch.setitem(AXIS_DEFINITIONS, axis_a.axis_id, axis_a)
    monkeypatch.setitem(AXIS_DEFINITIONS, axis_b.axis_id, axis_b)

    ramp = derive_ramp_inputs(axis_a)

    assert ramp is None


def test_boolean_material_with_categorical_true_values_derives_categories_tile_input():
    # 改善計画T404: is_designatedのように、dtype="boolean"だがタイル側は真偽値
    # プロパティではなく複数値の文字列(categorical)プロパティ("designation")の
    # tile_property_categorical_true_valuesで表現される材料の自動導出を検証する。
    assert MATERIAL_CATALOG["is_designated"].tile_property == "designation"
    assert MATERIAL_CATALOG["is_designated"].tile_property_categorical_true_values is not None

    definition = AxisDefinition(
        axis_id="synthetic_designation_adjustment",
        shape=CategoricalShape(material="is_designated", mapping={True: 1.0, False: 0.0}),
        default_weight=0.0,
        label="内部軸(指定路線補正)",
        is_published=False,
    )

    ramp = derive_ramp_inputs(definition)

    assert ramp is not None
    assert len(ramp.tile_inputs) == 1
    tile_input = ramp.tile_inputs[0]
    assert tile_input.property == "designation"
    assert tile_input.boolean is False
    assert tile_input.categories == {
        value: 1.0 for value in MATERIAL_CATALOG["is_designated"].tile_property_categorical_true_values
    }
    # is_designatedのbool_defaultは既定"false"（欠損=確定該当なし）のため不明表示にしない。
    assert tile_input.has_unknown_fallback is False


def test_categorical_true_values_material_with_nonzero_false_score_is_not_auto_derived():
    # 改善計画T404: categories未該当は常に寄与0扱いのため、false_score!=0.0を
    # categoriesで正確に表現する手段が無い。安全側でNoneを返すことを検証する。
    definition = AxisDefinition(
        axis_id="synthetic_designation_nonzero_false",
        shape=CategoricalShape(material="is_designated", mapping={True: 1.0, False: -5.0}),
        default_weight=0.0,
        label="内部軸(指定路線補正、非対応ケース)",
        is_published=False,
    )

    ramp = derive_ramp_inputs(definition)

    assert ramp is None


def test_car_stress_like_multi_axis_reference_derives_full_ramp(monkeypatch):
    # 改善計画T404: 実際のcar_stress軸（5つの内部軸参照: highway_base/maxspeed_adjustment/
    # lanes_adjustment/designation_adjustment/motor_vehicle_no_adjustment）を模した
    # 合成データで、dev DBのdisplay_override（本タスクで廃止・display_thresholds_override
    # へ移行済み、docs/tasks/T404.md参照）が手作業で構築していたtile_inputs構成と
    # 数学的に同一の結果が自動導出できることを検証する。
    highway_base = AxisDefinition(
        axis_id="t_car_stress_highway_base",
        shape=CategoricalShape(material="highway", mapping={"residential": 2.0, "primary": 4.0, "cycleway": 1.0}),
        default_weight=0.0,
        label="道路基準",
        is_published=False,
    )
    maxspeed_adjustment = AxisDefinition(
        axis_id="t_car_stress_maxspeed_adjustment",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="maxspeed_kmh", weight=1.0, required=True)],
            breakpoints=[(0.0, -1.0), (30.0, -1.0), (60.0, 1.0), (999.0, 1.0)],
        ),
        default_weight=0.0,
        label="制限速度補正",
        is_published=False,
    )
    lanes_adjustment = AxisDefinition(
        axis_id="t_car_stress_lanes_adjustment",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="lanes_count", weight=1.0, required=True)],
            breakpoints=[(0.0, -1.0), (1.0, -1.0), (4.0, 1.0), (99.0, 1.0)],
        ),
        default_weight=0.0,
        label="車線数補正",
        is_published=False,
    )
    designation_adjustment = AxisDefinition(
        axis_id="t_car_stress_designation_adjustment",
        shape=CategoricalShape(material="is_designated", mapping={True: 1.0, False: 0.0}),
        default_weight=0.0,
        label="指定路線補正",
        is_published=False,
    )
    motor_vehicle_no_adjustment = AxisDefinition(
        axis_id="t_car_stress_motor_vehicle_no_adjustment",
        shape=CategoricalShape(material="motor_vehicle_no", mapping={True: -1000.0, False: 0.0}),
        default_weight=0.0,
        label="自動車通行不可補正",
        is_published=False,
    )
    for internal in (
        highway_base,
        maxspeed_adjustment,
        lanes_adjustment,
        designation_adjustment,
        motor_vehicle_no_adjustment,
    ):
        monkeypatch.setitem(AXIS_DEFINITIONS, internal.axis_id, internal)

    car_stress = AxisDefinition(
        axis_id="t_car_stress",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material=highway_base.axis_id, weight=1.0, required=True),
                MaterialTerm(material=maxspeed_adjustment.axis_id, weight=1.0, required=False),
                MaterialTerm(material=lanes_adjustment.axis_id, weight=1.0, required=False),
                MaterialTerm(material=designation_adjustment.axis_id, weight=1.0, required=False),
                MaterialTerm(material=motor_vehicle_no_adjustment.axis_id, weight=1.0, required=False),
            ],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="車の圧迫感",
        category="推定",
    )

    ramp = derive_ramp_inputs(car_stress)

    assert ramp is not None
    assert len(ramp.tile_inputs) == 5
    by_property = {t.property: t for t in ramp.tile_inputs}
    assert by_property["highway"].categories == {"residential": 2.0, "primary": 4.0, "cycleway": 1.0}
    assert by_property["maxspeed_kmh"].breakpoints == maxspeed_adjustment.shape.breakpoints
    assert by_property["lanes_count"].breakpoints == lanes_adjustment.shape.breakpoints
    assert by_property["designation"].categories == {
        value: 1.0 for value in MATERIAL_CATALOG["is_designated"].tile_property_categorical_true_values
    }
    assert by_property["designation"].has_unknown_fallback is False
    assert by_property["motor_vehicle_no"].boolean is True
    assert by_property["motor_vehicle_no"].true_value == -1000.0
    assert by_property["motor_vehicle_no"].has_unknown_fallback is False
    # 複数の軸参照termを含むため、thresholdsはouter breakpointsのx値をそのまま流用する
    # （粗い1段階。色分け粒度の細かさはdisplay_thresholds_overrideで別途上書きする、
    # 下のaxis_display_forテスト参照）。
    assert ramp.thresholds == [4.0]


def test_runtime_scale_material_is_auto_derived_with_needs_runtime_scale_flag():
    # 改善計画T404: accidentを模した合成軸。材料accident_count_per_km_yearのタイル生値
    # (accident_per_km)は年正規化前で実行時に変動するスケール係数が必要だが、T404で
    # 自動導出の対象に含めるよう緩和した（TileInputSpec.needs_runtime_scaleで印を付け、
    # 実際のスケール定数はGET /api/axis-catalogがフロントへ渡す）。
    definition = AxisDefinition(
        axis_id="synthetic_accident",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="accident_count_per_km_year")],
            breakpoints=[(0.0, 0.0), (0.5, 100.0)],
        ),
        default_weight=0.08,
        label="テスト軸",
        category="推定",
    )
    ramp = derive_ramp_inputs(definition)

    assert ramp is not None
    assert len(ramp.tile_inputs) == 1
    tile_input = ramp.tile_inputs[0]
    assert tile_input.property == "accident_per_km"
    assert tile_input.weight == 1.0
    assert tile_input.needs_runtime_scale is True
    # thresholdsはouter breakpointsのx値（材料スケール、年正規化後）をそのまま流用する。
    assert ramp.thresholds == [0.5]


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
            description="テスト用の材料。",
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


def test_axis_display_for_prefers_auto_derivation_over_display_override():
    # 改善計画T404: 優先順位を書き換えた（axis_display_for()のdocstring参照）。
    # derive_ramp_inputsが自動導出できる形状であれば、軸自身がdisplay_override
    # （改善計画T310で軸id→値のハードコード辞書から移設、T404で廃止方針）を持っていても
    # 自動導出の結果を優先する（旧T308時点の優先順位[display_override最優先]から反転した）。
    override = AxisDisplaySpec(kind="ramp", label="手書き上書き", category="trafficSafety")
    definition = AxisDefinition(
        axis_id="synthetic_with_override",
        shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
        display_override=override,
    )

    display = axis_display_for(definition)

    assert display is not override
    assert display.kind == "ramp"
    assert display.label == definition.label  # display_overrideのlabel("手書き上書き")ではない


def test_axis_display_for_uses_display_override_only_as_fallback():
    # 改善計画T404: derive_ramp_inputs自体が失敗する軸（タイル非依存材料等）向けの
    # 後方互換セーフティネットとしてのみdisplay_overrideを使う。
    override = AxisDisplaySpec(kind="ramp", label="手書き上書き", category="trafficSafety")
    definition = AxisDefinition(
        axis_id="synthetic_gradient_with_override",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (15.0, 100.0)],
        ),
        default_weight=0.15,
        label="テスト軸",
        category="観測",
        display_override=override,
    )

    assert axis_display_for(definition) is override


def test_axis_display_for_falls_back_to_auto_derivation():
    # 手書きoverrideが無い軸は、derive_ramp_inputsの結果をそのまま使う。
    definition = AxisDefinition(
        axis_id="synthetic_surface_q",
        shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
        default_weight=0.1,
        label="テスト軸",
        category="観測",
    )
    display = axis_display_for(definition)
    assert display.kind == "ramp"
    assert display.label == definition.label
    ramp = derive_ramp_inputs(definition)
    assert ramp is not None
    assert display.tile_inputs == ramp.tile_inputs
    assert display.thresholds == ramp.thresholds


def test_axis_display_for_returns_none_kind_when_not_derivable():
    # 材料がタイル非依存のため自動導出不可、手書きoverrideも無い軸はkind="none"になる。
    definition = AxisDefinition(
        axis_id="synthetic_gradient",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (15.0, 100.0)],
        ),
        default_weight=0.15,
        label="テスト軸",
        category="観測",
    )
    display = axis_display_for(definition)
    assert display.kind == "none"
    assert display.label == definition.label
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


def test_axis_display_for_combines_auto_derived_tile_inputs_with_thresholds_override():
    # 改善計画T404: display_thresholds_override（軽量な色分けしきい値だけの上書き）は
    # derive_ramp_inputsが自動導出したtile_inputsと組み合わせて使う（tile_inputs自体は
    # 上書きしない）。stop_density実運用の移行内容（thresholds[1,2,4]、docs/tasks/
    # T404.md参照）を模した検証。
    definition = AxisDefinition(
        axis_id="synthetic_stop_density_with_thresholds_override",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="stop_count_per_km"),
                MaterialTerm(material="intersection_count_per_km", weight=0.3, required=False),
            ],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="テスト軸",
        category="観測",
        display_thresholds_override=[1.0, 2.0, 4.0],
    )

    display = axis_display_for(definition)

    assert display.kind == "ramp"
    assert display.tile_inputs == [
        TileInputSpec(property="stop_per_km", weight=1.0),
        TileInputSpec(property="intersection_per_km", weight=0.3),
    ]
    # 自動導出のみだと[4.0]（1段階）だが、display_thresholds_overrideで4段階へ差し替わる。
    assert display.thresholds == [1.0, 2.0, 4.0]


def test_axis_display_for_ignores_thresholds_override_when_auto_derivation_fails():
    # 改善計画T404: derive_ramp_inputs自体が失敗する軸（kind="none"）には
    # display_thresholds_overrideは効果が無い（tile_inputs自体を持たないため
    # 組み合わせようがない、AxisDefinition.display_thresholds_overrideのdocstring参照）。
    definition = AxisDefinition(
        axis_id="synthetic_gradient_with_thresholds_override",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (15.0, 100.0)],
        ),
        default_weight=0.15,
        label="テスト軸",
        category="観測",
        display_thresholds_override=[3.0, 6.0, 9.0],
    )

    display = axis_display_for(definition)

    assert display.kind == "none"
