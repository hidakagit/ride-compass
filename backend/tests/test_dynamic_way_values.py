"""domain/dynamic_way_values.py: dedicated_way_value_axes()宣言のテスト
（改善計画T423、T458でAXIS_DEFINITIONS由来の動的導出へ変更）。"""

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.domain.axis_display import derive_ramp_inputs, ramp_band_thresholds
from app.domain.dynamic_way_values import (
    dedicated_way_value_axes,
    map_value_kind,
    map_value_thresholds,
    map_value_unit,
    transform_dedicated_way_values,
)
from tests.realistic_axis_fixtures import axis_definitions_snapshot


def _axis(
    axis_id: str,
    dedicated_way_value_layer: bool,
    dynamic_way_value_needs_time: bool = False,
    dynamic_way_value_needs_bearing: bool = False,
) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="gradient_percent")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label=f"テスト軸[{axis_id}]",
        dedicated_way_value_layer=dedicated_way_value_layer,
        dynamic_way_value_needs_time=dynamic_way_value_needs_time,
        dynamic_way_value_needs_bearing=dynamic_way_value_needs_bearing,
    )


def test_derives_only_dedicated_way_value_layer_axes():
    fake_definitions = {
        "wind": _axis("wind", dedicated_way_value_layer=True, dynamic_way_value_needs_time=True, dynamic_way_value_needs_bearing=True),
        "gradient": _axis("gradient", dedicated_way_value_layer=True, dynamic_way_value_needs_bearing=True),
        "car_stress": _axis("car_stress", dedicated_way_value_layer=False),
    }
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(fake_definitions)

        axes = dedicated_way_value_axes()

        assert set(axes) == {"wind", "gradient"}


def test_wind_needs_time_and_bearing(monkeypatch):
    monkeypatch.setitem(
        AXIS_DEFINITIONS, "wind",
        _axis("wind", dedicated_way_value_layer=True, dynamic_way_value_needs_time=True, dynamic_way_value_needs_bearing=True),
    )

    wind = dedicated_way_value_axes()["wind"]

    assert wind.needs_time is True
    assert wind.needs_bearing is True


def test_gradient_needs_bearing_only(monkeypatch):
    # docs/tasks/T423.md確定済みの設計判断: 勾配は時刻非依存・向きのみ依存。
    monkeypatch.setitem(
        AXIS_DEFINITIONS, "gradient",
        _axis("gradient", dedicated_way_value_layer=True, dynamic_way_value_needs_bearing=True),
    )

    gradient = dedicated_way_value_axes()["gradient"]

    assert gradient.needs_time is False
    assert gradient.needs_bearing is True


def test_axis_id_matches_dict_key():
    for key, axis in dedicated_way_value_axes().items():
        assert axis.axis_id == key


def test_map_value_kind_is_signed_material_only_for_single_abs_term_axes():
    assert map_value_kind(AXIS_DEFINITIONS["gradient"]) == "signed_material"
    assert map_value_kind(AXIS_DEFINITIONS["wind"]) == "difficulty"
    assert map_value_kind(AXIS_DEFINITIONS["car_stress"]) == "difficulty"


def test_map_value_unit_comes_from_material_catalog_for_signed_material_only():
    assert map_value_unit(AXIS_DEFINITIONS["gradient"]) == "%"
    assert map_value_unit(AXIS_DEFINITIONS["wind"]) == ""


def test_transform_evaluates_difficulty_with_axis_breakpoints_and_clamps():
    wind = AXIS_DEFINITIONS["wind"]  # breakpoints [(-1.2,0),(0,15),(5,100)]
    result = transform_dedicated_way_values(wind, "wind_drag_ratio", {1: 0.0, 2: 4.0, 3: 8.0, 4: -3.0, 5: 12.0})
    assert result == {1: 15.0, 2: 83.0, 3: 100.0, 4: 0.0, 5: 100.0}


def test_transform_passes_signed_material_through_unchanged():
    gradient = AXIS_DEFINITIONS["gradient"]
    values = {10: -4.2, 11: 3.1}
    assert transform_dedicated_way_values(gradient, "gradient_percent", values) == values


def _ramp_axis(thresholds: list[float] | None) -> AxisDefinition:
    """ramp表示を自動導出できる軸（`trees_percent`はtile_propertyを持つ材料）。

    breakpointsは「材料の重み付き和 → 難易度」の写像で、-100〜-20の範囲を0〜100へ写す。
    """
    return AxisDefinition(
        axis_id="ramp_axis",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="trees_percent", weight=-1.0)],
            breakpoints=[(-100.0, 0.0), (-80.0, 30.0), (-20.0, 100.0)],
        ),
        default_weight=0.1,
        label="ramp表示の軸",
        display_thresholds_override=thresholds,
    )


def test_map_value_thresholds_maps_ramp_material_scale_onto_difficulty():
    # 材料スケール（重み付き和）で書かれた境界は、軸の折れ線で0〜100へ写してから返す。
    # 写さないと、材料の単位で書かれた境界が難易度と比べられてルート線が1色へ落ちる。
    assert map_value_thresholds(_ramp_axis([-85.0, -70.0, -50.0, -30.0])) == [22.5, 41.7, 65.0, 88.3]


