"""一次属性・二次軸のレジストリ（改善計画T137）。

新しい一次属性・二次軸を、コアロジック（コスト関数・レイヤーパネル・区間インスペクタ等）を
改修せず「ここへ1件登録する」だけで取り込めるようにするための宣言的な定義集。

- `PrimaryAttributeSpec`: 一次属性（OSM生タグ・外部静的データ等）の出どころの宣言。
- `AxisSpec`: 二次軸（一次属性から軸スコアへの変換）の宣言。`inputs`が使用する一次属性の
  `attr_id`リスト。

**排他制約はレジストリ登録時に機械的にチェックする**（設計方針の核）。`register_axis()`は、
登録しようとする軸の`inputs`のうち`shared=False`の一次属性が、既に登録済みの別軸の
`inputs`と重複していれば`AxisInputConflictError`を送出する。`shared=True`の一次属性
（区間の距離・形状など全軸が参照してよい共通コンテキスト）は排他チェックの対象外。

現時点（T137）では「車ストレス」「安全度」「自転車インフラ」の3軸は入力が重複したまま
（`domain/traffic.py`/`domain/safety.py`参照、T130で意図的に共有）のため、この3つは
まだここへ登録しない（T138〜T139で軸自体を再編したうえで登録する）。それ以外の既存軸
（勾配・風・路面・停止密度・交差点密度・事故密度）はここに登録済み。
"""

from typing import Callable, Literal

from pydantic import BaseModel, Field

Geometry = Literal["edge", "point"]
DType = Literal["categorical", "numeric", "boolean", "geometry"]
UpdateCadence = Literal["static", "monthly", "quarterly", "yearly", "on_reimport"]


class PrimaryAttributeSpec(BaseModel):
    """一次属性の宣言。`ingest_fn`はモジュールパス文字列（`"app.domain.osm_adapter.osm_way_to_way_spec"`
    のような参照）で持ち、実体をimportしない（レジストリ自体は取込パイプラインへ依存しない、
    宣言のみのモジュールにするため）。
    """

    attr_id: str
    source: str
    geometry: Geometry
    dtype: DType
    update_cadence: UpdateCadence
    description: str
    ingest_fn: str | None = None
    shared: bool = False


class AxisSpec(BaseModel):
    """二次軸の宣言。`inputs`は参照する一次属性の`attr_id`リスト（`register_axis`が
    登録済みの一次属性であることを検証する）。`transform_fn`は`PrimaryAttributeSpec.ingest_fn`
    と同じくモジュールパス文字列。"""

    axis_id: str
    inputs: list[str]
    transform_fn: str
    output_range: tuple[float, float] = (0.0, 1.0)
    description: str


class AxisInputConflictError(ValueError):
    """新規登録しようとした軸の入力一次属性が、既存の別軸と重複している場合に送出する。"""

    def __init__(self, new_axis_id: str, existing_axis_id: str, overlapping_attrs: set[str]) -> None:
        self.new_axis_id = new_axis_id
        self.existing_axis_id = existing_axis_id
        self.overlapping_attrs = overlapping_attrs
        attrs = ", ".join(sorted(overlapping_attrs))
        super().__init__(
            f"axis '{new_axis_id}' shares non-shared input(s) [{attrs}] with already-registered "
            f"axis '{existing_axis_id}'; each primary attribute may belong to at most one axis "
            f"(exclusive assignment principle) unless marked shared=True"
        )


_PRIMARY_ATTRIBUTES: dict[str, PrimaryAttributeSpec] = {}
_AXES: dict[str, AxisSpec] = {}


def register_primary_attribute(spec: PrimaryAttributeSpec) -> None:
    if spec.attr_id in _PRIMARY_ATTRIBUTES:
        raise ValueError(f"primary attribute already registered: {spec.attr_id}")
    _PRIMARY_ATTRIBUTES[spec.attr_id] = spec


def _exclusive_inputs(inputs: list[str]) -> set[str]:
    return {attr_id for attr_id in inputs if not _PRIMARY_ATTRIBUTES[attr_id].shared}


def register_axis(spec: AxisSpec) -> None:
    """二次軸を登録する。

    `inputs`に未登録の一次属性が含まれる場合、または`shared=False`の一次属性が既存の
    別軸とかぶる場合はエラーを送出し、登録は行わない（部分登録によるレジストリの不整合を防ぐ）。
    """
    unknown = [attr_id for attr_id in spec.inputs if attr_id not in _PRIMARY_ATTRIBUTES]
    if unknown:
        raise ValueError(f"axis '{spec.axis_id}' references unregistered primary attribute(s): {unknown}")

    if spec.axis_id in _AXES:
        raise ValueError(f"axis already registered: {spec.axis_id}")

    new_exclusive = _exclusive_inputs(spec.inputs)
    for existing in _AXES.values():
        overlap = new_exclusive & _exclusive_inputs(existing.inputs)
        if overlap:
            raise AxisInputConflictError(spec.axis_id, existing.axis_id, overlap)

    _AXES[spec.axis_id] = spec


def get_primary_attribute(attr_id: str) -> PrimaryAttributeSpec:
    return _PRIMARY_ATTRIBUTES[attr_id]


def get_axis(axis_id: str) -> AxisSpec:
    return _AXES[axis_id]


def all_primary_attributes() -> list[PrimaryAttributeSpec]:
    return list(_PRIMARY_ATTRIBUTES.values())


def all_axes() -> list[AxisSpec]:
    return list(_AXES.values())


def reset_registry_for_testing() -> None:
    """テスト用: グローバルなレジストリ状態を空に戻す。本体コードからは呼ばない。"""
    _PRIMARY_ATTRIBUTES.clear()
    _AXES.clear()
