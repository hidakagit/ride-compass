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

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisCategory
from app.domain.axis_display import axis_display_for
from app.domain.registry import AxisDisplaySpec

router = APIRouter()


class AxisCatalogEntry(BaseModel):
    axis_id: str
    label: str
    description: str
    category: AxisCategory
    default_weight: float
    display: AxisDisplaySpec


class AxisCatalogResponse(BaseModel):
    axes: list[AxisCatalogEntry]


@router.get("/api/axis-catalog", response_model=AxisCatalogResponse)
async def get_axis_catalog() -> AxisCatalogResponse:
    # AXIS_DEFINITIONSは常に最新（起動時＋管理API書き込み直後にin-place更新済み、
    # services/axis_registry_service.py参照）のため、DBへは触れずプロセス内の値を
    # そのまま返す（評価ホットパスと同じ同期アクセス方式）。axis_display_for()も同様に
    # プロセス内メモリだけを見る純粋関数のため、リクエスト毎に呼んでもコストは無視できる。
    return AxisCatalogResponse(
        axes=[
            AxisCatalogEntry(
                axis_id=definition.axis_id,
                label=definition.label,
                description=definition.description,
                category=definition.category,
                default_weight=definition.default_weight,
                display=axis_display_for(definition),
            )
            for definition in AXIS_DEFINITIONS.values()
            if definition.is_published
        ]
    )
