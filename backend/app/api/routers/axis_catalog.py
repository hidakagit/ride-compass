"""軸カタログの公開読み取りAPI（改善計画T269、T308で地図表示宣言を追加）。

一般向けルート設定画面（RouteSettingsPanel）・研究モードのフロントが、評価軸の一覧
（label/description/category/default_weight）を取得するための読み取り専用・認可不要の
エンドポイント。書き込みは`api/routers/axis_admin.py`（認可必須）が担う。

軸スタジオ（T270）が管理API経由でDBへ書き込んだ軸も、`AXIS_DEFINITIONS`のpush型更新
（services/axis_registry_service.py）により、コード変更・再デプロイなしにここへ反映される
（改善計画T269完了条件）。ビルド時静的生成物`frontend/src/types/generated/axis-catalog.json`
（`export_openapi.py`が`domain/registry.py`から書き出す、地図レイヤー専用の別カタログ）とは
別物——あちらはStage DでDB化されていないため、GUIで作った軸を表現できない。

**公開済み軸のみを返す（改善計画T271）**: `is_published=False`（下書き）の軸は
一般ユーザーの目に触れさせない（下書き軸が一般UIに漏れると、まだ検証・命名が
固まっていない軸を一般ユーザーが選んでしまい、その後の破壊的変更・削除ができなく
なる——公開の意味が失われる）。下書き軸の一覧・編集は認可必須の
`GET /api/admin/axis-definitions`（軸スタジオ）側で行う。

**`display`フィールド（改善計画T308）**: `domain/axis_display.py: axis_display_for()`
（プロセス内メモリのみを見る純粋関数、DB/IO無し）を軸ごとに呼んで含める。これにより、
軸スタジオでの公開操作（is_publishedの切替）が、地図レイヤーのramp表示へ**再デプロイ
なしに即座に**反映される（従来はビルド時静的生成物`axis-catalog.json`
——`domain/registry.py`のレジストリ由来で、GUI作成軸を走査する経路自体が無かった——
にしか地図表示情報が無く、GUI作成軸は技術的にramp化可能な材料構成であっても地図に
一切現れなかった。docs/decisions/t308-axis-map-display-auto-derivation.md参照）。

**`material_runtime_scales`（改善計画T404）**: `derive_ramp_inputs`は実行時にしか
決まらないスケール変換が必要な材料（`tile_property_needs_runtime_scale=True`、例:
`accident_count_per_km_year`）も自動導出の対象に含めるようになったが、その変換係数
（収録年数の逆数）自体は`domain/axis_display.py`のような純粋関数では計算できないため
（DBアクセスが要る）、本エンドポイントがリクエスト毎に1回だけ`RegionService`経由で
解決しレスポンスへ含める。フロントのJS式ビルダーがこれを取得しタイル生値に掛け合わせる
（docs/tasks/T404.md参照）。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_region_service
from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisCategory, AxisShape
from app.domain.axis_display import axis_display_for, primary_attribute_ids_for
from app.domain.registry import AxisDisplaySpec
from app.services.region_service import RegionService

router = APIRouter()


class AxisCatalogEntry(BaseModel):
    axis_id: str
    label: str
    description: str
    category: AxisCategory
    default_weight: float
    display: AxisDisplaySpec
    # 改善計画T310: 地図チップ表示要素（既存軸だけ特別扱いしていたSECONDARY_AXIS_ICONS等の
    # 軸id→値の手書き辞書を廃止し、軸自身のデータ[domain/axis_definitions.py:
    # AxisDefinition]として持たせたもの）。全てNone可（未設定はフロント側の汎用
    # フォールバックに委ねる）。
    icon_id: str | None
    chip_label: str | None
    panel_hint: str | None
    # 改善計画T318: falseなら地図上チップ・地図の見え方パネルの両方からこの軸を丸ごと
    # 除外する（domain/axis_definitions.py: AxisDefinition.show_map_iconのdocstring参照）。
    show_map_icon: bool
    # 改善計画T352: この軸のdifficultyを、ルート地図の色分けモード（frontend
    # routeStyleModes.ts）の選択肢として動的に使えるかの宣言（domain/axis_definitions.py:
    # AxisDefinition.supports_route_coloringのdocstring参照）。
    supports_route_coloring: bool
    # 改善計画T308: この軸が参照する材料を、対応する一次属性id（domain/registry.py:
    # PrimaryAttributeSpec.attr_id、frontend側はprimaryAttributes.tsのキーと同じ名前空間）へ
    # 解決したもの（重複除去、対応が無い材料[動的気象・未登録一次属性]・他の軸を参照する
    # 材料[car_stress等の階層構造]は除く）。フロント側の「材料が同時表示中は太い下敷きで
    # 強調する」機能（axisMaterialLayerIds、page.tsx: secondaryAxisCasingLayerIds）・
    # 「軸の下に材料一覧を出す」機能（MapOverlayControls.tsx: renderMaterialsNote）が、
    # 軸スタジオの公開軸に対しても同じ仕組みで動くようにするため（以前はビルド時静的生成物
    # axis-catalog.jsonのregistry.py: AxisSpec.inputsをそのまま使っており、GUI作成軸を
    # 含まなかった）。
    primary_attribute_ids: list[str]
    # 改善計画T440: 「軸スタジオで決められること」（AxisDefinitionが実際に持つ未公開の
    # フィールド）を個別に選んでフィールド追加するのではなく、まとめて返す方針にした
    # （ユーザー指摘「axis-catalogは、軸スタジオで決められること全部返すほうがいい。
    # 連動されるためには」）。shapeはルート結果の色分け（frontend routeStyleModes.ts）が、
    # 「符号付き値を直接読むべきか（shape.kind==="breakpoint_linear" &&
    # shape.preprocess==="abs"）」「その場合どの材料id（≒RouteSegmentDetailのフィールド名）
    # を読むか（shape.terms[0].material）」を、axis_idのハードコード分岐ではなく軸データ
    # から導出するために必要（gradientの実データ: kind="breakpoint_linear"、
    # preprocess="abs"、terms=[{material:"gradient_percent"}]）。
    shape: AxisShape
    # 改善計画T352で新設済みのフィールドだが、今まで`display`（axis_display_for()が
    # kind="ramp"軸向けに導出した値、kind="none"の軸[gradient等]では常に空配列）経由でしか
    # 露出しておらず、生の上書き値を読み取れなかった。ルート結果の色分けのしきい値
    # （frontend routeStyleModes.ts: buildRangeSteppedMode）の唯一の正として使うため、
    # 生の値をそのまま返す。
    display_thresholds_override: list[float] | None
    # 改善計画T440 Part D: 「専用のway_id→値配信レイヤー（Redis経由、ルート未確定時から
    # 地図上で視界内の全道路を線色分け表示できる）を持つか」の宣言（domain/
    # axis_definitions.py: AxisDefinition.dedicated_way_value_layerのdocstring参照）。
    # RouteSettingsPanel.tsx（mapColorLayerIdFor）・mapLayers.ts（isAxisStudioLayer）が、
    # axis_idの文字列比較（wind/gradientのみ）ではなくこのフィールドで判定する。
    dedicated_way_value_layer: bool


class AxisCatalogResponse(BaseModel):
    axes: list[AxisCatalogEntry]
    # 改善計画T404: 実行時にしか決まらないスケール定数（`GET /api/axis-catalog`が
    # リクエスト毎に1回だけDBから解決する「たまにしか変わらないグローバル定数」）。
    # `tile_property_needs_runtime_scale=True`な材料（material_catalog.py参照）の
    # material_id→スケール係数（タイル生値に掛けると材料スケールへ変換できる倍率）。
    # フロントのJS式ビルダー（axisLayers.ts: buildAxisRampValueExpression）が
    # `TileInputSpec.needs_runtime_scale=True`なtile_inputに対してこの係数を追加で
    # 掛け合わせる。値が解決できない材料（現状はaccident_count_per_km_year、収録年数が
    # 0件のとき）はキー自体を含めない——フロント側はキーが無い場合、その材料の寄与を
    # 0として扱う（RegionService.get_accident_years_coveredのdocstring参照）。
    material_runtime_scales: dict[str, float] = {}


@router.get("/api/axis-catalog", response_model=AxisCatalogResponse)
async def get_axis_catalog(region_service: RegionService = Depends(get_region_service)) -> AxisCatalogResponse:
    # AXIS_DEFINITIONSは常に最新（起動時＋管理API書き込み直後にin-place更新済み、
    # services/axis_registry_service.py参照）のため、DBへは触れずプロセス内の値を
    # そのまま返す（評価ホットパスと同じ同期アクセス方式）。axis_display_for()・
    # primary_attribute_ids_for()も同様にプロセス内メモリだけを見る純粋関数のため、
    # リクエスト毎に呼んでもコストは無視できる。
    #
    # 改善計画T404: material_runtime_scalesだけが例外的にDB（accident_years_covered）を
    # 見る。現時点でtile_property_needs_runtime_scale=Trueな材料は
    # accident_count_per_km_year 1件のみのため、ここでは決め打ちで解決する
    # （将来2件目が増えたら、材料ごとのスケール源をどう解決するかも合わせて設計し
    # 直す必要がある——「material_idごとに任意のスケール源を宣言できる」汎用機構は
    # 現時点で利用者が1件しかいないため、過剰な抽象化を避けてYAGNI原則に従った）。
    material_runtime_scales: dict[str, float] = {}
    accident_years_covered = await region_service.get_accident_years_covered()
    if accident_years_covered > 0:
        material_runtime_scales["accident_count_per_km_year"] = 1 / accident_years_covered

    return AxisCatalogResponse(
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
                supports_route_coloring=definition.supports_route_coloring,
                primary_attribute_ids=primary_attribute_ids_for(definition),
                shape=definition.shape,
                display_thresholds_override=definition.display_thresholds_override,
                dedicated_way_value_layer=definition.dedicated_way_value_layer,
            )
            for definition in AXIS_DEFINITIONS.values()
            if definition.is_published
        ],
        material_runtime_scales=material_runtime_scales,
    )
