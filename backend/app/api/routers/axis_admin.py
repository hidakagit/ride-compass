"""評価軸定義のCRUD管理API（改善計画T221 Stage D、ADR: docs/decisions/t221-axis-registry.md）。

`domain/axis_definitions.py: AXIS_DEFINITIONS`をDBの内容と同期させる書き込み口。
ルート生成の振る舞いを直接変えられるため、他のエンドポイントと異なり認可を要求する
（require_axis_admin_token、api/dependencies.py参照）。GUI編集画面（Stage E）は
本APIの上に構築する想定でスコープ外。
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_axis_registry_admin_service
from app.config import settings
from app.domain.axis_definitions import AxisDefinition, AxisShape
from app.services.axis_registry_service import AxisRegistryAdminService

router = APIRouter(prefix="/api/admin/axis-definitions", tags=["axis-admin"])


async def require_axis_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """管理APIの認可境界（改善計画T221 Stage D）。

    現状は共有トークンheader（環境変数`AXIS_ADMIN_TOKEN`、settings.axis_admin_token）による
    簡易な保護のみ。他のバックエンドAPIには認証機構が一切無いが、本APIだけは書き込みで
    ルート生成の振る舞いを直接変えられるため保護する（2026-08-24ユーザー判断）。
    将来、研究モードを一般ユーザーから隠し何らかの権限制御を導入する計画（ユーザー、
    2026-08-24）があるため、認可判定をこの1関数（FastAPI Dependency）へ集約しておく——
    実権限チェックへ差し替える際はこの関数の中身だけを変えればよい。
    axis_admin_token未設定（既定""）の環境では常に拒否し、うっかり無保護公開しない。
    """
    if not settings.axis_admin_token or x_admin_token != settings.axis_admin_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理APIへのアクセスが許可されていません")


class AxisDefinitionPayload(BaseModel):
    """作成・更新リクエストボディ。妥当性検証は型・範囲チェックのみ

    （極端な重み設定に対する意味的な歯止めは設けない、2026-08-24ユーザー判断。
    default_weightの非負制約はRoutePreferenceWeights（routers/routes.py）と同じ）。
    """

    axis_id: str
    shape: AxisShape
    default_weight: float = Field(ge=0)


class AxisDefinitionResponse(AxisDefinitionPayload):
    pass


def _to_response(definition: AxisDefinition) -> AxisDefinitionResponse:
    return AxisDefinitionResponse(axis_id=definition.axis_id, shape=definition.shape, default_weight=definition.default_weight)


@router.get("", dependencies=[Depends(require_axis_admin_token)])
async def list_axis_definitions(
    service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service),
) -> list[AxisDefinitionResponse]:
    definitions = await service.list_all()
    return [_to_response(definition) for definition in definitions.values()]


@router.get("/{axis_id}", dependencies=[Depends(require_axis_admin_token)])
async def get_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    definition = await service.get(axis_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません")
    return _to_response(definition)


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_axis_admin_token)])
async def create_axis_definition(
    payload: AxisDefinitionPayload, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    definition = AxisDefinition(axis_id=payload.axis_id, shape=payload.shape, default_weight=payload.default_weight)
    try:
        await service.create(definition)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_response(definition)


@router.put("/{axis_id}", dependencies=[Depends(require_axis_admin_token)])
async def update_axis_definition(
    axis_id: str,
    payload: AxisDefinitionPayload,
    service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service),
) -> AxisDefinitionResponse:
    if payload.axis_id != axis_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="axis_idはURLとボディで一致させてください"
        )
    definition = AxisDefinition(axis_id=axis_id, shape=payload.shape, default_weight=payload.default_weight)
    try:
        await service.update(axis_id, definition)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません") from exc
    return _to_response(definition)


@router.delete("/{axis_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_axis_admin_token)])
async def delete_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> None:
    try:
        await service.delete(axis_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
