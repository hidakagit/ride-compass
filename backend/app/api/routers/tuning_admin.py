"""較正値の管理API（`domain/tuning.py`の宣言を読み、上書きを書く）。

走行モデルの振る舞いを直接変えられるため、軸スタジオと同じ認可境界の内側に置く
（`require_admin_basic_auth`）。

**画面が並べる項目はこのAPIが宣言から導く**。較正値を1つ足しても、ここと画面の両方へ
書き足す場所は無い（`TUNING_PARAMETERS`に載っているものだけを返す——較正値ではない固定値は
使う側のモジュールに置いたままで、このAPIからは見えない（物理定数を出すと模型を壊せ、
資源の上限を出すと本番を止められる）。

**名前に添える対象（どの路面・どの停止要因の値か）は、値を使う側の宣言から引く**。`domain/tuning.py`は
その宣言を読めない（循環する）ので、ここで添える。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_tuning_service
from app.domain.road import rolling_resistance_subjects
from app.domain.strict_model import StrictModel
from app.domain.traffic import stop_seconds_subjects
from app.domain.tuning import TUNING_PARAMETERS_BY_ID, TuningParameter, tuning_parameters_by_effect, tuning_value
from app.infrastructure.tuning_overrides import TuningOverrideError
from app.services.tuning_service import TuningService

router = APIRouter(prefix="/api/admin/tuning", tags=["tuning-admin"], dependencies=[Depends(require_admin_basic_auth)])


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
    """1件の上書き。`value`がnullなら既定へ戻す。"""

    value: float | None


def _subjects() -> dict[str, tuple[str, ...]]:
    """較正値のid → 名前へ添える対象。要求ごとに1回だけ作り、較正値の1件ずつへ渡す。"""
    return {**rolling_resistance_subjects(), **stop_seconds_subjects()}


def _view(
    parameter: TuningParameter, overridden_ids: set[str], subjects_by_id: dict[str, tuple[str, ...]]
) -> TuningParameterView:
    subjects = subjects_by_id.get(parameter.id)
    return TuningParameterView(
        id=parameter.id,
        label=f"{parameter.label}（{'／'.join(subjects)}）" if subjects else parameter.label,
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
    service: TuningService = Depends(get_tuning_service),
) -> list[TuningParameterView]:
    """較正値を効き方の順（`tuning_parameters_by_effect`）に返す。"""
    overridden = await service.overridden_parameter_ids()
    subjects_by_id = _subjects()
    return [_view(p, overridden, subjects_by_id) for p in tuning_parameters_by_effect()]


@router.put("/{param_id}", response_model=TuningParameterView)
async def update_tuning_parameter(
    param_id: str,
    request: TuningUpdateRequest,
    service: TuningService = Depends(get_tuning_service),
) -> TuningParameterView:
    parameter = TUNING_PARAMETERS_BY_ID.get(param_id)
    if parameter is None:
        # 較正値の宣言に無いidは書かせない（較正値ではない固定値はこの逆引きに載らない）。
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"較正値がありません: {param_id}")
    try:
        overridden = await service.save_override(param_id, request.value)
    except TuningOverrideError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _view(parameter, overridden, _subjects())
