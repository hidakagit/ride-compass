"""ルートを出す前の地図が塗る軸の値の、要求の条件の組み立てと、フィーチャーの材料から地図が塗る値への写し。

状態機械（ルート未確定=利用者が決めた条件を全道路へ一律適用／ルート確定後=ルート自身の実値をルート線のみへ
適用）は軸非依存で、要求の条件（時刻・向き・速度）のうち何が要るかは、軸の葉の材料の値を配るサービスが受け取る
条件の型で決まる（`assemble_conditions`）。

**この層で扱うidは軸id（`axis_definitions.axis_id`）であり、材料id（`material_catalog.py`のキー、例:
`wind_drag_ratio`）ではない。**両者は名前空間が異なる別概念で、軸は葉まで辿った材料で配信のサービスと結ばれる
（`services/dedicated_way_values.py: DEDICATED_WAY_VALUE_SERVICES`）。
"""

from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, fields
from datetime import datetime
from typing import TYPE_CHECKING, Literal, TypeVar, cast

import numpy as np

from app.domain.attributes import CategoricalColumn, MaterialColumn
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    averages_density,
    axis_dependencies,
    evaluate_axes_array,
)
from app.domain.difficulty import round_difficulty, weighted_mean_by_distance
from app.domain.evaluation import empty_material_arrays
from app.domain.geo import bearing_sector
from app.domain.map_paint import SignedMaterialMapValue, map_paint
from app.domain.material_catalog import segment_material_ids

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

#: 向きに依る値を、この幅（度）のバケットの中心の向きで計算した値で代える粒度。キャッシュは
#: バケットごとに1つの値を持ち、バケットの中の別の向きの要求にも同じ値を返す。
BEARING_BUCKET_DEG = 5


