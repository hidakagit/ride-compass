"""`domain/dynamic_way_values.py`——ルートを出す前の地図が塗る値を、フィーチャーの材料と配信のサービスが配る値から
求めること（`paint_feature_values`）と、道1本のフィーチャーの値を区間から畳むこと（`paint_folded_feature_values`）。

材料カタログは本番の正本を読まず、性質だけを持つ架空の材料を使う（塗る値の種類は`domain/map_paint.py`を、区間ごとに
値が違いうるか・密度の軸かは`domain/material_catalog.py`を通るので、両方の名前空間を差し替える）。

ここで見ないもの:
- 塗る値の種類・段の境界・凡例の目盛り（`map_paint`） → `test_map_paint.py`
- 折れ線の得点・対応表・0次条件の評価そのもの（`domain/axis_definitions.py: evaluate_axis_array`） → `test_axis_definitions.py`
- 軸から配るサービスを選ぶこと・要求の条件の組み立て・配信のAPI → `test_region_routes.py`
- 区間の材料を読むこと → `test_feature_materials_in_tile.py`、勾配の区間ごとの向き → `test_gradient_way_service.py`
"""

import numpy as np
import pytest

from app.domain import map_paint, material_catalog
from app.domain.attributes import CategoricalColumn, EdgeMaterialArrays
from app.domain.axis_definitions import (
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.domain.difficulty import weighted_mean_by_distance
from app.domain.dynamic_way_values import FeatureSegments, paint_feature_values, paint_folded_feature_values
from app.domain.evaluation import build_static_edge_score_matrix
from app.domain.map_paint import SignedMaterialMapValue
from app.domain.material_catalog import CoverageExcluded, MaterialSpec
from app.domain.route import DensityScoreInput, RouteSegmentDetail, merge_axis_difficulties
from tests.axis_system_fixture import replaced_axis_definitions, shaped_axis


def _material(material_id, dtype="numeric", unit="", value_sql=None, additive=False) -> MaterialSpec:
    return MaterialSpec(
        material_id=material_id,
        label=material_id,
        description="架空の材料",
        dtype=dtype,
        unit=unit,
        tile_property=None,
        value_sql=value_sql,
        additive=additive,
        coverage=CoverageExcluded(reason="架空", missing_semantics="definite"),
    )


CATALOG = {spec.material_id: spec for spec in [
    _material("num_a", unit="%"), _material("num_b"), _material("bool_a", dtype="boolean"),
    _material("cat_a", dtype="categorical"),
    # 区間ごとに値が違いうる材料（値式が区間の値を読む）: 土地被覆のような割合・勾配のような向きのある値・1kmあたりの回数。
    _material("seg_cover", value_sql="em.cover"), _material("seg_grade", unit="%", value_sql="em.grade"),
    _material("seg_count", value_sql="em.count / (re.distance_m / 1000.0)", additive=True),
    # 道1本で決まる材料（道のタグ）。
    _material("way_num", value_sql="w.num"),
]}


@pytest.fixture
def catalog(monkeypatch):
    """材料カタログ（架空の材料だけ）。"""
    monkeypatch.setattr(map_paint, "MATERIAL_CATALOG", CATALOG)
    monkeypatch.setattr(material_catalog, "MATERIAL_CATALOG", CATALOG)


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


#: 道1本の値を区間から畳む軸と、畳まない軸（密度の軸）。
FOLDED_AXES = {axis.axis_id: axis for axis in [
    _axis("axis_cover", _line("seg_cover", "way_num", breakpoints=((0.0, 0.0), (5.0, 80.0), (20.0, 100.0)))),
    _axis("axis_density", _line("seg_count")),
    shaped_axis(_line("seg_count"), axis_id="axis_internal_density"),
    _axis("axis_composite", _line("axis_internal_density", "way_num", breakpoints=((0.0, 0.0), (30.0, 90.0), (60.0, 100.0)))),
    _axis("axis_grade", _line("seg_grade", preprocess="abs", breakpoints=((0.0, 0.0), (3.0, 30.0), (10.0, 100.0)))),
]}

#: 道ごとの区間（長さm・割合・向きを付けた勾配・1kmあたりの回数）。値の無い区間と、上りと下りが打ち消す道を含む。
WAYS = {
    "way-1": [(120.0, 4.0, 6.0, 0.0), (35.0, 30.0, -9.0, 28.6), (300.0, np.nan, 1.0, 3.3), (80.0, 12.0, np.nan, 0.0)],
    "way-2": [(400.0, 2.0, -2.5, 5.0)],
    "way-3": [(60.0, 50.0, 8.0, 0.0), (60.0, 0.0, -8.0, 16.7)],
}
WAY_NUM = {"way-1": 3.0, "way-2": 0.0, "way-3": 10.0}


def _segment_tile():
    """道1本のフィーチャーの材料と区間の材料。道の材料は、道のタグはその値、区間の材料は区間の値の距離平均
    （道の表の値と同じ。勾配のように道の表に無い材料は配信の値）。"""
    keys = list(WAYS)
    segment_keys = [key for key in keys for _ in WAYS[key]]
    rows = [row for key in keys for row in WAYS[key]]
    distance_m, cover, grade, count = (np.array(column, dtype=float) for column in zip(*rows))

    def way_mean(column):
        return np.array([weighted_mean_by_distance(
            [(None if np.isnan(value) else value, distance) for value, distance, owner
             in zip(column, distance_m, segment_keys) if owner == key]) for key in keys], dtype=float)

    way_grade = way_mean(grade)
    materials = {"seg_cover": way_mean(cover), "seg_count": way_mean(count),
                 "way_num": np.array([WAY_NUM[key] for key in keys])}
    served = {"seg_grade": {key: round(float(value), 1) for key, value in zip(keys, way_grade)}}
    segments = FeatureSegments(
        feature_keys=tuple(segment_keys), distance_m=distance_m, feature_bearing_deg=np.zeros(len(rows)),
        columns={"seg_cover": cover, "seg_count": count},
    )
    return keys, materials, served, segments, {"seg_grade": grade}


def _route_values(segments: FeatureSegments, grade: np.ndarray) -> dict[str, dict[str, float]]:
    """道ごとに、その区間をルートの区間に見立てた探索の得点を、ルートの値の決まりで畳んだ値。"""
    n = len(segments)
    nan = np.full(n, np.nan)
    owners = segments.feature_keys
    arrays = EdgeMaterialArrays(
        numeric_ids=("seg_cover", "seg_grade", "seg_count", "way_num"),
        numeric_values=np.column_stack([segments.columns["seg_cover"], grade, segments.columns["seg_count"],
                                        [WAY_NUM[owner] for owner in owners]]),
        categorical_ids=(), categorical_columns=(), hard_filter_ids=(), hard_filter_flags=np.empty((n, 0), dtype=bool),
        distance_m=segments.distance_m, bearing_deg=nan, mid_lat=nan, mid_lon=nan,
        elevation_present=np.zeros(n, dtype=bool), elevation_gain_m=nan, elevation_loss_m=nan,
    )
    with replaced_axis_definitions(FOLDED_AXES):
        matrix = build_static_edge_score_matrix(arrays, {})
    details: dict[str, list[RouteSegmentDetail]] = {}
    for row, owner in enumerate(owners):
        distance_km = float(segments.distance_m[row]) / 1000
        details.setdefault(owner, []).append(RouteSegmentDetail(
            start_latitude=0.0, start_longitude=0.0, end_latitude=0.0, end_longitude=0.0,
            cumulative_distance_km=0.0, distance_km=distance_km,
            axis_difficulties={axis_id: float(score) for axis_id, score
                               in zip(matrix.axis_ids, matrix.axis_scores[row]) if not np.isnan(score)},
        ).with_density_inputs({
            axis_id: DensityScoreInput(value=float(column.inputs[row]), distance_km=distance_km, weight_share=None,
                                       shape=column.shape)
            for axis_id, column in matrix.density_axes.items() if not np.isnan(column.inputs[row])
        }))
    return {owner: merge_axis_difficulties(segments) for owner, segments in details.items()}


# 引いた地図の道の色が、その道をルートとして走ったときのルートの値と同じ決まりで出る。食い違うと、地図で良く見えた道を
# 走ったルートが悪い値になる（区間ごとに値の違う割合・勾配と、それを読む軸を参照する軸と、密度の軸）。
@pytest.mark.parametrize("axis_id", [axis_id for axis_id, axis in FOLDED_AXES.items()
                                     if axis.is_published and axis_id != "axis_grade"])
def test_a_way_is_painted_with_the_value_of_a_route_along_its_segments(axis_id):
    keys, materials, served, segments, served_segments = _segment_tile()
    expected = _route_values(segments, served_segments["seg_grade"])

    painted = paint_folded_feature_values(axis_id, FOLDED_AXES, keys, materials, served, segments, served_segments)

    assert painted == {key: expected[key][axis_id] for key in keys}


def test_a_way_painted_with_a_signed_material_keeps_the_band_of_the_route_and_the_direction_of_the_whole_way():
    """勾配の地図は、道1本の色の段がルートの勾配の値と同じ段になり、上りか下りかは道全体で決まる。上って下る道
    （way-3）が平坦の色になると、坂のある道が平坦に見える。"""
    keys, materials, served, segments, served_segments = _segment_tile()
    expected = _route_values(segments, served_segments["seg_grade"])
    shape = FOLDED_AXES["axis_grade"].shape

    painted = paint_folded_feature_values("axis_grade", FOLDED_AXES, keys, materials, served, segments, served_segments)

    assert {key: shape.score_at(abs(value)) for key, value in painted.items()} == {
        key: expected[key]["axis_grade"] for key in keys}
    assert {key: np.sign(value) for key, value in painted.items()} == {"way-1": 1.0, "way-2": -1.0, "way-3": 1.0}
    assert painted["way-3"] >= 3.0


def test_a_way_undetermined_by_bearing_stays_so_and_a_way_without_segments_keeps_its_own_value():
    """向きで決まらない道は「向きで決まらない」のまま、区間の無い道（区間を作れない道）は道1本の値で塗る。"""
    keys, materials, served, segments, served_segments = _segment_tile()
    keys = [*keys, "way-4"]
    materials = {material_id: np.append(column, 7.0) for material_id, column in materials.items()}
    served = {"seg_grade": {**served["seg_grade"], "way-1": None}}

    painted = paint_folded_feature_values("axis_cover", FOLDED_AXES, keys, materials, served, segments, served_segments)
    graded = paint_folded_feature_values("axis_grade", FOLDED_AXES, keys, materials, served, segments, served_segments)

    assert painted["way-4"] == paint_feature_values("axis_cover", FOLDED_AXES, ["way-4"], {
        material_id: column[-1:] for material_id, column in materials.items()}, {})["way-4"]
    assert graded["way-1"] is None
