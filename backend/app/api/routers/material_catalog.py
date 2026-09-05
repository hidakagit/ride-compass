"""材料カタログの公開読み取りAPI。

軸スタジオ（`/admin`、`components/AxisStudio/AxisComposer.tsx`）が材料選択の候補一覧を
取得するための読み取り専用・認可不要のエンドポイント。材料自体の追加・編集・削除は
GUIから行わない（`domain/material_catalog.py`へのコード変更＋デプロイのみ）。

`tile_property`（地図レイヤーのramp自動生成が内部で使う想定）は公開レスポンスに
含めない——フロントの軸コンポーザーが必要とするのは`material_id`/`label`/`description`/
`dtype`/`reference_points`のみのため（`description`は軸コンポーザーの情報アイコンから
表示する説明文、`reference_points`は折れ点編集を助ける「値の目安」一覧）。

`MaterialSpec.display_only=True`の材料（designation）は`axis_studio_materials()`が
このレスポンスから除外する。構造的なAND条件（"both"）を素朴なCategoricalShapeが
正しく表現できず誤解を招くため。地図表示（`tile_property`経由）には影響しない。

`GET /api/material-catalog/{material_id}/values`（同じく認可不要・読み取り専用）は、
highway/surface/smoothnessのようなOSMタグの生値でオープンエンドな材料について、DBに
実際に取り込まれている値を動的取得し返す（`AxisComposer.tsx`の値入力欄がタグ生値を
暗記して手入力せずに選べるようにする）。DB未接続構成（`road_graph_use_repository=False`）
では空リストを返し、呼び出し側（フロント）が自由テキスト入力へフォールバックする。

`values.label`（`MaterialSpec.value_label`）は材料の値ごとの日本語ラベル対訳表
（`MaterialSpec.value_labels`、`domain/material_catalog.py`、材料定義自体の一部）を
そのまま返す。`values.label`・`materials.label`（`MaterialSpec.full_label`）ともに
「論理名 - 物理名」形式（例: 材料"道路種別 - highway"、値"自転車専用道 - cycleway"）で
返す——論理名だけではどのOSMタグ値に対応するか分からず、軸定義
（`AxisDefinitionResponse`）や外部ドキュメント上で物理名を探す必要があるため。

`GET /api/admin/material-catalog/coverage`（Basic認証必須）は、材料ごとの欠損割合
（元データ[タグ・派生テーブル行]が無いWay/Edgeの割合）を全材料ぶん返す管理画面向けの
集計API（`services/material_coverage_service.py`・`infrastructure/material_coverage.py`）。
上の2エンドポイントと異なり認可を要求する理由は`get_material_coverage`のdocstring参照。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_material_coverage_service, get_region_service
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialDType, axis_studio_materials, is_known_material
from app.infrastructure.material_coverage import MissingSemantics, Population
from app.services.material_coverage_service import MaterialCoverageService
from app.services.region_service import RegionService

router = APIRouter()


class MaterialReferencePointEntry(BaseModel):
    label: str
    value: float


class MaterialCatalogEntry(BaseModel):
    material_id: str
    # 「論理名 - 物理名」形式（MaterialSpec.full_label、例: "道路種別 - highway"）。
    # 論理名だけでは物理名(material_id)が分からないため併記する。
    label: str
    # 情報アイコン(ⓘ)から表示する説明文（labelだけでは何を表す材料か分かりにくいため）。
    description: str
    dtype: MaterialDType
    # 値の単位（MaterialSpec.unitが単一ソース、無次元・真偽値・カテゴリ値は空文字）。
    # 凡例・比較パネル等、数値を表示する箇所の単位表記の唯一の正（frontendは単位を持たない）。
    unit: str
    # 軸スタジオの折れ点編集を助ける「値の目安」一覧。値域が直感的でない材料（風等）
    # ほど有用なため、真偽値・categorical材料や単純な材料は空配列になりうる。
    reference_points: list[MaterialReferencePointEntry]


class MaterialCatalogResponse(BaseModel):
    materials: list[MaterialCatalogEntry]


class MaterialValueEntry(BaseModel):
    value: str
    # 「論理名 - 物理名」形式（例: "自転車専用道 - cycleway"）。ラベル対訳表に無い値は
    # valueと同じ文字列（MaterialSpec.value_labelのフォールバック、新しいOSMタグ値が
    # DBに現れてもAPIが失敗しないようにするため。この場合論理名が無いため" - "は付かない）。
    label: str


class MaterialValuesResponse(BaseModel):
    values: list[MaterialValueEntry]


class MaterialCoverageEntry(BaseModel):
    material_id: str
    label: str
    dtype: MaterialDType
    # 集計対象外の材料はpopulation/total/missing/missing_ratio/missing_semanticsがnullで、
    # excluded_reasonに理由を持つ。
    population: Population | None
    total: int | None
    missing: int | None
    # 0〜1（total=0の場合はnull）。
    missing_ratio: float | None
    # 欠損判定の根拠（どのテーブル・列・タグの不在を欠損とみなすか）。
    source: str
    # "unknown"=欠損は不明値として扱われ軸が評価対象外になる、"definite"=欠損は確定値
    # （タグ不在=非該当等）として扱われ軸は通常どおり評価される。
    missing_semantics: MissingSemantics | None
    excluded_reason: str | None


class MaterialCoverageResponse(BaseModel):
    computed_at: datetime
    way_total: int
    edge_total: int
    materials: list[MaterialCoverageEntry]


@router.get("/api/material-catalog", response_model=MaterialCatalogResponse)
async def get_material_catalog() -> MaterialCatalogResponse:
    return MaterialCatalogResponse(
        materials=[
            MaterialCatalogEntry(
                material_id=m.material_id,
                label=m.full_label(),
                description=m.description,
                dtype=m.dtype,
                unit=m.unit,
                reference_points=[
                    MaterialReferencePointEntry(label=p.label, value=p.value) for p in m.reference_points
                ],
            )
            for m in axis_studio_materials()
        ]
    )


@router.get("/api/material-catalog/{material_id}/values", response_model=MaterialValuesResponse)
async def get_material_values(
    material_id: str,
    region_service: RegionService = Depends(get_region_service),
) -> MaterialValuesResponse:
    """材料idに対応する実データの値一覧（ソート済み、重複無し）を返す。
    未知の材料idは404（フロントのタイプミス検知用）。既知だが動的値一覧に対応していない
    材料（`tracktype`等、事前に閉じた値集合を持つため本APIが不要）・DB未接続・DB障害は
    いずれも空リストを返す（`RegionService.get_material_values`のグレースフルデグレード
    方針、`infrastructure/road_graph_repository.py: _MATERIAL_VALUE_COLUMN_EXPR`参照）。
    """
    if not is_known_material(material_id):
        raise HTTPException(status_code=404, detail=f"unknown material '{material_id}'")
    values = await region_service.get_material_values(material_id)
    spec = MATERIAL_CATALOG[material_id]
    return MaterialValuesResponse(values=[MaterialValueEntry(value=v, label=spec.value_label(v)) for v in values])


@router.get(
    "/api/admin/material-catalog/coverage",
    response_model=MaterialCoverageResponse,
    dependencies=[Depends(require_admin_basic_auth)],
)
async def get_material_coverage(
    service: MaterialCoverageService = Depends(get_material_coverage_service),
) -> MaterialCoverageResponse:
    """全材料の欠損割合（`MATERIAL_CATALOG`の登録順、集計対象外の材料は理由付き）を返す。

    同じ材料カタログの読み取りAPIでも、上の2エンドポイントと異なりBasic認証を要求する:
    osm_raw_ways/road_edgesの全表走査を伴う重いクエリで、認可なしに公開すると
    繰り返し呼ばれるだけでDBを圧迫できてしまう（管理画面`/admin`からのみ使う想定）。
    DB例外は`axis_admin.py`と同じく503へ変換する（診断用APIのため空レポートへ倒さない）。
    """
    try:
        report = await service.get_material_coverage()
    except DBAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="材料の欠損割合の集計に失敗しました（DB接続・migration適用状況を確認してください）",
        ) from exc
    return MaterialCoverageResponse(
        computed_at=report.computed_at,
        way_total=report.way_total,
        edge_total=report.edge_total,
        materials=[
            MaterialCoverageEntry(
                material_id=entry.material_id,
                label=entry.label,
                dtype=entry.dtype,
                population=entry.population,
                total=entry.total,
                missing=entry.missing,
                missing_ratio=entry.missing_ratio,
                source=entry.source,
                missing_semantics=entry.missing_semantics,
                excluded_reason=entry.excluded_reason,
            )
            for entry in report.materials
        ],
    )