def bearing_bucket(bearing_deg: float) -> int:
    """向き（度、範囲外は正規化）をバケット番号へ丸める。360度は0度と同じバケットになる。"""
    return bearing_sector(bearing_deg, 360 // BEARING_BUCKET_DEG)


#: 地図の配信の要求が運ぶ条件の名前。`WayValueQuery`の欄の名前で、配信のクエリパラメータの名前でもある。
WayValueConditionName = Literal["at", "bearing_deg", "speed_kmh"]


@dataclass(frozen=True)
class WayValueQuery:
    """地図の配信の要求が運ぶ条件。どれも省略されうる——どれが要るかは、値を返すサービスが
    受け取る条件の型（`assemble_conditions`の`kind`）が決める。欄の名前は`WayValueConditionName`。"""

    at: datetime | None
    bearing_deg: float | None
    speed_kmh: float | None


@dataclass(frozen=True)
class MissingConditions:
    """サービスが要る条件のうち、要求に無かったものの名前（`WayValueQuery`の欄の名前）。"""

    names: tuple[str, ...]


_C = TypeVar("_C", bound="DataclassInstance")


def assemble_conditions(kind: type[_C], query: WayValueQuery) -> _C | MissingConditions:
    """サービスが受け取る条件（frozen dataclassの`kind`）を要求から組み立てる。

    `kind`の欄は`WayValueQuery`の同じ名前の欄から取り、既定値の無い欄が要るものになる。
    **方位・速度の欠けを判定するのはここだけ**——サービスは組み立て済みの値だけを受け取るので、
    要る欄は`None`を許さない型のまま届く。地図の配信は欠けを422に、区間インスペクタは
    「データなし」にする。
    """
    kind_fields = fields(kind)
    values = {field.name: getattr(query, field.name) for field in kind_fields}
    missing = tuple(
        field.name for field in kind_fields
        if values[field.name] is None and field.default is MISSING and field.default_factory is MISSING
    )
    if missing:
        return MissingConditions(missing)
    return kind(**values)


@dataclass(frozen=True)
class FeatureMaterials:
    """タイル1枚のフィーチャーごとの材料。`columns`の各列は`feature_keys`と同じ並びで、評価（`evaluate_axes_array`）へ
    そのまま渡せる形（数値・真偽はfloatの配列で欠損はNaN、分類は`CategoricalColumn`）。"""

    feature_keys: tuple[str, ...]
    columns: dict[str, MaterialColumn]

    def __len__(self) -> int:
        return len(self.feature_keys)


@dataclass(frozen=True)
class FeatureSegments:
    """道1本を1つのフィーチャーにするタイルの、フィーチャーごとの区間（`road_edges`の行）と、区間ごとに値が違いうる材料
    （`domain/material_catalog.py: segment_material_ids`）の区間の値。並びは区間ごとで、どの列も同じ並び。"""

    #: 区間が属するフィーチャーの鍵（`FeatureMaterials.feature_keys`と同じ鍵）。
    feature_keys: tuple[str, ...]
    distance_m: np.ndarray
    #: 区間が属するフィーチャー（道）の両端を結ぶ方位（度）。向きに依る材料を、道1本と同じ向きで読むのに使う。
    feature_bearing_deg: np.ndarray
    columns: dict[str, MaterialColumn]

    def __len__(self) -> int:
        return len(self.feature_keys)


def axis_with_dependencies(axis_id: str, definitions: Mapping[str, AxisDefinition]) -> dict[str, AxisDefinition]:
    """`axis_id`の軸と、それが材料として読む軸を内部軸まで辿ったもの。並びは`definitions`の並び。"""
    known = set(definitions)
    found: set[str] = set()
    pending = [axis_id]
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(axis_dependencies(definitions[current], known))
    return {key: definition for key, definition in definitions.items() if key in found}


def leaf_materials(definitions: Mapping[str, AxisDefinition]) -> set[str]:
    """`definitions`の軸が読む材料のうち、`definitions`の軸でないもの（葉の材料）。"""
    return {material for definition in definitions.values() for material in definition.materials
            if material not in definitions}


def _feature_columns(
    feature_keys: Sequence[str],
    materials: Mapping[str, MaterialColumn],
    served: Mapping[str, Mapping[str, float | None]],
) -> tuple[dict[str, MaterialColumn], np.ndarray]:
    """`materials`へ`served`の材料の列を重ねた列と、配信が値をNoneで返した（走行方位で決まらない）フィーチャーの印。"""
    n = len(feature_keys)
    columns: dict[str, MaterialColumn] = dict(materials)
    undetermined = np.zeros(n, dtype=bool)
    for material_id, values in served.items():
        column = np.full(n, np.nan)
        for row, key in enumerate(feature_keys):
            if key not in values:
                continue
            value = values[key]
            if value is None:
                undetermined[row] = True
            else:
                column[row] = value
        columns[material_id] = column
    columns.update(empty_material_arrays(n, columns))
    return columns, undetermined


def paint_feature_values(
    axis_id: str,
    definitions: Mapping[str, AxisDefinition],
    feature_keys: Sequence[str],
    materials: Mapping[str, MaterialColumn],
    served: Mapping[str, Mapping[str, float | None]],
) -> dict[str, float | None]:
    """フィーチャーごとに、地図が軸`axis_id`について塗る値（`map_paint`の塗る値が難易度なら得点、符号付き材料なら
    その材料の値）。

    `materials`は`feature_keys`と同じ並びの材料の列、`served`は配信のサービスが返した材料ごとの`{フィーチャーの鍵: 値}`で、
    同じ材料の列を置き換える（鍵の無いフィーチャーは欠損）。得点は探索の静的スコア行列と同じ評価
    （`evaluate_axes_array`）を、軸とそれが読む軸だけへ通して求める。どちらにも無い材料は値の無い列になる。

    評価できないフィーチャーは結果から除く（地図上は「データなし」）。配信が値をNoneで返したフィーチャー（走行方位で
    決まらない）は、Noneのまま返す（地図上は「向きで決まらない」）。
    """
    columns, undetermined = _feature_columns(feature_keys, materials, served)
    paint = map_paint(definitions[axis_id]).value
    if isinstance(paint, SignedMaterialMapValue):
        painted = np.asarray(columns[paint.material], dtype=float)
    else:
        painted = evaluate_axes_array(columns, axis_with_dependencies(axis_id, definitions))[axis_id]
    out: dict[str, float | None] = {}
    for row, key in enumerate(feature_keys):
        if undetermined[row]:
            out[key] = None
        elif not np.isnan(painted[row]):
            out[key] = float(painted[row])
    return out


def folds_segments(axis_id: str, definitions: Mapping[str, AxisDefinition]) -> bool:
    """道1本のフィーチャーの値を、その道の区間ごとに評価した得点から畳む軸か（`paint_folded_feature_values`）。

    ルートの値は区間の得点の距離平均で、区間ごとに値の違う材料を読む軸では、道1本の材料で評価した得点と違う。
    密度の軸（`averages_density`）は畳まない——ルートの値は横軸の値（1kmあたりの量）の距離平均の得点で、道1本の
    材料（道の数÷道の長さ）がその平均と同じ値になる。
    """
    if averages_density(definitions[axis_id]):
        return False
    return bool(leaf_materials(axis_with_dependencies(axis_id, definitions)) & segment_material_ids())


def _take(column: MaterialColumn, rows: np.ndarray) -> MaterialColumn:
    return column.take(rows) if isinstance(column, CategoricalColumn) else np.asarray(column)[rows]


def paint_folded_feature_values(
    axis_id: str,
    definitions: Mapping[str, AxisDefinition],
    feature_keys: Sequence[str],
    materials: Mapping[str, MaterialColumn],
    served: Mapping[str, Mapping[str, float | None]],
    segments: FeatureSegments,
    served_segments: Mapping[str, np.ndarray],
) -> dict[str, float | None]:
    """道1本のフィーチャーごとに地図が軸`axis_id`について塗る値を、その道の区間をルートの区間に見立てて、ルートの値と
    同じ決まり（`domain/route.py: merge_axis_difficulties`の、区間の得点の距離平均）で畳んで求める。

    区間の材料は、区間ごとに値が違いうる材料なら`segments`の区間の値（配信のサービスが配る材料は`served_segments`の
    区間の値）、ほかの材料は区間が属するフィーチャーの値（`paint_feature_values`と同じ`materials`・`served`）。
    区間から畳まない軸（`folds_segments`）と、区間の無いフィーチャーは、フィーチャーの値で評価する（`paint_feature_values`）。

    符号付き材料を塗る軸は、畳んだ得点を、その得点に当たる材料の値の大きさへ戻し（`smallest_magnitude_at`）、区間の
    材料の値の距離平均の符号（道全体で上るか下るか。平均が0なら正）を付ける——段はルートの値と揃い、地図は材料の
    目盛りと向きの塗り分けを保つ。配信が値をNoneで返したフィーチャーは、Noneのまま返す。
    """
    whole = paint_feature_values(axis_id, definitions, feature_keys, materials, served)
    if not folds_segments(axis_id, definitions):
        return whole
    columns, undetermined = _feature_columns(feature_keys, materials, served)
    row_of = {key: row for row, key in enumerate(feature_keys)}
    owner = np.array([row_of.get(key, -1) for key in segments.feature_keys], dtype=np.int64)
    kept = owner >= 0
    owner = owner[kept]
    distance_km = np.asarray(segments.distance_m, dtype=float)[kept] / 1000
    segment_columns: dict[str, MaterialColumn] = {
        material_id: _take(column, owner) for material_id, column in columns.items()
    }
    segment_columns.update({material_id: _take(column, np.flatnonzero(kept))
                            for material_id, column in {**segments.columns, **served_segments}.items()})
    dependencies = axis_with_dependencies(axis_id, definitions)
    scores = evaluate_axes_array(segment_columns, dependencies)[axis_id]

    by_feature: dict[int, list[int]] = {}
    for index, row in enumerate(owner.tolist()):
        by_feature.setdefault(row, []).append(index)
    paint = map_paint(definitions[axis_id]).value
    signed = np.asarray(segment_columns[paint.material], dtype=float) if isinstance(
        paint, SignedMaterialMapValue) else None
    out: dict[str, float | None] = {}
    for row, key in enumerate(feature_keys):
        indexes = by_feature.get(row)
        if undetermined[row]:
            out[key] = None
            continue
        if indexes is None:
            if key in whole:
                out[key] = whole[key]
            continue
        mean = weighted_mean_by_distance(
            [(None if np.isnan(scores[i]) else float(scores[i]), float(distance_km[i])) for i in indexes])
        if mean is None:
            continue
        score = round_difficulty(mean)
        if signed is None:
            out[key] = score
            continue
        direction = weighted_mean_by_distance(
            [(None if np.isnan(signed[i]) else float(signed[i]), float(distance_km[i])) for i in indexes])
        # `signed_material`は折れ線の軸にしか付かない。
        magnitude = cast(BreakpointLinearShape, definitions[axis_id].shape).smallest_magnitude_at(score)
        out[key] = -magnitude if direction is not None and direction < 0 else magnitude
    return out
