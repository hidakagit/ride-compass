"""`AXIS_DEFINITIONS`から専用way値レイヤーの宣言と地図表示値を導く経路のテスト。"""

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.domain.axis_display import axis_display_for
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
        "surface_q": _axis("surface_q", dedicated_way_value_layer=False),
    }
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(fake_definitions)

        axes = dedicated_way_value_axes()

        assert set(axes) == {"wind", "gradient"}


def test_carries_each_needs_flag_through_without_swapping(monkeypatch):
    # 3つのフラグへ別々の値を置く。取り違えるとどれかが逆になる。
    monkeypatch.setitem(
        AXIS_DEFINITIONS, "flagged",
        _axis("flagged", dedicated_way_value_layer=True, dynamic_way_value_needs_bearing=True),
    )

    flagged = dedicated_way_value_axes()["flagged"]

    assert flagged.needs_time is False
    assert flagged.needs_bearing is True
    assert flagged.needs_speed is False


def test_axis_id_matches_dict_key():
    for key, axis in dedicated_way_value_axes().items():
        assert axis.axis_id == key


def test_map_value_kind_is_signed_material_only_for_single_abs_term_axes():
    assert map_value_kind(AXIS_DEFINITIONS["gradient"]) == "signed_material"
    assert map_value_kind(AXIS_DEFINITIONS["wind"]) == "difficulty"
    assert map_value_kind(AXIS_DEFINITIONS["stop_density"]) == "difficulty"


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
    # 食い違う。写した結果はルート前の段数（しきい値+1）と対応する。
    before = axis_display_for(_ramp_axis(None)).thresholds

    mapped = map_value_thresholds(_ramp_axis(None))

    assert mapped == [30.0, 100.0]
    assert len(mapped) == len(before)


def test_map_value_thresholds_is_none_when_the_axis_has_no_ramp_display():
    # 地図に段そのものが無い軸（自動導出できず上書きも無い）はNoneを返し、
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
    assert axis_display_for(not_derivable).kind == "none"

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
            # wind_drag_ratioはtile_propertyを持たないため地図に出ない。
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


def test_every_axis_with_a_ramp_display_has_the_same_bands_before_and_after_a_route():
    """ルート確定前の全道路の塗りと、確定後のルート線は同じ数の段で塗る。

    段の識別子は前後で同じ保存先へ書かれるため、数が違うと前に隠した段が生成後に別の段へ
    化ける。母集団は宣言から導く——軸idを並べると、公開を増やしたときにここだけが古くなる。
    """
    mismatches = []
    for definition in AXIS_DEFINITIONS.values():
        display = axis_display_for(definition)
        if display.kind != "ramp":
            continue
        bands = display.thresholds
        mapped = map_value_thresholds(definition)
        if mapped is None or len(mapped) != len(bands):
            mismatches.append(f"{definition.axis_id}: 前={bands} 後={mapped}")

    assert mismatches == []
