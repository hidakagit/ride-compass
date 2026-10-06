"""軸カタログの公開読み取りAPI。

一般向けのルート設定画面が、評価軸の一覧
（label/description/category/default_weight）を取得するための読み取り専用・認可不要の
エンドポイント。書き込みは`api/routers/axis_admin.py`（認可必須）が担う。

軸スタジオが管理API経由でDBへ書き込んだ軸も、`AXIS_DEFINITIONS`のpush型更新
（services/axis_registry_service.py）により、コード変更・再デプロイなしにここへ反映される。
ビルド時の生成物は軸を持たない（`export_openapi.py`が`domain/registry.py`から書き出すのは
一次属性の語彙まで）ため、フロントが軸を知る経路はこのAPIだけ。

**公開済み軸のみを返す**: `is_published=False`（下書き）の軸は
一般ユーザーの目に触れさせない（下書き軸が一般UIに漏れると、まだ検証・命名が
固まっていない軸を一般ユーザーが選んでしまい、その後の破壊的変更・削除ができなく
なる——公開の意味が失われる）。下書き軸の一覧・編集は認可必須の
`GET /api/admin/axis-definitions`（軸スタジオ）側で行う。

**`display`フィールド**: `domain/axis_display.py: axis_display_for()`
（プロセス内メモリのみを見る純粋関数、DB/IO無し）を軸ごとに呼んで含める。これにより、
軸スタジオでの公開操作（is_publishedの切替）が、地図レイヤーのramp表示へ**再デプロイ
なしに即座に**反映される（docs/records/decisions/t308-axis-map-display-auto-derivation.md参照）。

**`tile_runtime_scales`**: 地図表示の導出は、タイルの生値を材料の値へ換算する係数が実行時に
しか決まらない材料（`MaterialSpec.tile_property_runtime_scale`）も対象に含めるが、係数の源
（事故の収録年）はDBにしか無いため、`domain/axis_display.py`の純粋関数では求められない。
本エンドポイントがリクエスト毎に1回だけ`services/axis_catalog_service.py`経由で収録年を読み、係数は
`domain/material_catalog.py: tile_runtime_scales`が材料の宣言から導く。フロントのJS式ビルダーが
これを取得しタイル生値に掛け合わせる。
"""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_region_service
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisCategory,
    AxisDefinition,
    primary_attribute_ids_for,
    weather_layer_groups_for,
)
from app.domain.material_catalog import MATERIAL_CATALOG, tile_runtime_scales
from app.domain.axis_display import axis_display_for, map_band_labels
from app.domain.axis_raw_value import (
    axis_material_shares,
    raw_value_total_unit,
    raw_value_unit,
)
from app.domain.dynamic_way_values import WayValueConditionName
from app.domain.map_paint import MapPaint, map_paint
from app.domain.registry import AxisDisplaySpec
from app.domain.tuning import client_tuning_values
from app.services.axis_catalog_service import axis_catalog_sources
from app.services.region_service import RegionService
from app.domain.strict_model import StrictModel

router = APIRouter()


def _material_breakdown(definition: AxisDefinition) -> list["AxisMaterialBreakdownEntry"]:
    """軸の内訳（材料まで分解した絶対量の並び）。カタログに無い材料は落とす。

    categorical材料（`highway`等）も含めて返す——値ごとの延長割合を運ぶ器はまだ無いが、
    内訳の並び自体は軸定義から決まるため、運搬側の都合で並びを変えると軸定義との
    対応が読めなくなる。値が来ない材料を
    フロントが飛ばす形にする。
    """
    entries = []
    for share in axis_material_shares(definition, AXIS_DEFINITIONS):
        spec = MATERIAL_CATALOG.get(share.material_id)
        if spec is None:
            continue
        entries.append(
            AxisMaterialBreakdownEntry(
                material_id=share.material_id,
                label=spec.label,
                dtype=spec.dtype,
                unit=spec.unit or "",
                share=round(share.share, 4),
                value_labels=dict(spec.value_labels) if spec.dtype == "categorical" else {},
            )
        )
    return entries


