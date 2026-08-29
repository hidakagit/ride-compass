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
（`domain/traffic.py`/当時の`domain/safety.py`〔T148で削除〕参照、T130で意図的に共有）の
ため、この3つはまだここへ登録しない（T138〜T139で軸自体を再編したうえで登録する）。
それ以外の既存軸（勾配・風・路面・停止密度・交差点密度・事故密度）はここに登録済み。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PrimaryAttributeSpec(BaseModel):
    """一次属性の宣言。

    `label`は一次属性のユーザー向け正式名称（改善計画: 地図レイヤー階層の次数反転）。
    地図チップ・サイドバー・研究タブが表示する「観測データ」側の名称の単一ソースで、
    `export_openapi.py`がaxis-catalog.jsonの`primary_attributes[]`へ書き出し、フロントは
    ここから略名（4文字以下、地図チップ用）への対応表だけを別途持つ（片側import、
    設計原則2）。

    死コード監査（過去の監査）で`ingest_fn`（モジュールパス文字列、`importlib`未使用で誰も
    解決していなかった）・`source`/`geometry`/`dtype`/`update_cadence`/`description`
    （唯一の消費者`export_openapi.py`が`attr_id`/`label`/`shared`の3つしか書き出しておらず、
    宣言されているだけで実際には誰にも消費されていなかった）を削除した。これらは
    `domain/registry.py`docstringの「排他制約はレジストリ登録時に機械的にチェックする」
    という設計方針の核とは無関係な、記録用メタデータのつもりで持っていたフィールドだった。
    """

    attr_id: str
    label: str
    shared: bool = False


