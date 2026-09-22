"""一次属性・二次軸のレジストリと、地図表示の宣言の型。

このモジュールが保証するのは2つだけである。

1. **一次属性の語彙が一意であること**——同じ`attr_id`を2度登録できず、登録した語彙は
   `all_primary_attributes()`が返す（ビルド時生成物`primary-attributes.json`の元）。
2. **一次属性が2つの軸へ跨がらないこと**——`register_axis()`は未登録の一次属性・
   重複した軸id・既存の軸との入力の重なりを送出して拒む。軸そのものは登録後に誰も
   読まない（実行時の軸カタログは`GET /api/axis-catalog`が配る）。**軸の登録は、
   この排他性の検査そのものである。**

`AxisDisplaySpec`/`TileInputSpec`はレジストリの状態ではなく、地図が軸をどう塗るかの
宣言の型で、`domain/axis_display.py`が組み立て`GET /api/axis-catalog`がそのまま配る。

登録そのものはここでは行わない（`domain/registry_defaults.py`が呼ぶ）。
"""

from typing import Literal

from pydantic import Field, field_validator, model_validator
from app.domain.strict_model import StrictModel


class PrimaryAttributeSpec(StrictModel):
    """一次属性の宣言。

    `label`はユーザー向け正式名称の単一ソース。`export_openapi.py`がaxis-catalog.jsonへ
    書き出し、フロントはそこから略名（地図チップ用）への対応表だけを別途持つ（片側import）。
    """

    attr_id: str
    #: 空を許すと、地図チップ・サイドバー・研究タブが名前を引けない属性を登録できてしまう。
    label: str = Field(min_length=1)