def test_map_value_thresholds_collapses_boundaries_that_saturate_to_the_same_score():
    # 折れ線が飽和した先（-20より大きい側は常に100）へ置かれた境界は同じスコアへ写る。
    # 畳まないと同値の境界が並び、段階の境界として使えない。
    assert map_value_thresholds(_ramp_axis([-50.0, -20.0, -10.0, 0.0])) == [65.0, 100.0]


def test_map_value_thresholds_maps_the_auto_derived_thresholds_when_there_is_no_override():
    # 上書きが無い軸も、ルート確定前の全道路は自動導出のしきい値で塗る。同じ段を難易度側で
    # 言い直さずNoneで済ませると、その軸だけがルート後に既定値へ転落し、段の数も意味も
    # 食い違う（T939）。写した結果はルート前の段数（しきい値+1）と対応する。
    auto = derive_ramp_inputs(_ramp_axis(None))
    assert auto is not None

    mapped = map_value_thresholds(_ramp_axis(None))

    assert mapped == [30.0, 100.0]
    assert len(mapped) == len(auto.thresholds)


def test_map_value_thresholds_is_none_when_the_axis_has_no_ramp_display():
    # 地図に段そのものが無い軸（自動導出できず上書きも無い）は従来どおりNoneで、
    # 読む側が map_value_kind ごとの既定値を使う。
    not_derivable = AxisDefinition(
        axis_id="not_derivable",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (15.0, 100.0)],
        ),
        default_weight=0.15,
        label="ramp表示を持たない軸",
    )
    assert derive_ramp_inputs(not_derivable) is None

    assert map_value_thresholds(not_derivable) is None


def test_map_value_thresholds_keeps_material_scale_for_signed_material_axes():
    # 符号付き材料の軸は地図も材料生値を塗るため、境界は材料スケールのまま使う。
    signed = AxisDefinition(
        axis_id="signed",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (15.0, 100.0)],
        ),
        default_weight=0.1,
        label="符号付き材料の軸",
        display_thresholds_override=[-2.0, 2.0, 6.0, 10.0],
    )
    assert map_value_kind(signed) == "signed_material"
    assert map_value_thresholds(signed) == [-2.0, 2.0, 6.0, 10.0]


def test_map_value_thresholds_keeps_difficulty_scale_for_axes_without_ramp_display():
    # ramp表示を持たない軸（自動導出が失敗する軸）の上書きは、地図が塗る値そのものに
    # 対する境界として書かれている。写すと二重に変換される。
    no_ramp = AxisDefinition(
        axis_id="no_ramp",
        shape=BreakpointLinearShape(
            # wind_drag_ratioはtile_propertyを持たないため derive_ramp_inputs が None を返す。
            terms=[MaterialTerm(material="wind_drag_ratio")],
            breakpoints=[(-1.2, 0.0), (0.0, 15.0), (5.0, 100.0)],
        ),
        default_weight=0.1,
        label="ramp表示を持たない軸",
        display_thresholds_override=[20.0, 40.0, 60.0, 80.0],
    )
    assert map_value_thresholds(no_ramp) == [20.0, 40.0, 60.0, 80.0]


def test_transform_drops_ways_the_axis_cannot_evaluate_from_one_material():
    two_materials = AxisDefinition(
        axis_id="two_materials",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="wind_drag_ratio"), MaterialTerm(material="lanes_count")],
            breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
        default_weight=0.1,
        label="2材料",
        dedicated_way_value_layer=True,
    )
    assert transform_dedicated_way_values(two_materials, "wind_drag_ratio", {1: 3.0}) == {}


def _saturating_axis() -> AxisDefinition:
    """折れ線に平らな区間がある軸（5〜10の範囲はどこでも難易度50）。"""
    return AxisDefinition(
        axis_id="saturating_axis",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="trees_percent", weight=1.0)],
            breakpoints=[(0.0, 0.0), (5.0, 50.0), (10.0, 50.0), (15.0, 100.0)],
        ),
        default_weight=0.1,
        label="飽和する軸",
    )


def test_ramp_display_drops_thresholds_that_map_to_the_same_score():
    # 5と10の間は難易度が動かない。ここへ境界を引くと、色は変わるのに評価は同じ、という
    # 見分けを地図が見せることになる——しかもルート線は難易度で塗るためその段を作れず、
    # 前後で段の数が食い違う（T939）。
    bands = ramp_band_thresholds(_saturating_axis())

    assert bands == [5.0, 15.0]


def test_every_axis_with_a_ramp_display_has_the_same_bands_before_and_after_a_route():
    """ルート確定前の全道路の塗りと、確定後のルート線は同じ数の段で塗る。

    段の識別子は前後で同じ保存先へ書かれるため、数が違うと前に隠した段が生成後に別の段へ
    化ける。母集団は宣言から導く——軸idを並べると、公開を増やしたときにここだけが古くなる。
    """
    mismatches = []
    for definition in AXIS_DEFINITIONS.values():
        bands = ramp_band_thresholds(definition)
        if bands is None:
            continue
        mapped = map_value_thresholds(definition)
        if mapped is None or len(mapped) != len(bands):
            mismatches.append(f"{definition.axis_id}: 前={bands} 後={mapped}")

    assert mismatches == []
