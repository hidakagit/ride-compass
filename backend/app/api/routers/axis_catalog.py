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
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisCategory, AxisDefinition
from app.domain.axis_display import axis_display_for
from app.domain.material_catalog import MATERIAL_CATALOG
from app.domain.registry import AxisDisplaySpec

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
    proxy_hint: str | None
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


class AxisCatalogResponse(BaseModel):
    axes: list[AxisCatalogEntry]


def _primary_attribute_ids_for(definition: AxisDefinition) -> list[str]:
    """軸が参照する材料を一次属性idへ解決する。`AxisDefinition.materials`は材料idだけで
    なく他の軸id（改善計画T292の階層構造、例: car_stressの内部軸6つ）も返しうるため、
    材料id側で見つからないエントリはAXIS_DEFINITIONSの軸として再帰的に解決する
    （内部軸自体も内部軸を参照しうる想定はないが、循環参照は軸スタジオ側で拒否済み
    [test_create_rejects_direct_cycle_between_two_axes]のため`visited`で安全側に保護する）。
    """
    seen: dict[str, None] = {}
    visited: set[str] = set()

    def resolve(current: AxisDefinition) -> None:
        if current.axis_id in visited:
            return
        visited.add(current.axis_id)
        for material_id in current.materials:
            spec = MATERIAL_CATALOG.get(material_id)
            if spec is not None:
                if spec.primary_attribute_id is not None:
                    seen.setdefault(spec.primary_attribute_id, None)
                continue
            referenced_axis = AXIS_DEFINITIONS.get(material_id)
            if referenced_axis is not None:
                resolve(referenced_axis)

    resolve(definition)
    return list(seen)


@router.get("/api/axis-catalog", response_model=AxisCatalogResponse)
async def get_axis_catalog() -> AxisCatalogResponse:
    # AXIS_DEFINITIONSは常に最新（起動時＋管理API書き込み直後にin-place更新済み、
    # services/axis_registry_service.py参照）のため、DBへは触れずプロセス内の値を
    # そのまま返す（評価ホットパスと同じ同期アクセス方式）。axis_display_for()・
    # _primary_attribute_ids_for()も同様にプロセス内メモリだけを見る純粋関数のため、
    # リクエスト毎に呼んでもコストは無視できる。
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
                proxy_hint=definition.proxy_hint,
                primary_attribute_ids=_primary_attribute_ids_for(definition),
            )
            for definition in AXIS_DEFINITIONS.values()
            if definition.is_published
        ]
    )
