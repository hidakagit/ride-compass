"""`domain/dynamic_way_values.py`——ルートを出す前に全道路へ配る軸について、地図が塗る値。

入口は`map_value_kind`／`map_value`／
`map_value_unit`（塗る値の種類・材料・単位）・`map_value_thresholds`（ルート線の段の境界）・
`map_legend`（凡例が段の境界を書く目盛り）・`transform_dedicated_way_values`（配る材料の生値を塗る値へ）。

材料カタログと軸の集合は本番の正本を読まず、性質だけを持つ架空の材料・軸へ差し替える（`MATERIAL_CATALOG`・
`AXIS_DEFINITIONS`。段の境界は`domain/axis_display.py`を、量の単位は`domain/axis_raw_value.py`を通るので、
そちらの名前空間も差し替える）。

ここで見ないもの:
- 地図の段の境界そのもの（どの軸が地図に塗れるか・境界の導出） → `test_axis_display.py`
- 折れ線の得点・0次条件の評価（`domain/axis_definitions.py: evaluate_axis_values`） → `test_axis_definitions.py`。
  配る材料に置いた条件が当たる道の得点も見ない——条件は真偽・分類の材料にしか置けず（`check_axis_definition`）、
  配る材料はどれも数値なので、本番の専用配信の軸で当たる条件は起こらない
- 材料から配るサービスを選ぶこと・配信のAPI → `test_dedicated_way_values.py`・`test_region_routes.py`
- 要求の条件の組み立て（`assemble_conditions`） → `test_region_routes.py`（配信と区間インスペクタの入口で）
"""

import math

import pytest

from app.domain import axis_display, axis_raw_value, dynamic_way_values
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.domain.dynamic_way_values import (
    MapLegendScale,
    SignedMaterialMapValue,
    map_legend,
    map_value,
    map_value_kind,
    map_value_thresholds,
    map_value_unit,
    transform_dedicated_way_values,
)
from app.domain.material_catalog import CoverageExcluded, MaterialSpec


def _material(material_id, dtype="numeric", *, tile=True, unit="") -> MaterialSpec:
    return MaterialSpec(
        material_id=material_id,
        label=material_id,
        description="架空の材料",
        dtype=dtype,
        unit=unit,
        tile_property=f"{material_id}_tile" if tile else None,
        value_sql=f"w.{material_id}",
        coverage=CoverageExcluded(reason="架空", missing_semantics="definite"),
    )


CATALOG = {
    spec.material_id: spec
    for spec in [
        _material("num_tiled"),
        _material("count_tiled", unit="件"),
        _material("rain_live", tile=False, unit="mm"),
        _material("num_live", tile=False, unit="%"),
        _material("num_other", tile=False),
        _material("kind", "categorical"),
    ]
}


@pytest.fixture
def axes(monkeypatch) -> dict[str, AxisDefinition]:
    """保存済みの軸の集合（空から）。"""
    saved: dict[str, AxisDefinition] = {}
    for module in (dynamic_way_values, axis_display, axis_raw_value):
        monkeypatch.setattr(module, "MATERIAL_CATALOG", CATALOG)
        monkeypatch.setattr(module, "AXIS_DEFINITIONS", saved)
    return saved


pytestmark = pytest.mark.usefixtures("axes")


def _line(*materials, breakpoints=((0.0, 0.0), (10.0, 100.0)), preprocess="identity") -> BreakpointLinearShape:
    return BreakpointLinearShape(
        terms=[MaterialTerm(material=m) for m in materials], breakpoints=list(breakpoints), preprocess=preprocess
    )


def _axis(shape, axis_id="axis_a", **fields) -> AxisDefinition:
    return AxisDefinition(axis_id=axis_id, shape=shape, default_weight=1.0, label="軸A", **fields)


SIGNED = _axis(_line("num_live", breakpoints=((0.0, 0.0), (2.0, 30.0), (6.0, 100.0)), preprocess="abs"))


# --- 塗る値の種類 ---


def test_a_single_material_axis_on_its_absolute_value_paints_the_signed_raw_value():
    """勾配のように向きの符号に意味がある材料は、難易度ではなく符号付きの生値を塗る。"""
    assert map_value_kind(SIGNED) == "signed_material"
    assert map_value(SIGNED) == SignedMaterialMapValue(material="num_live")
    assert map_value_unit(SIGNED) == "%"


