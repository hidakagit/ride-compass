"""較正値の管理API（`domain/tuning.py`の宣言を読み、上書きを書く）。

走行モデルの振る舞いを直接変えられるため、軸スタジオと同じ認可境界の内側に置く
（`require_admin_basic_auth`）。

**画面が並べる項目はこのAPIが宣言から導く**。較正値を1つ足しても、ここと画面の両方へ
書き足す場所は無い（`TUNING_PARAMETERS`に載っているものだけを返す——較正値ではない固定値は
`FIXED_VALUES`の側にあり、物理定数を出すと模型を壊せ、資源の上限を出すと本番を止められる）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_tuning_session
from app.domain.strict_model import StrictModel
from app.domain.tuning import (
    TUNING_PARAMETERS,
    TUNING_PARAMETERS_BY_ID,
    TuningEffect,
    tuning_value,
)
from app.infrastructure.tuning_overrides import TuningOverrideError
from app.services.tuning_service import overridden_parameter_ids, save_override

router = APIRouter(prefix="/api/admin/tuning", tags=["tuning-admin"])


class TuningParameterView(StrictModel):
    """較正値1件の宣言と、いま効いている値。"""

    id: str
    label: str
    unit: str
    description: str
    default: float
    minimum: float
    maximum: float
    #: 変えたとき効くまでに何が要るか（`TuningEffect`の値）。画面はこれでまとめる。
    effect: str
    #: 上と同じことを利用者へ見せる言い方（`TuningEffect.title`）。**画面へ対応表を
    #: 持たせない**——効き方を足したときに画面が知らず、名前の無いまとまりへ落ちる。
    effect_title: str
    value: float
    #: 既定から動かしてあるか。画面が「既定へ戻す」を出すかの判断に使う。
    overridden: bool


class TuningUpdateRequest(StrictModel):
    """1件の上書き。`value`を省略すると既定へ戻す。"""

    value: float | None = Field(default=None)


def _view(param_id: str, overridden_ids: set[str]) -> TuningParameterView:
    parameter = TUNING_PARAMETERS_BY_ID[param_id]
    return TuningParameterView(
        id=parameter.id,
        label=parameter.label,
        unit=parameter.unit,
        description=parameter.description,
        default=parameter.default,
        minimum=parameter.minimum,
        maximum=parameter.maximum,
        effect=parameter.effect.value,
        effect_title=parameter.effect.title,
        value=tuning_value(parameter.id),
        overridden=parameter.id in overridden_ids,
    )


@router.get("", response_model=list[TuningParameterView])
async def list_tuning_parameters(
    session: AsyncSession = Depends(get_tuning_session),
    _: None = Depends(require_admin_basic_auth),
) -> list[TuningParameterView]:
    overridden = await overridden_parameter_ids(session)
    # **効き方の順に並べて返す**（`TuningEffect`の宣言順）。画面はこの順のまま
    # まとめるだけで、並び順の知識を持たない。同じ効き方の中は宣言順のまま。
    effects = list(TuningEffect)
    ordered = sorted(TUNING_PARAMETERS, key=lambda p: effects.index(p.effect))
    return [_view(p.id, overridden) for p in ordered]


@router.put("/{param_id}", response_model=TuningParameterView)
async def update_tuning_parameter(
    param_id: str,
    request: TuningUpdateRequest,
    session: AsyncSession = Depends(get_tuning_session),
    _: None = Depends(require_admin_basic_auth),
) -> TuningParameterView:
    parameter = TUNING_PARAMETERS_BY_ID.get(param_id)
    if parameter is None:
        # 較正値の宣言に無いidは書かせない（較正値ではない固定値はこの逆引きに載らない）。
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"較正値がありません: {param_id}")
    try:
        await save_override(session, param_id, request.value)
    except TuningOverrideError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _view(param_id, await overridden_parameter_ids(session))
