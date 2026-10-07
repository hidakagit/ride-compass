"""`domain/dynamic_way_values.py`——ルートを出す前に全道路へ配る軸について、配る材料の生値を地図が塗る値へ写すこと
（`transform_dedicated_way_values`）。

材料カタログは本番の正本を読まず、性質だけを持つ架空の材料へ差し替える（`MATERIAL_CATALOG`。塗る値の種類は
`domain/map_paint.py`を通るので、そちらの名前空間を差し替える）。

ここで見ないもの:
- 塗る値の種類・段の境界・凡例の目盛り（`map_paint`） → `test_map_paint.py`
- 折れ線の得点・0次条件の評価（`domain/axis_definitions.py: evaluate_axis_values`） → `test_axis_definitions.py`。
  配る材料に置いた条件が当たる道の得点も見ない——条件は真偽・分類の材料にしか置けず（`check_axis_definition`）、
  配る材料はどれも数値なので、本番の専用配信の軸で当たる条件は起こらない
- 材料から配るサービスを選ぶこと・配信のAPI → `test_dedicated_way_values.py`・`test_region_routes.py`
- 要求の条件の組み立て（`assemble_conditions`） → `test_region_routes.py`（配信と区間インスペクタの入口で）
"""

import math

import pytest

from app.domain import map_paint
from app.domain.axis_definitions import BreakpointLinearShape, MaterialTerm, PriorityCondition
from app.domain.dynamic_way_values import transform_dedicated_way_values
from app.domain.material_catalog import CoverageExcluded, MaterialSpec
from tests.axis_system_fixture import shaped_axis


def _material(material_id, unit="") -> MaterialSpec:
    return MaterialSpec(
        material_id=material_id,
        label=material_id,
        description="架空の材料",
        dtype="numeric",
        unit=unit,
        tile_property=None,
        coverage=CoverageExcluded(reason="架空", missing_semantics="definite"),
    )


CATALOG = {spec.material_id: spec for spec in [_material("num_live", unit="%"), _material("num_other")]}


@pytest.fixture
def catalog(monkeypatch):
    """材料カタログ（架空の材料だけ）。"""
    monkeypatch.setattr(map_paint, "MATERIAL_CATALOG", CATALOG)


pytestmark = pytest.mark.usefixtures("catalog")


def _line(*materials, breakpoints=((0.0, 0.0), (10.0, 100.0)), preprocess="identity") -> BreakpointLinearShape:
    return BreakpointLinearShape(
        terms=[MaterialTerm(material=m) for m in materials], breakpoints=list(breakpoints), preprocess=preprocess
    )


SIGNED = shaped_axis(_line("num_live", breakpoints=((0.0, 0.0), (2.0, 30.0), (6.0, 100.0)), preprocess="abs"))


# --- 生値から塗る値へ ---

VALUES = {"way:1": -4.0, "way:2": 1.0, "edge:3": 12.0}


def test_a_signed_material_axis_paints_the_raw_values_unchanged():
    assert transform_dedicated_way_values(SIGNED, "num_live", VALUES) == VALUES


def test_a_difficulty_axis_paints_each_feature_by_the_axis():
    """折れ線の外は両端の得点へ寄る。"""
    definition = shaped_axis(_line("num_live"))

    assert transform_dedicated_way_values(definition, "num_live", VALUES) == {
        "way:1": 0.0,
        "way:2": 10.0,
        "edge:3": 100.0,
    }


def test_a_feature_the_axis_cannot_evaluate_is_left_unpainted():
    """地図では「データなし」になる。"""
    result = transform_dedicated_way_values(shaped_axis(_line("num_live")), "num_live", {"way:1": math.nan, "way:2": 5.0})

    assert result == {"way:2": 50.0}


def test_a_feature_undetermined_by_the_bearing_stays_undetermined():
    """地図では「向きで決まらない」になり、値の無い道（鍵ごと無い）と見分けられる。"""
    result = transform_dedicated_way_values(shaped_axis(_line("num_live")), "num_live", {"way:1": None, "way:2": 5.0})

    assert result == {"way:1": None, "way:2": 50.0}


def test_an_axis_that_also_needs_a_material_not_served_paints_nothing():
    """配信が値を持つのは1つの材料だけ。必須の別の材料が無ければ、どの道も評価できない。"""
    definition = shaped_axis(_line("num_live", "num_other"))

    assert transform_dedicated_way_values(definition, "num_live", VALUES) == {}


def test_a_condition_on_a_material_not_served_paints_nothing():
    """条件が当たるかを決められない。条件を落として塗ると、条件の当たる道で評価と食い違う。"""
    definition = shaped_axis(
        _line("num_live"), priority_overrides=[PriorityCondition(material="num_other", equals="x", value=0.0)]
    )

    assert transform_dedicated_way_values(definition, "num_live", VALUES) == {}


def test_a_condition_on_the_served_material_does_not_stop_the_painting():
    """条件が配る材料にだけ置かれていれば、当たるかを決められるので塗る（ここで当たらない条件は得点を変えない）。"""
    definition = shaped_axis(
        _line("num_live"), priority_overrides=[PriorityCondition(material="num_live", equals="x", value=0.0)]
    )

    assert transform_dedicated_way_values(definition, "num_live", {"way:2": 1.0}) == {"way:2": 10.0}
