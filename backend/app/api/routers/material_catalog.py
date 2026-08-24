"""材料カタログの公開読み取りAPI（改善計画T277）。

軸スタジオ（`/admin`、`components/AxisStudio/AxisComposer.tsx`）が材料選択の候補一覧を
取得するための読み取り専用・認可不要のエンドポイント。材料自体の追加・編集・削除は
GUIから行わない（`domain/material_catalog.py`へのコード変更＋デプロイのみ、ユーザー方針）。

`tile_property`/`tile_property_inverted`（地図レイヤーのramp自動生成が内部で使う想定、
T278）は公開レスポンスに含めない——フロントの軸コンポーザーが必要とするのは
`material_id`/`label`/`dtype`のみのため。
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.domain.material_catalog import MaterialDType, all_materials

router = APIRouter()


class MaterialCatalogEntry(BaseModel):
    material_id: str
    label: str
    dtype: MaterialDType


class MaterialCatalogResponse(BaseModel):
    materials: list[MaterialCatalogEntry]


@router.get("/api/material-catalog", response_model=MaterialCatalogResponse)
async def get_material_catalog() -> MaterialCatalogResponse:
    return MaterialCatalogResponse(
        materials=[
            MaterialCatalogEntry(material_id=m.material_id, label=m.label, dtype=m.dtype)
            for m in all_materials()
        ]
    )