class TileInputSpec(BaseModel):
    """地図表示（ramp）が読むMVTタイルプロパティ（改善計画T145b・T278・T292）。

    数値材料（既定）: `display_value = Σ(property × weight)`をフロントのMapLibre
    expressionが計算する。
    真偽値材料（`boolean=True`、改善計画T278）: MVTの真偽値プロパティは
    `["==",["get",property],true]`のような真偽比較で読む必要があり数値の重み付け結合が
    成立しないため、`true_value`/`false_value`（`weight`は無視）で寄与値を直接指定する。
    `invert`は材料がタイルプロパティの否定（例: no_lit⟵lit）の場合に立てる。

    `has_unknown_fallback`（レビュー指摘の修正、改善計画T278）: タイルプロパティが
    欠損している場合の意味が「true/falseどちらでもない不明」（例: surface_good、
    未分類の路面。`domain/road.py: classify_osm_surface`が3値[良/不明/悪]に分類する
    うちの「不明」に対応）であればTrueにする。既定Falseは「欠損=falseとみなしてよい
    真偽値材料」（例: no_lit⟵lit、has_tunnel⟵tunnel。タグ不在は「無し」の安全側既定と
    元々の軸定義でそう決めている）を表し、フロントは通常どおり`true_value`/
    `false_value`で色分けする。Trueの場合、フロントは欠損時に灰色「不明」表示へ切り替え、
    trueValue/falseValueどちらのスコアにも倒さない（`domain/axis_templates.py:
    evaluate_categorical`が欠損値をNone/NaN[difficulty不明]として扱うのと整合させる）。

    N値文字列材料（`categories`、改善計画T292）: `domain/axis_definitions.py:
    CategoricalShape`のmappingがbool2値ではなくstr3値以上（highway/surface等）の
    場合に使う。タイルプロパティの文字列値を`categories`辞書で引いた点数を寄与値とする
    （`weight`と併用可、寄与値=`categories[value] * weight`）。`has_unknown_fallback=False`
    （既定）の場合、未登録値は0扱い（寄与なし。値の種類は多いが取りうる値のごく一部だけを
    圧迫感等の点数に反映すれば足りる材料向け、例: `designation`は評価側のmappingが
    全既知値をカバーしており「未登録＝存在しない値」しか起こらない）。
    `has_unknown_fallback=True`（改善計画T297で修正）の場合、未登録値は0扱いではなく
    「不明」（灰色）へ倒す。これは`CategoricalShape`の評価側の実際の意味論（`domain/
    axis_templates.py: evaluate_categorical`は未登録値に`mapping.get(value, None)`で
    Noneを返し、`required=True`の材料でNoneは軸全体を評価不能にする——「未登録値=寄与0
    [最良側]」ではなく「未登録値=評価不能」）に合わせるため。典型例: `highway`
    （`car_stress_highway_base`。footway/path等、highway基準値が定義されていない道路種別は
    評価側でcar_stress軸全体を評価しない[required=True]。以前はフロント側の実装が
    プロパティの**欠損**のみを「不明」判定していたため、この「値はあるが未登録」の
    ケースを見落とし、実際には未評価のはずの区間が0点=最良[緑]色で表示される
    不整合があった。`axisLayers.ts: buildAxisRampUnknownExpression`参照）。
    boolean材料の`has_unknown_fallback=True`はタイルプロパティが完全に欠損している
    場合のみを「不明」とする（真偽値には「未登録の値」という状態自体が存在しないため）。

    自己変換材料（`breakpoints`、改善計画T292）: 材料自身が
    `BreakpointLinearShape.breakpoints`（区分線形）で変換される軸（例:
    `car_stress_maxspeed_adjustment`）の寄与値を、フロントの`interpolate`
    expressionでタイルプロパティの生値から直接求める場合に使う（`weight`と併用可）。

    `needs_runtime_scale`（改善計画T404）: この材料のタイル生値が実行時にしか決まらない
    係数でのスケール変換を要する場合True（`domain/material_catalog.py: MaterialSpec.
    tile_property_needs_runtime_scale`が立っている材料、例: `accident_count_per_km_year`
    ——収録年数[DBの`accident_import_runs`から実行時に取得、増え続ける]で正規化する前の
    生値がタイルに焼き込まれている）。`derive_ramp_inputs`（axis_display.py）は
    このフラグが立つ材料も自動導出の対象に含める（以前はこのフラグを持つ材料を含む軸を
    一律`None`[自動導出不可]としていたが、`weight`が「タイル生値→材料スケール」の
    静的な変換係数を表現できないだけで、`GET /api/axis-catalog`が実行時に取得した
    スケール定数[`material_runtime_scales`]をフロントのJS式が追加で掛け合わせれば
    正しく解決できるため、T404でこの制約を緩和した）。`thresholds`は元々
    `AxisDefinition.shape.breakpoints`由来の「材料スケール」の値のため、この
    フラグを持たない他のtile_inputと同じ意味のまま扱ってよい（フロント側だけが
    このフラグを見てtile生値に追加のスケール定数を掛ける）。
    """

    property: str
    weight: float = 1.0
    boolean: bool = False
    invert: bool = False
    true_value: float = 0.0
    false_value: float = 0.0
    has_unknown_fallback: bool = False
    categories: dict[str, float] | None = None
    breakpoints: list[tuple[float, float]] | None = None
    needs_runtime_scale: bool = False

    @field_validator("categories")
    @classmethod
    def _sort_categories(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        # 改善計画T333: このフィールドの値は情報源によって挿入順が非決定になりうる
        # （手書きのPython dictリテラル[AXIS_DEFINITIONS.display_override等]は決定的だが、
        # DBのdisplay_override[JSONB列]へ一度でも往復するとPostgreSQLのjsonb内部順
        # [キー長→バイト順]へ変わり両者は一致しない）。ここは表示専用（frontendの色分け
        # 表示にしか使わない）のため、モデル構築のたびにキーをソートして経路によらず
        # 決定的な順序へ正規化する。TileInputSpecはPydanticモデルのためこのvalidatorが
        # 構築元（コード内リテラル・DB読み込み・APIリクエストボディ）を問わず一律に効く。
        if value is None:
            return None
        return dict(sorted(value.items()))


class AxisDisplaySpec(BaseModel):
    """二次軸の地図レイヤー表示宣言（改善計画T145b「事実はタイルに、解釈はクライアントに」）。

    - kind="ramp": タイルへ焼き込み済みの事実プロパティ（`tile_inputs`の線形結合）を
      `thresholds`（昇順、色段階の境界値）で色分けする汎用レイヤーを、フロントの
      レイヤーファクトリが自動生成する。新しい軸はこれを宣言するだけで地図に現れる。
    - kind="none": 専用の二次レイヤーを持たない（既存レイヤーで代替、またはデータ未整備）。
      `note`へ理由を書く。

    改善計画T298: 以前は「タグの複雑な組み合わせを要しフロント側の手書きexpressionが
    必要な軸」向けのkind="bespoke"（例: 旧`carStressExpression.ts`）もあったが、
    改善計画T292でcar_stressが最後の利用者としてkind="ramp"へ移行し利用がゼロになった
    ため削除した（Literalから外すだけで、既存データ・呼び出し元への影響は無いことを
    grep（`kind="bespoke"`の構築箇所ゼロ）で確認済み）。
    """

    kind: Literal["ramp", "none"]
    label: str
    category: str = "trafficSafety"
    tile_inputs: list[TileInputSpec] = Field(default_factory=list)
    thresholds: list[float] = Field(default_factory=list)
    unit: str = ""
    note: str = ""


class AxisSpec(BaseModel):
    """二次軸の宣言。`inputs`は参照する一次属性の`attr_id`リスト（`register_axis`が
    登録済みの一次属性であることを検証する）。`display`は地図レイヤー表示の宣言
    （改善計画T145b、未指定は「表示宣言なし」でkind="none"相当）。

    改善計画T320: `transform_fn`（実際には動的解決されないドキュメント目的の文字列）・
    `output_range`（全軸で常に(0.0, 100.0)固定、呼び出し元は`export_openapi.py`のみで
    しかも読んでいなかった）・`description`（開発者向けの長い技術説明のつもりだったが
    axis-catalog.json生成時に一度も参照されていなかった）は、いずれもモデルへ必須
    フィールドとして残っているだけで実際には誰にも消費されていなかった（`_register_axes`
    [domain/registry_defaults.py]がAXIS_DEFINITIONSの軸ごとに手書きしていた分の名残）。
    フィールド自体を削除した。"""

    axis_id: str
    inputs: list[str]
    display: AxisDisplaySpec | None = None


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


def all_primary_attributes() -> list[PrimaryAttributeSpec]:
    return list(_PRIMARY_ATTRIBUTES.values())


def all_axes() -> list[AxisSpec]:
    return list(_AXES.values())


def reset_registry_for_testing() -> None:
    """テスト用: グローバルなレジストリ状態を空に戻す。本体コードからは呼ばない。"""
    _PRIMARY_ATTRIBUTES.clear()
    _AXES.clear()