DIFFICULTY_AXES = {
    "符号を畳まない": _axis(_line("num_live")),
    "項が2つ": _axis(_line("num_live", "num_other", preprocess="abs")),
    "項が軸を指す": _axis(_line("inner", preprocess="abs")),
    "0次条件を持つ": SIGNED.model_copy(
        update={"priority_overrides": [PriorityCondition(material="num_live", equals="x", value=0.0)]}
    ),
    "分類の軸": _axis(CategoricalShape(material="kind", mapping={"x": 0.0, "y": 100.0})),
}


@pytest.mark.parametrize("definition", DIFFICULTY_AXES.values(), ids=DIFFICULTY_AXES.keys())
def test_other_axes_paint_the_difficulty(axes, definition):
    """軸を指す項の値は参照先の得点で、材料の符号も単位も持たない。0次条件の当たる道では生値が評価と食い違う。"""
    axes["inner"] = _axis(_line("num_tiled"), axis_id="inner")

    assert map_value_kind(definition) == "difficulty"


# --- ルート線の段の境界 ---


def test_signed_material_bands_open_symmetrically_from_the_axis_knots():
    """軸は|値|を評価しているので、段も0を挟んで同じ境界で開く。0の節は境界にしない。"""
    assert map_value_thresholds(SIGNED) == [-6.0, -2.0, 2.0, 6.0]


def test_an_override_on_an_axis_the_tiles_cannot_paint_is_used_as_is():
    """専用の配信で塗る軸の上書きは、地図が塗る値そのものに対する境界。"""
    definition = SIGNED.model_copy(update={"display_thresholds_override": [-3.0, 0.0, 3.0]})

    assert map_value_thresholds(definition) == [-3.0, 0.0, 3.0]


def test_a_difficulty_axis_the_tiles_cannot_paint_is_cut_at_the_default_difficulty_bands():
    assert map_value_thresholds(_axis(_line("num_live", "num_other", preprocess="abs"))) == list(
        dynamic_way_values.DEFAULT_DIFFICULTY_BOUNDARIES
    )


def test_the_default_difficulty_boundaries_are_strictly_ascending():
    """地図の式（MapLibreの`step`）は段の境界が厳密に昇順でないと式ごと失敗し、レイヤーが黙って消える。"""
    boundaries = list(dynamic_way_values.DEFAULT_DIFFICULTY_BOUNDARIES)

    assert boundaries == sorted(set(boundaries))


def test_route_line_bands_of_a_categorical_axis_are_the_map_bands():
    """分類の軸の地図の値は初めから得点なので、写さない。"""
    definition = _axis(CategoricalShape(material="kind", mapping={"x": 0.0, "y": 40.0, "z": 100.0}))

    assert map_value_thresholds(definition) == [20.0, 70.0]


# --- 凡例の目盛り ---

RAIN_LINE = ((0.0, 0.0), (5.0, 30.0), (20.0, 70.0), (50.0, 100.0))


def test_an_axis_scoring_a_quantity_is_cut_at_its_knots_and_written_in_that_quantity():
    """雨のように単位のある量1つから得点を作る軸は、軸が効きの変わり目とした節で段を切り、凡例はその量で書く。"""
    definition = _axis(_line("rain_live", breakpoints=RAIN_LINE), dedicated_way_value_layer=True)

    assert map_value_thresholds(definition) == [30.0, 70.0, 100.0]
    assert map_legend(definition) == MapLegendScale(boundaries=[5.0, 20.0, 50.0], unit="mm")


def test_a_tile_painted_axis_scoring_a_quantity_is_written_at_its_map_bands_in_that_quantity():
    """タイルで塗る軸の地図の段は初めから量の目盛りなので、凡例はそれをそのまま量で書く。地図は材料の重み付き和を、
    ルート線は難易度を塗るので、同じ段になるよう、ルート線の境界は地図の境界を折れ線で写す。"""
    definition = _axis(
        _line("count_tiled", breakpoints=((0.0, 0.0), (4.0, 20.0), (10.0, 80.0))), display_thresholds_override=[2.0, 7.0]
    )

    assert map_value_thresholds(definition) == pytest.approx([10.0, 50.0])
    assert map_legend(definition) == MapLegendScale(boundaries=[2.0, 7.0], unit="件")


