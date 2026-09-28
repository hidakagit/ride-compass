"""`domain/dynamic_way_values.py`——ルートを出す前に全道路へ配る軸の宣言と、地図がその軸について塗る値。

入口は`dedicated_way_value_axes`（配る軸と、要る問い合わせの項目）・`map_value_kind`／`map_value`／
`map_value_unit`（塗る値の種類・材料・単位）・`map_value_thresholds`（ルート線の段の境界）・
`transform_dedicated_way_values`（配る材料の生値を塗る値へ）。

材料カタログと軸の集合は本番の正本を読まず、性質だけを持つ架空の材料・軸へ差し替える（`MATERIAL_CATALOG`・
`AXIS_DEFINITIONS`。段の境界は`domain/axis_display.py`を通るので、そちらの名前空間も差し替える）。

ここで見ないもの:
- 地図の段の境界そのもの（どの軸が地図に塗れるか・境界の導出） → `test_axis_display.py`
- 折れ線の得点・0次条件の評価（`domain/axis_definitions.py: evaluate_axis_values`） → `test_axis_definitions.py`
- 材料から配るサービスを選ぶこと・配信のAPI → `test_dedicated_way_value_services.py`・`test_region_routes.py`
"""

import math

import pytest

from app.domain import axis_display, dynamic_way_values
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.domain.dynamic_way_values import (
    DedicatedWayValueAxis,
    DifficultyMapValue,
    SignedMaterialMapValue,
    dedicated_way_value_axes,
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
        coverage=CoverageExcluded(reason="架空", missing_semantics="definite"),
    )


CATALOG = {
    spec.material_id: spec
    for spec in [
        _material("num_tiled"),
        _material("num_live", tile=False, unit="%"),
        _material("num_other", tile=False),
        _material("kind", "categorical"),
    ]
}


@pytest.fixture
def axes(monkeypatch) -> dict[str, AxisDefinition]:
    """保存済みの軸の集合（空から）。"""
    saved: dict[str, AxisDefinition] = {}
    for module in (dynamic_way_values, axis_display):
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


# --- 配る軸 ---


def test_only_axes_with_a_dedicated_layer_are_served_with_what_they_ask_for(axes):
    axes["plain"] = _axis(_line("num_tiled"), axis_id="plain")
    axes["wind"] = _axis(
        _line("num_live"),
        axis_id="wind",
        dedicated_way_value_layer=True,
        dynamic_way_value_needs_time=True,
        dynamic_way_value_needs_bearing=True,
        dynamic_way_value_needs_speed=True,
    )
    axes["rain"] = _axis(_line("num_other"), axis_id="rain", dedicated_way_value_layer=True)

    assert dedicated_way_value_axes() == {
        "wind": DedicatedWayValueAxis(
            axis_id="wind", label="軸A", needs_time=True, needs_bearing=True, needs_speed=True
        ),
        "rain": DedicatedWayValueAxis(
            axis_id="rain", label="軸A", needs_time=False, needs_bearing=False, needs_speed=False
        ),
    }


def test_served_axes_follow_the_saved_axes_after_an_update(axes):
    """軸スタジオで保存すると軸の集合はその場で書き換わる。次の問い合わせから配る軸に入る。"""
    assert dedicated_way_value_axes() == {}

    axes["rain"] = _axis(_line("num_other"), axis_id="rain", dedicated_way_value_layer=True)

    assert list(dedicated_way_value_axes()) == ["rain"]


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
    assert map_value(definition) == DifficultyMapValue()
    assert map_value_unit(definition) == ""


# --- ルート線の段の境界 ---


def test_signed_material_bands_open_symmetrically_from_the_axis_knots():
    """軸は|値|を評価しているので、段も0を挟んで同じ境界で開く。0の節は境界にしない。"""
    assert map_value_thresholds(SIGNED) == [-6.0, -2.0, 2.0, 6.0]


def test_an_override_on_an_axis_the_tiles_cannot_paint_is_used_as_is():
    """専用の配信で塗る軸の上書きは、地図が塗る値そのものに対する境界。"""
    definition = SIGNED.model_copy(update={"display_thresholds_override": [-3.0, 0.0, 3.0]})

    assert map_value_thresholds(definition) == [-3.0, 0.0, 3.0]


def test_a_difficulty_axis_the_tiles_cannot_paint_is_cut_at_the_default_difficulty_bands():
    """既定をここで解くので、読む側は既定を持たない。"""
    assert map_value_thresholds(_axis(_line("num_live", "num_other", preprocess="abs"))) == list(
        dynamic_way_values.DEFAULT_DIFFICULTY_BOUNDARIES
    )


@pytest.mark.parametrize(
    ("override", "expected"),
    [(None, [20.0, 80.0]), ([2.0, 7.0], [10.0, 50.0])],
    ids=["導出した境界", "上書きした境界"],
)
def test_route_line_bands_are_the_map_bands_written_on_the_difficulty_scale(override, expected):
    """地図は材料の重み付き和を、ルート線は難易度を塗る。同じ段になるよう、地図の境界を折れ線で写す。"""
    definition = _axis(
        _line("num_tiled", breakpoints=((0.0, 0.0), (4.0, 20.0), (10.0, 80.0))), display_thresholds_override=override
    )

    assert map_value_thresholds(definition) == pytest.approx(expected)


def test_route_line_bands_of_a_categorical_axis_are_the_map_bands():
    """分類の軸の地図の値は初めから得点なので、写さない。"""
    definition = _axis(CategoricalShape(material="kind", mapping={"x": 0.0, "y": 40.0, "z": 100.0}))

    assert map_value_thresholds(definition) == [20.0, 70.0]


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


def test_a_condition_on_the_served_material_is_evaluated():
    definition = _axis(
        _line("num_live"), priority_overrides=[PriorityCondition(material="num_live", equals="x", value=0.0)]
    )

    assert transform_dedicated_way_values(definition, "num_live", {"way:2": 1.0}) == {"way:2": 10.0}
