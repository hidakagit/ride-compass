"""`domain/map_paint.py`——地図が軸について塗るもの（`map_paint`）。

入口は`map_paint`1本で、塗る値の種類・材料・単位・ルート線の段の境界・凡例の目盛りを1つの値で返す。

材料カタログと軸の集合は本番の正本を読まず、性質だけを持つ架空の材料・軸へ差し替える（`MATERIAL_CATALOG`・
`AXIS_DEFINITIONS`。段の境界は`domain/axis_display.py`を、量の単位は`domain/axis_raw_value.py`を通るので、
そちらの名前空間も差し替える）。

ここで見ないもの:
- 地図の段の境界そのもの（どの軸が地図に塗れるか・境界の導出） → `test_axis_display.py`
- 配る材料の生値を塗る値へ写すこと → `test_dynamic_way_values.py`
"""

import pytest

from app.domain import axis_display, axis_raw_value, map_paint as map_paint_module
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.domain.map_paint import (
    DEFAULT_DIFFICULTY_BOUNDARIES,
    DifficultyMapValue,
    MapLegendScale,
    SignedMaterialMapValue,
    map_paint,
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
    for module in (map_paint_module, axis_display, axis_raw_value):
        monkeypatch.setattr(module, "MATERIAL_CATALOG", CATALOG)
    monkeypatch.setattr(axis_display, "AXIS_DEFINITIONS", saved)
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
    paint = map_paint(SIGNED)

    assert (paint.value, paint.unit) == (SignedMaterialMapValue(material="num_live"), "%")


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

    assert map_paint(definition).value == DifficultyMapValue()


# --- ルート線の段の境界 ---


def test_signed_material_bands_open_symmetrically_from_the_axis_knots():
    """軸は|値|を評価しているので、段も0を挟んで同じ境界で開く。0の節は境界にしない。"""
    assert map_paint(SIGNED).thresholds == [-6.0, -2.0, 2.0, 6.0]


def test_an_override_on_an_axis_the_tiles_cannot_paint_is_used_as_is():
    """専用の配信で塗る軸の上書きは、地図が塗る値そのものに対する境界。"""
    definition = SIGNED.model_copy(update={"display_thresholds_override": [-3.0, 0.0, 3.0]})

    assert map_paint(definition).thresholds == [-3.0, 0.0, 3.0]


def test_a_difficulty_axis_the_tiles_cannot_paint_is_cut_at_the_default_difficulty_bands():
    assert map_paint(_axis(_line("num_live", "num_other", preprocess="abs"))).thresholds == list(
        DEFAULT_DIFFICULTY_BOUNDARIES
    )


def test_the_default_difficulty_boundaries_are_strictly_ascending():
    """地図の式（MapLibreの`step`）は段の境界が厳密に昇順でないと式ごと失敗し、レイヤーが黙って消える。"""
    boundaries = list(DEFAULT_DIFFICULTY_BOUNDARIES)

    assert boundaries == sorted(set(boundaries))


def test_route_line_bands_of_a_categorical_axis_are_the_map_bands():
    """分類の軸の地図の値は初めから得点なので、写さない。"""
    definition = _axis(CategoricalShape(material="kind", mapping={"x": 0.0, "y": 40.0, "z": 100.0}))

    assert map_paint(definition).thresholds == [20.0, 70.0]


# --- 凡例の目盛り ---

RAIN_LINE = ((0.0, 0.0), (5.0, 30.0), (20.0, 70.0), (50.0, 100.0))


def test_an_axis_scoring_a_quantity_is_cut_at_its_knots_and_written_in_that_quantity():
    """雨のように単位のある量1つから得点を作る軸は、軸が効きの変わり目とした節で段を切り、凡例はその量で書く。"""
    paint = map_paint(_axis(_line("rain_live", breakpoints=RAIN_LINE), dedicated_way_value_layer=True))

    assert paint.thresholds == [30.0, 70.0, 100.0]
    assert paint.legend == MapLegendScale(boundaries=[5.0, 20.0, 50.0], unit="mm")


def test_a_tile_painted_axis_scoring_a_quantity_is_written_at_its_map_bands_in_that_quantity():
    """タイルで塗る軸の地図の段は初めから量の目盛りなので、凡例はそれをそのまま量で書く。地図は材料の重み付き和を、
    ルート線は難易度を塗るので、同じ段になるよう、ルート線の境界は地図の境界を折れ線で写す。"""
    paint = map_paint(
        _axis(
            _line("count_tiled", breakpoints=((0.0, 0.0), (4.0, 20.0), (10.0, 80.0))),
            display_thresholds_override=[2.0, 7.0],
        )
    )

    assert paint.thresholds == pytest.approx([10.0, 50.0])
    assert paint.legend == MapLegendScale(boundaries=[2.0, 7.0], unit="件")


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
    paint = map_paint(definition)

    assert paint.legend == MapLegendScale(boundaries=paint.thresholds, unit=None)


def test_a_signed_material_axis_is_written_in_the_material_unit():
    assert map_paint(SIGNED).legend == MapLegendScale(boundaries=[-6.0, -2.0, 2.0, 6.0], unit="%")