class AxisMaterialBreakdownEntry(StrictModel):
    """合成軸の内訳1件（材料と、その材料が軸の生値に占める割合）。"""

    material_id: str
    #: 材料の表示名（`MaterialSpec.label`）。フロントは対応表を持たない。
    label: str
    #: 値の型。`numeric`＝距離加重平均＋単位、`boolean`＝該当区間の延長割合。
    dtype: str
    #: numeric材料の単位。真偽値材料は空文字。
    unit: str
    #: 各階層で正規化した重みの積（0〜1）。並び順の根拠を画面側でも示せるよう返す。
    share: float
    #: categorical材料の「タグ生値→論理名」対訳（`MaterialSpec.value_labels`）。
    #: ルート結果は`material_category_shares`の値をこれで日本語にする。他の型では空。
    #: 軸スタジオが使う`value_label()`の「論理名 - 物理名」形式にしないのは、走行中に見る
    #: 画面へ物理名を並べても読み手の判断が増えないため。
    value_labels: dict[str, str] = {}


class AxisCatalogEntry(StrictModel):
    axis_id: str
    label: str
    description: str
    category: AxisCategory
    default_weight: float
    display: AxisDisplaySpec
    # 地図チップ表示要素（軸自身のデータ[domain/axis_definitions.py:
    # AxisDefinition]として持つ）。全てNone可（未設定はフロント側の汎用
    # フォールバックに委ねる）。
    icon_id: str | None
    chip_label: str | None
    panel_hint: str | None
    # falseなら地図上チップの一覧からこの軸を丸ごと除外する
    # （domain/axis_definitions.py: AxisDefinition.show_map_iconのdocstring参照）。
    show_map_icon: bool
    # この軸が参照する材料を、対応する一次属性id（domain/registry.py:
    # PrimaryAttributeSpec.attr_id。ビルド時の生成物が配る一次属性と同じ名前空間）へ
    # 解決したもの（重複除去、対応が無い材料[動的気象・未登録一次属性]・他の軸を参照する
    # 材料[階層構造]は除く）。軸と一次属性レイヤーの対応を、軸idで分岐せずに引けるよう
    # 軸スタジオの公開軸にも同じ形で配る。
    primary_attribute_ids: list[str]
    # この軸の材料の元データを描く気象のチップ（`domain/axis_definitions.py: weather_layer_groups_for`）。
    # 一次属性を持たない動的な材料（風等）は`primary_attribute_ids`に現れないため、こちらが運ぶ。
    weather_layer_groups: list[str]
    # 段階ごとの体感ラベルの上書き（domain/axis_definitions.py: AxisDefinition.
    # display_band_labels_override）を、地図の段で引き直したもの（domain/axis_display.py:
    # map_band_labels）。軸定義の生の値ではなく、件数は地図の段数
    # （`map_paint.thresholds`の件数+1）と一致する——上書きは人が刻んだ境界の段ごとに付くため、
    # 地図で落ちる境界があるとそのままでは件数が合わない。
    display_band_labels_override: list[str] | None
    # 「専用のフィーチャー→値配信レイヤー（ルート未確定時から
    # 地図上で視界内の全道路を線色分け表示できる）を持つか」の宣言（domain/
    # axis_definitions.py: AxisDefinition.dedicated_way_value_layerのdocstring参照）。
    # 受け取る側が、axis_idの文字列比較ではなくこのフィールドで地図レイヤー・取得の対象を決めるための宣言。
    dedicated_way_value_layer: bool
    # 地図がこの軸について塗る値・単位・段の境界・凡例の目盛り（domain/map_paint.py: map_paint）。
    # ルート確定前の塗り・ルート確定後のルート線色分け・凡例のどれもこれに従う。
    map_paint: MapPaint
    # 折れ点を通す前の生値の単位（`domain/axis_raw_value.py: raw_value_unit`）。
    # 定まらない軸はnull。ルート結果は得点の隣にこの単位で生値を出す。
    raw_value_unit: str | None
    # 生値へ走行距離を掛けた総量の単位（`domain/axis_raw_value.py: raw_value_total_unit`）。
    # **総量を出しても読み手の判断が変わらない軸はnull**（「約3322度曲がる」には比べる
    # 尺度が無い）。フロントは単位の綴りから総量の可否を判断しない。
    raw_value_total_unit: str | None
    # 生値の単位が定まらない軸の内訳（`domain/axis_raw_value.py: axis_material_shares`）。
    # 得点だけでは軸単体で経路を判断できないため、材料まで分解して較正に依存しない
    # 絶対の事実を出す。単位が定まる軸（`raw_value_unit`が非null）は分解せず空配列。
    # 並びは正規化重みの降順で、フロントは先頭から順に出す（並べ替えを持たない）。
    material_breakdown: list[AxisMaterialBreakdownEntry]
    # 専用way値配信（`GET /api/region/dynamic-way-values/{axis_id}`）へ地図がこの軸について
    # 載せるクエリパラメータの名前（`services/dedicated_way_values.py: dedicated_way_value_conditions`。
    # 配信サービスが受け取る条件の型から導く）。専用配信を持たない軸は空。受け取る側が
    # 「どの軸の取得に時刻・向き・想定速度を添えるか」を、axis_idで分岐せずここから決めるために配る。
    dynamic_way_value_conditions: list[WayValueConditionName]
    # 専用way値配信が、走行方位しだいで値の決まらない道（値がnull）を返しうるか
    # （`services/dedicated_way_values.py: dedicated_way_value_undetermined_by_bearing`）。trueの軸だけ、
    # 地図の凡例が「向きで決まらない」の行を持つ（返さない軸に出すと、どの道も入らない行になる）。
    dynamic_way_value_undetermined_by_bearing: bool


