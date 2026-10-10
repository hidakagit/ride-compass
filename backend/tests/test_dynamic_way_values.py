"""`domain/dynamic_way_values.py`——ルートを出す前の地図が塗る値を、フィーチャーの材料と配信のサービスが配る値から
求めること（`paint_feature_values`）。

材料カタログは本番の正本を読まず、性質だけを持つ架空の材料を使う（塗る値の種類は`domain/map_paint.py`を通るので、
そちらの名前空間を差し替える）。

ここで見ないもの:
- 塗る値の種類・段の境界・凡例の目盛り（`map_paint`） → `test_map_paint.py`
- 折れ線の得点・対応表・0次条件の評価そのもの（`domain/axis_definitions.py: evaluate_axis_array`） → `test_axis_definitions.py`
- 軸から配るサービスを選ぶこと・要求の条件の組み立て・配信のAPI → `test_region_routes.py`
"""

import numpy as np
import pytest

from app.domain import map_paint
from app.domain.attributes import CategoricalColumn, EdgeMaterialArrays
from app.domain.axis_definitions import (
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.domain.dynamic_way_values import paint_feature_values
from app.domain.evaluation import build_static_edge_score_matrix
from app.domain.map_paint import SignedMaterialMapValue
from app.domain.material_catalog import CoverageExcluded, MaterialSpec
from tests.axis_system_fixture import replaced_axis_definitions, shaped_axis


def _material(material_id, dtype="numeric", unit="") -> MaterialSpec:
    return MaterialSpec(
        material_id=material_id,
        label=material_id,
        description="架空の材料",
        dtype=dtype,
        unit=unit,
        tile_property=None,
        coverage=CoverageExcluded(reason="架空", missing_semantics="definite"),
    )


CATALOG = {spec.material_id: spec for spec in [
    _material("num_a", unit="%"), _material("num_b"), _material("bool_a", dtype="boolean"),
    _material("cat_a", dtype="categorical"),
]}


@pytest.fixture
def catalog(monkeypatch):
    """材料カタログ（架空の材料だけ）。"""
    monkeypatch.setattr(map_paint, "MATERIAL_CATALOG", CATALOG)


pytestmark = pytest.mark.usefixtures("catalog")


def _line(*materials, breakpoints=((0.0, 0.0), (10.0, 100.0)), preprocess="identity") -> BreakpointLinearShape:
    return BreakpointLinearShape(
        terms=[MaterialTerm(material=m) for m in materials], breakpoints=list(breakpoints), preprocess=preprocess
    )


def _axis(axis_id, shape, **fields):
    return shaped_axis(shape, axis_id=axis_id, is_published=True, **fields)


#: 地図に出る軸の形を1本ずつ。どれも公開軸で、`axis_internal`だけが参照される内部軸。
AXES = {axis.axis_id: axis for axis in [
    _axis("axis_line", _line("num_a", "bool_a")),
    _axis("axis_categorical", CategoricalShape(material="cat_a", mapping={"x": 10.0, "y": 90.0})),
    _axis("axis_flag", CategoricalShape(material="bool_a", mapping={"true": 80.0, "false": 20.0})),
    shaped_axis(_line("num_b"), axis_id="axis_internal"),
    _axis("axis_reference", _line("axis_internal", "num_a", breakpoints=((0.0, 0.0), (200.0, 100.0)))),
    _axis("axis_abs", _line("num_a", "num_b", preprocess="abs")),
    _axis("axis_signed", _line("num_b", preprocess="abs")),
    _axis("axis_condition", _line("num_a"), priority_overrides=[PriorityCondition(material="cat_a", equals="y", value=0.0)]),
]}

#: 欠けた値（NaN・値なし）と、正負の値・分類の値を混ぜた行。
NUM_A = [3.0, -12.0, np.nan, 7.5, 0.0]
NUM_B = [-4.0, np.nan, 2.0, 15.0, 0.0]
BOOL_A = [1.0, 0.0, np.nan, 1.0, 0.0]
CAT_A = ["x", "y", None, "z", "y"]


def _arrays() -> EdgeMaterialArrays:
    n = len(NUM_A)
    nan = np.full(n, np.nan)
    return EdgeMaterialArrays(
        numeric_ids=("num_a", "num_b", "bool_a"), numeric_values=np.column_stack([NUM_A, NUM_B, BOOL_A]),
        categorical_ids=("cat_a",), categorical_columns=(CategoricalColumn.encode(CAT_A),),
        hard_filter_ids=(), hard_filter_flags=np.empty((n, 0), dtype=bool),
        distance_m=np.full(n, 100.0), bearing_deg=nan, mid_lat=nan, mid_lon=nan,
        elevation_present=np.zeros(n, dtype=bool), elevation_gain_m=nan, elevation_loss_m=nan,
    )


# 地図の色と、探索が同じ道に付ける得点が、同じ材料なら同じになる。食い違うと、地図で良く見えた道を探索が避ける。
# 符号付き材料を塗る軸は、得点ではなく材料の値（符号つき）を塗る。
@pytest.mark.parametrize("axis_id", [axis_id for axis_id, axis in AXES.items() if axis.is_published])
def test_the_map_paints_the_same_value_the_search_scores(axis_id):
    arrays = _arrays()
    keys = [f"feature-{row}" for row in range(len(arrays))]
    with replaced_axis_definitions(AXES):
        matrix = build_static_edge_score_matrix(arrays, {})

    painted = paint_feature_values(axis_id, AXES, keys, arrays.columns(), {})

    paint = map_paint.map_paint(AXES[axis_id]).value
    if isinstance(paint, SignedMaterialMapValue):
        expected = arrays.columns()[paint.material]
    else:
        expected = matrix.axis_scores[:, matrix.axis_ids.index(axis_id)]
    assert np.isfinite(expected).any()
    np.testing.assert_array_equal([painted.get(key, np.nan) for key in keys], expected)


def test_values_from_a_service_replace_the_material_of_the_tile():
    """配信のサービスが返さなかったフィーチャーは「データなし」、Noneで返したフィーチャーは「向きで決まらない」に
    なり、地図で見分けられる。タイルの材料に同じ材料の値があっても、サービスの値で塗る。返さなかったフィーチャーを
    先に置く（その後ろのフィーチャーの値を落とさないことも見る）。"""
    keys = ["feature-2", "feature-0", "feature-1"]
    tile = {"num_a": np.array([1.0, 1.0, 1.0])}

    painted = paint_feature_values(
        "axis_signed", AXES, keys, tile, {"num_b": {"feature-0": -4.0, "feature-1": None, "elsewhere": 9.0}}
    )

    assert painted == {"feature-0": -4.0, "feature-1": None}
