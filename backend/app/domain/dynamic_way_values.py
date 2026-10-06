"""専用way値レイヤー（`dedicated_way_value_layer=True`の軸）の、要求の条件の組み立てと、配った生値から地図が塗る値への写し。
状態機械（ルート未確定=ユーザー指定パラメータを全道路へ一律適用／ルート確定後=ルート自身の実値を
ルート線のみへ適用）は軸非依存で、要求の条件（時刻・向き・速度）のうち何が要るかは値を返す
サービスが受け取る条件の型で決まる（`assemble_conditions`）。

**この層で扱うidは軸id（`axis_definitions.axis_id`）であり、材料id
（`material_catalog.py`のキー、例: `wind_drag_ratio`）ではない。**両者は名前空間が
異なる別概念で、配信サービスが返す生値の材料idは`WindWayService.material_id`等が
別に持つ（`transform_dedicated_way_values`が軸定義の評価へ渡す先）。

軸→サービス実装本体の対応は、軸が参照する材料とサービスの`material_id`の突き合わせで
決まる（`services/dedicated_way_values.py: DEDICATED_WAY_VALUE_SERVICES`）。材料ごとの計算ロジック
自体は宣言的に導出できないPythonコードのまま残る。
"""

from collections.abc import Mapping
from dataclasses import MISSING, dataclass, fields
from datetime import datetime
from typing import TYPE_CHECKING, Literal, TypeVar

from app.domain.axis_definitions import AxisDefinition, evaluate_axis_values
from app.domain.map_paint import SignedMaterialMapValue, map_paint

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

#: 専用配信の要求が運ぶ条件の名前。`WayValueQuery`の欄の名前で、配信のクエリパラメータの名前でもある。
WayValueConditionName = Literal["at", "bearing_deg", "speed_kmh"]


@dataclass(frozen=True)
class WayValueQuery:
    """専用配信の要求が運ぶ条件。どれも省略されうる——どれが要るかは、値を返すサービスが
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


def transform_dedicated_way_values(
    definition: AxisDefinition, material_id: str, values: Mapping[str, float | None]
) -> dict[str, float | None]:
    """専用way値配信サービスが返した材料生値（`material_id`の値）を、地図が塗るべき値へ
    変換する。塗る値（`map_paint`）が難易度なら軸スタジオの定義（breakpoints・
    priority_overrides）で評価した難易度、符号付き材料なら生値のまま。評価できない
    値（軸が他の材料も必須にしている等）はその道路を結果から除く（地図上は「データなし」）。
    走行方位で決まらない値（None）は、Noneのまま返す（地図上は「向きで決まらない」）。
    タイル内の全道路を1回の配列評価で求める。
    """
    if isinstance(map_paint(definition).value, SignedMaterialMapValue):
        return dict(values)
    if any(override.material != material_id for override in definition.priority_overrides):
        # 配信が値を持つのは`material_id`だけで、ほかの材料に置いた0次条件は当たるかどうかを決められない。
        return {}
    known = {key: value for key, value in values.items() if value is not None}
    feature_keys = list(known)
    difficulties = evaluate_axis_values(
        definition, {material_id: [known[key] for key in feature_keys]}, len(feature_keys)
    )
    transformed: dict[str, float | None] = {key: None for key, value in values.items() if value is None}
    transformed.update(
        (key, difficulty) for key, difficulty in zip(feature_keys, difficulties) if difficulty is not None
    )
    return transformed