class AxisCatalogResponse(StrictModel):
    axes: list[AxisCatalogEntry]
    # タイルのプロパティ名→実行時にしか決まらない換算係数（タイル生値に掛けると材料の値になる倍率、
    # `domain/material_catalog.py: tile_runtime_scales`）。`TileInputSpec.needs_runtime_scale=True`な
    # tile_inputのタイル生値へ、受け取る側が`property`で引いて掛ける。
    tile_runtime_scales: dict[str, float] = {}
    # フロントが使う較正値（id → いま効いている値、`domain/tuning.py`が宣言）。管理画面から
    # 変えた値を**再デプロイなしに**画面へ届けるため、起動時に1回取るこのカタログへ相乗り
    # させる（ビルド時生成物のroute-generate-config.jsonが持つ既定値は、画面がidの型にだけ使い、値は読まない）。
    client_tuning: dict[str, float] = {}
    # 配信するタイルの世代（系統名 → `<派生の世代>.<生データの世代>-<形の署名>`、`services/
    # tile_version_service.py`）。フロントはこれをタイルURLのクエリへ入れてブラウザの
    # キャッシュを分ける。**ビルド時生成物では配れない**——バッチが中身を作り直しても
    # デプロイは起きないため、次のデプロイまで古い値を配り続ける。
    tile_versions: dict[str, str] = {}
    # 事故データの収録年（今の事故の数を数えた取込の宣言そのもの）。地図の説明文が範囲を書くために
    # 使う。**表示側に持たせない**——文字列で持つと取り込み直したときに黙って食い違う。
    accident_years: list[int] = []


@router.get("/api/axis-catalog", response_model=AxisCatalogResponse)
async def get_axis_catalog(region_service: RegionService = Depends(get_region_service)) -> AxisCatalogResponse:
    # AXIS_DEFINITIONSは常に最新（起動時＋管理API書き込み直後にin-place更新済み、
    # services/axis_registry_service.py参照）のため、DBへは触れずプロセス内の値を
    # そのまま返す（評価ホットパスと同じ同期アクセス方式）。axis_display_for()・
    # primary_attribute_ids_for()も同様にプロセス内メモリだけを見る純粋関数のため、
    # リクエスト毎に呼んでもコストは無視できる。事故の収録年と、それから導く換算係数・タイルの世代だけがDBを見る。
    published = [definition for definition in AXIS_DEFINITIONS.values() if definition.is_published]
    sources = await axis_catalog_sources(region_service, [definition.axis_id for definition in published])

    return AxisCatalogResponse(
        client_tuning=client_tuning_values(),
        accident_years=sources.accident_years,
        tile_versions=sources.tile_versions,
        axes=[
            AxisCatalogEntry(
                axis_id=definition.axis_id,
                label=definition.label,
                description=definition.description,
                category=definition.category,
                default_weight=definition.default_weight,
                display=axis_display_for(definition),
                icon_id=definition.icon_id,
                chip_label=definition.chip_label,
                panel_hint=definition.panel_hint,
                show_map_icon=definition.show_map_icon,
                primary_attribute_ids=primary_attribute_ids_for(definition),
                weather_layer_groups=weather_layer_groups_for(definition),
                display_band_labels_override=map_band_labels(definition),
                dedicated_way_value_layer=definition.dedicated_way_value_layer,
                map_paint=map_paint(definition),
                raw_value_unit=raw_value_unit(definition),
                raw_value_total_unit=raw_value_total_unit(definition),
                material_breakdown=_material_breakdown(definition),
                dynamic_way_value_conditions=sources.dynamic_way_value_conditions[definition.axis_id],
                dynamic_way_value_undetermined_by_bearing=(
                    sources.dynamic_way_value_undetermined_by_bearing[definition.axis_id]
                ),
            )
            for definition in published
        ],
        tile_runtime_scales=tile_runtime_scales(sources.accident_years),
    )