class TileInputSpec(StrictModel):
    """地図表示（ramp）が読むMVTタイルプロパティ。

    数値材料（既定）: フロントのMapLibre expressionが`Σ(property × weight)`を計算する。

    真偽値材料（`boolean=True`）: MVTの真偽値プロパティは真偽比較でしか読めず重み付け
    結合が成立しないため、`true_value`/`false_value`で寄与値を直接指定する（`weight`は
    無視される）。

    N値文字列材料（`categories`）: 文字列値を`categories`で引いた点数×`weight`を寄与値と
    する。`CategoricalShape`のmappingがbool2値ではなく3値以上（highway/surface等）の
    場合に使う。

    自己変換材料（`breakpoints`）: 区分線形（`BreakpointLinearShape`）で変換される軸の
    寄与値を、フロントの`interpolate`でタイル生値から直接求める。

    `has_unknown_fallback`: 値が引けないときの意味が「true/falseどちらでもない不明」
    （例: 未分類の路面）ならTrueにし、フロントは灰色「不明」へ倒す。既定Falseは
    「欠損=falseとみなしてよい」材料（例: lit。タグ不在は「無し」の安全側既定）を表す。
    `categories`材料では**未登録値**も不明に含める——`evaluate_categorical`が未登録値に
    Noneを返し`required=True`の軸全体を評価不能にするため、欠損だけを見ると、実際には
    未評価の区間が0点＝最良（緑）で表示されてしまう。真偽値材料には「未登録の値」という
    状態が無いため、欠損のみが不明になる。

    `needs_runtime_scale`: タイル生値が実行時にしか決まらない係数でのスケール変換を要する
    材料（例: 収録年数で正規化する前の事故件数）でTrue。`weight`が静的な変換係数を
    表現できないが、`GET /api/axis-catalog`が配るスケール定数をフロントのJS式が追加で
    掛けるため、地図表示の対象には含める。`thresholds`は材料スケールの値のままでよい。
    """

    property: str = Field(min_length=1)
    weight: float = 1.0
    boolean: bool = False
    true_value: float = 0.0
    false_value: float = 0.0
    has_unknown_fallback: bool = False
    categories: dict[str, float] | None = None
    breakpoints: list[tuple[float, float]] | None = None
    needs_runtime_scale: bool = False

    @model_validator(mode="after")
    def _check_one_form(self) -> "TileInputSpec":
        """寄与値の置き場は形ごとに1つだけ。2つ載せるとフロントの式がどちらか片方を選び、
        選ばれなかった側の指定が黙って消える。"""
        forms = [
            name
            for name, declared in (
                ("boolean", self.boolean),
                ("categories", self.categories is not None),
                ("breakpoints", self.breakpoints is not None),
            )
            if declared
        ]
        if len(forms) > 1:
            raise ValueError(f"tile input '{self.property}' declares more than one form: {forms}")
        if not self.boolean and (self.true_value or self.false_value):
            raise ValueError(f"tile input '{self.property}' sets true/false values without boolean=True")
        if self.boolean and self.weight != 1.0:
            raise ValueError(
                f"tile input '{self.property}' sets a weight the boolean form ignores; "
                "put the weight into true_value/false_value"
            )
        return self

    @field_validator("categories")
    @classmethod
    def _sort_categories(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        # 構築元（コード内リテラル・DB経由・APIレスポンス等）によって挿入順が非決定に
        # なりうるため、経路によらず決定的な順序へ正規化する。
        if value is None:
            return None
        return dict(sorted(value.items()))


class AxisDisplaySpec(StrictModel):
    """二次軸の地図レイヤー表示宣言（「事実はタイルに、解釈はクライアントに」）。

    - kind="ramp": タイルへ焼き込み済みの事実プロパティ（`tile_inputs`の線形結合）を
      `thresholds`（昇順、色段階の境界値）で色分けする汎用レイヤーを、フロントの
      レイヤーファクトリが自動生成する。新しい軸はこれを宣言するだけで地図に現れる。
    - kind="none": 専用の二次レイヤーを持たない（既存レイヤーで代替、またはデータ未整備）。
      `note`へ理由を書く。
    """

    kind: Literal["ramp", "none"]
    label: str = Field(min_length=1)
    category: str = "trafficSafety"
    tile_inputs: list[TileInputSpec] = Field(default_factory=list)
    thresholds: list[float] = Field(default_factory=list)
    unit: str = ""
    note: str = ""

    @model_validator(mode="after")
    def _check_kind_carries_its_payload(self) -> "AxisDisplaySpec":
        """`kind`とレイヤーの中身を食い違わせない。読む側は`kind`だけを見てレイヤーを
        作るため、食い違いはどちらの側でも「地図に出ているのに何も塗られない」に化ける。
        """
        if self.kind == "ramp":
            if not self.tile_inputs:
                raise ValueError(f"ramp display '{self.label}' has nothing to read from the tile")
        elif self.tile_inputs or self.thresholds:
            raise ValueError(f"display '{self.label}' is kind=none but carries a ramp payload")
        if any(b <= a for a, b in zip(self.thresholds, self.thresholds[1:])):
            # 昇順でない段はフロントのstep式が読めず、境界が1つ先の帯へ吸われる。
            raise ValueError(f"display '{self.label}' thresholds are not ascending: {self.thresholds}")
        return self


class AxisSpec(StrictModel):
    """二次軸の宣言。`inputs`は参照する一次属性の`attr_id`リストで、`register_axis`が
    登録済みであること・他の軸と重ならないことを検証する。"""

    axis_id: str
    inputs: list[str]


class AxisInputConflictError(ValueError):
    """新規登録しようとした軸の入力一次属性が、既存の別軸と重複している場合に送出する。"""

    def __init__(self, new_axis_id: str, existing_axis_id: str, overlapping_attrs: set[str]) -> None:
        self.new_axis_id = new_axis_id
        self.existing_axis_id = existing_axis_id
        self.overlapping_attrs = overlapping_attrs
        attrs = ", ".join(sorted(overlapping_attrs))
        super().__init__(
            f"axis '{new_axis_id}' shares input(s) [{attrs}] with already-registered "
            f"axis '{existing_axis_id}'; each primary attribute may belong to at most one axis "
            f"(exclusive assignment principle)"
        )


_PRIMARY_ATTRIBUTES: dict[str, PrimaryAttributeSpec] = {}
_AXES: dict[str, AxisSpec] = {}


def register_primary_attribute(spec: PrimaryAttributeSpec) -> None:
    if spec.attr_id in _PRIMARY_ATTRIBUTES:
        raise ValueError(f"primary attribute already registered: {spec.attr_id}")
    _PRIMARY_ATTRIBUTES[spec.attr_id] = spec


def register_axis(spec: AxisSpec) -> None:
    """二次軸を登録する。

    `inputs`に未登録の一次属性が含まれる場合、または一次属性が既存の別軸とかぶる場合は
    エラーを送出し、登録は行わない（部分登録によるレジストリの不整合を防ぐ）。
    """
    unknown = [attr_id for attr_id in spec.inputs if attr_id not in _PRIMARY_ATTRIBUTES]
    if unknown:
        raise ValueError(f"axis '{spec.axis_id}' references unregistered primary attribute(s): {unknown}")

    if spec.axis_id in _AXES:
        raise ValueError(f"axis already registered: {spec.axis_id}")

    new_inputs = set(spec.inputs)
    for existing in _AXES.values():
        overlap = new_inputs & set(existing.inputs)
        if overlap:
            raise AxisInputConflictError(spec.axis_id, existing.axis_id, overlap)

    _AXES[spec.axis_id] = spec


def all_primary_attributes() -> list[PrimaryAttributeSpec]:
    return list(_PRIMARY_ATTRIBUTES.values())


def all_axes() -> list[AxisSpec]:
    return list(_AXES.values())


def reset_registry_for_testing() -> None:
    """テスト用: グローバルなレジストリ状態を空に戻す。本体コードからは呼ばない。"""
    _PRIMARY_ATTRIBUTES.clear()
    _AXES.clear()
