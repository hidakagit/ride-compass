"""材料カタログの公開読み取りAPI（改善計画T277）。

軸スタジオ（`/admin`、`components/AxisStudio/AxisComposer.tsx`）が材料選択の候補一覧を
取得するための読み取り専用・認可不要のエンドポイント。材料自体の追加・編集・削除は
GUIから行わない（`domain/material_catalog.py`へのコード変更＋デプロイのみ、ユーザー方針）。

`tile_property`/`tile_property_inverted`（地図レイヤーのramp自動生成が内部で使う想定、
T278）は公開レスポンスに含めない——フロントの軸コンポーザーが必要とするのは
`material_id`/`label`/`description`/`dtype`のみのため（`description`は改善計画T345で追加、
軸コンポーザーの情報アイコンから表示する説明文）。

改善計画T338: `MaterialSpec.display_only=True`の材料（現状designationのみ）は
このレスポンスから除外する（`axis_studio_materials()`）。地図表示専用の材料で、
軸スタジオで評価軸材料として選ぶと構造的なAND条件（"both"）を素朴なCategoricalShapeが
正しく表現できず誤解を招くため。地図表示（`tile_property`経由）には影響しない。

改善計画T340: `GET /api/material-catalog/{material_id}/values`（同じく認可不要・
読み取り専用）を追加した。highway/surface/smoothnessはOSMタグの生値でオープンエンドな
ため、`AxisComposer.tsx`の値入力欄が「タグ生値を暗記して手入力する」というUX課題を
抱えていた（2026-08-26ユーザー報告）。DBに実際に取り込まれている値を動的取得し返す。
DB未接続構成（`road_graph_use_repository=False`）では空リストを返し、呼び出し側
（フロント）が自由テキスト入力へフォールバックする。

改善計画T345フォローアップ: 当初（T340）はラベル付与を「UI語彙のカタログ集約」原則に
従いfrontend側（`lib/materialValueLabels.ts`、地図の絞り込みUIのグルーピングを流用）で
行っていたが、地図表示用のグルーピングは意図的に多対一（例: motorway/trunk/primary等
複数値が同じ「幹線道路」）なため、軸スタジオの候補一覧で同じラベルが並び見分けが
付かなくなる実害が判明した。「地図表示と評価は別」という方針のもと、値の意味は
材料そのものの定義に属するドメイン知識と位置づけ直し、`MaterialSpec.value_labels`
（`domain/material_catalog.py`、材料定義自体の一部）へ一元化した。本APIのレスポンスに
`label`を含めることで、frontendは受け取った値をそのまま表示するだけでよくなる
（frontend側の対訳表は撤去済み）。

改善計画T345さらなるフォローアップ2: `values.label`（`MaterialSpec.value_label`）・
`materials.label`（`MaterialSpec.full_label`）ともに「論理名 - 物理名」形式
（例: 材料"道路種別 - highway"、値"自転車専用道 - cycleway"）で返す。論理名だけでは
どのOSMタグ値に対応するか分からない・軸定義（`AxisDefinitionResponse`）や外部ドキュメント
上で物理名を探す必要がある、というユーザー要望への対応。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_region_service
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialDType, axis_studio_materials, is_known_material
from app.services.region_service import RegionService

router = APIRouter()


class MaterialCatalogEntry(BaseModel):
    material_id: str
    # 改善計画T345さらなるフォローアップ2: 「論理名 - 物理名」形式（MaterialSpec.full_label、
    # 例: "道路種別 - highway"）。論理名だけでは物理名(material_id)が分からないという
    # ユーザー要望への対応。
    label: str
    # 改善計画T345: 軸スタジオの材料選択で、labelだけでは何を表す材料か分かりにくいという
    # ユーザーフィードバックへの対応。情報アイコン(ⓘ)から表示する説明文。
    description: str
    dtype: MaterialDType


class MaterialCatalogResponse(BaseModel):
    materials: list[MaterialCatalogEntry]


class MaterialValueEntry(BaseModel):
    value: str
    # 改善計画T345フォローアップ: 「論理名 - 物理名」形式（例: "自転車専用道 - cycleway"）。
    # ラベル対訳表に無い値はvalueと同じ文字列（MaterialSpec.value_labelのフォールバック、
    # 新しいOSMタグ値がDBに現れてもAPIが失敗しないようにするため。この場合論理名が無い
    # ため" - "は付かない）。
    label: str


class MaterialValuesResponse(BaseModel):
    values: list[MaterialValueEntry]


@router.get("/api/material-catalog", response_model=MaterialCatalogResponse)
async def get_material_catalog() -> MaterialCatalogResponse:
    return MaterialCatalogResponse(
        materials=[
            MaterialCatalogEntry(
                material_id=m.material_id, label=m.full_label(), description=m.description, dtype=m.dtype
            )
            for m in axis_studio_materials()
        ]
    )


@router.get("/api/material-catalog/{material_id}/values", response_model=MaterialValuesResponse)
async def get_material_values(
    material_id: str,
    region_service: RegionService = Depends(get_region_service),
) -> MaterialValuesResponse:
    """改善計画T340: 材料idに対応する実データの値一覧（ソート済み、重複無し）を返す。
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