SCORE_LEGEND_AXES = {
    "量に単位が無い": _axis(_line("num_live", "num_other")),
    "得点が量について増えない区間がある": _axis(
        _line("rain_live", breakpoints=((0.0, 0.0), (5.0, 50.0), (20.0, 50.0), (50.0, 100.0)))
    ),
    "得点で刻んだ上書き": _axis(_line("rain_live", breakpoints=RAIN_LINE), display_thresholds_override=[40.0]),
    "0次条件を持つ": _axis(
        _line("rain_live", breakpoints=RAIN_LINE),
        priority_overrides=[PriorityCondition(material="rain_live", equals="x", value=0.0)],
    ),
}


@pytest.mark.parametrize("definition", SCORE_LEGEND_AXES.values(), ids=SCORE_LEGEND_AXES.keys())
def test_bands_that_cannot_be_written_as_a_quantity_are_written_as_scores(definition):
    """量で書いた段が得点の段と同じ道を指すと言えない軸は、塗る得点の境界をそのまま得点として書く。"""
    assert map_legend(definition) == MapLegendScale(boundaries=map_value_thresholds(definition), unit=None)


def test_a_signed_material_axis_is_written_in_the_material_unit():
    assert map_legend(SIGNED) == MapLegendScale(boundaries=[-6.0, -2.0, 2.0, 6.0], unit="%")


# --- 生値から塗る値へ ---

VALUES = {"way:1": -4.0, "way:2": 1.0, "edge:3": 12.0}


def test_a_signed_material_axis_paints_the_raw_values_unchanged():
    assert transform_dedicated_way_values(SIGNED, "num_live", VALUES) == VALUES


def test_a_difficulty_axis_paints_each_feature_by_the_axis():
    """折れ線の外は両端の得点へ寄る。"""
    definition = _axis(_line("num_live"))

    assert transform_dedicated_way_values(definition, "num_live", VALUES) == {
        "way:1": 0.0,
        "way:2": 10.0,
        "edge:3": 100.0,
    }


def test_a_feature_the_axis_cannot_evaluate_is_left_unpainted():
    """地図では「データなし」になる。"""
    result = transform_dedicated_way_values(_axis(_line("num_live")), "num_live", {"way:1": math.nan, "way:2": 5.0})

    assert result == {"way:2": 50.0}


def test_a_feature_undetermined_by_the_bearing_stays_undetermined():
    """地図では「向きで決まらない」になり、値の無い道（鍵ごと無い）と見分けられる。"""
    result = transform_dedicated_way_values(_axis(_line("num_live")), "num_live", {"way:1": None, "way:2": 5.0})

    assert result == {"way:1": None, "way:2": 50.0}


def test_an_axis_that_also_needs_a_material_not_served_paints_nothing():
    """配信が値を持つのは1つの材料だけ。必須の別の材料が無ければ、どの道も評価できない。"""
    definition = _axis(_line("num_live", "num_other"))

    assert transform_dedicated_way_values(definition, "num_live", VALUES) == {}


def test_a_condition_on_a_material_not_served_paints_nothing():
    """条件が当たるかを決められない。条件を落として塗ると、条件の当たる道で評価と食い違う。"""
    definition = _axis(
        _line("num_live"), priority_overrides=[PriorityCondition(material="num_other", equals="x", value=0.0)]
    )

    assert transform_dedicated_way_values(definition, "num_live", VALUES) == {}


def test_a_condition_on_the_served_material_does_not_stop_the_painting():
    """条件が配る材料にだけ置かれていれば、当たるかを決められるので塗る（ここで当たらない条件は得点を変えない）。"""
    definition = _axis(
        _line("num_live"), priority_overrides=[PriorityCondition(material="num_live", equals="x", value=0.0)]
    )

    assert transform_dedicated_way_values(definition, "num_live", {"way:2": 1.0}) == {"way:2": 10.0}
