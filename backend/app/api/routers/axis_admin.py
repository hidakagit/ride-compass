"""評価軸定義のCRUD管理API（ADR: docs/records/decisions/t221-axis-registry.md）。

`domain/axis_definitions.py: AXIS_DEFINITIONS`をDBの内容と同期させる書き込み口。
ルート生成の振る舞いを直接変えられるため、他のエンドポイントと異なり認可を要求する
（require_admin_basic_auth）。GUI編集画面（軸スタジオ、frontend `/admin`）はこのAPIの
上に構築されており、軸の追加・更新・公開/非公開・削除はすべてこのAPIを通る
（docs/modules/frontend/axis-studio.md参照）。
"""

from typing import Awaitable, TypeVar

from collections.abc import Mapping
from dataclasses import asdict
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field, field_validator, model_validator
from sqlalchemy.exc import DBAPIError

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_road_graph_repository
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.axis_preview_service import axis_raw_value_distribution
from app.api.dependencies import get_axis_registry_admin_service, served_dedicated_way_value_material
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    axis_error,
    AxisDefinition,
    AxisShape,
    BreakpointLinearShape,
    PriorityCondition,
    check_axis_definition,
    referenced_materials,
)
from app.domain.axis_display import axis_display_for, bands_the_map_keeps, thresholds_the_map_drops
from app.domain.difficulty import weight_share
from app.domain.registry import AxisDisplaySpec
from app.services.axis_registry_service import AxisRegistryAdminService
from app.domain.strict_model import StrictModel

router = APIRouter(
    prefix="/api/admin/axis-definitions", tags=["axis-admin"], dependencies=[Depends(require_admin_basic_auth)]
)

_T = TypeVar("_T")


async def _guard_db_errors(awaitable: Awaitable[_T]) -> _T:
    """軸スタジオCRUDのDB例外を診断可能な503へ変換する。

    軸スタジオ（本ルーター）のCRUDの編集対象は常にDBの実データそのものであるべきで、
    DB障害時にフォールバック値を編集画面に出すと気付かないまま上書きしてしまう危険が
    ある。ここでは代わりに、DBAPIError（接続失敗・テーブルや列が作られていないなど）
    だけを捕捉し、未処理の素の500ではなく原因の当たりが付くメッセージを返す
    （ValueError/KeyErrorは呼び出し元の既存except節がそのまま扱うため対象外）。
    """
    try:
        return await awaitable
    except DBAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "軸定義DBへのアクセスに失敗しました"
                "（DB接続と、テーブルが作られているかを確認してください）"
            ),
        ) from exc


class AxisDefinitionPayload(AxisDefinition):
    """作成・更新リクエストボディ。

    フィールドと、軸そのものの不変条件（重みの非負・折れ点のx昇順・段の境界の昇順・
    段ラベルの件数など）は`AxisDefinition`が持ち、DBの行から組み立てる経路にも同じように
    効く。軸の外（材料カタログ・既存の軸）に照らす値の不変条件は`check_axis_definition`が持ち、
    起動時・復元時の読み込みも同じものを通す。ここが自分で持つのは、このプロセスの組み立て
    （配信の実装）に照らす検証だけである。
    """

    @model_validator(mode="after")
    def _check_against_the_catalog_and_the_other_axes(self) -> "AxisDefinitionPayload":
        check_axis_definition(self, AXIS_DEFINITIONS.keys())
        return self

    @model_validator(mode="after")
    def _check_dedicated_layer_is_implemented(self) -> "AxisDefinitionPayload":
        """`dedicated_way_value_layer`は、配信の実装がある材料をちょうど1つ参照する軸にだけ立てられる。

        way_id→値の配信はPythonのサービス本体（`api/dependencies.py`の
        `_DEDICATED_WAY_VALUE_SERVICES`、材料ごとに1つ）が必要で、軸スタジオでの宣言だけでは
        配信できる値が無い。宣言だけを通すと、その軸のタイル要求が実装の無いまま
        呼ばれ続ける（配信側は404を返すため表示は壊れないが、地図に出ない軸の宣言が
        残り続けて「宣言したのに出ない」原因が分からなくなる）。

        値の不変条件ではないので`check_axis_definition`へ置かない: 照らす相手はこのプロセスが組み立てた
        配信の実装で、実装の無い軸の配信は未知の軸と同じ404で済む（読み込みを止める理由にならない）。
        """
        if not self.dedicated_way_value_layer:
            return self
        materials = referenced_materials(self.shape, self.priority_overrides)
        if served_dedicated_way_value_material(materials) is None:
            raise axis_error(
                "専用配信の軸は、配信の実装がある材料をちょうど1つだけ指す必要があります"
                f"（この軸が指す材料: {materials}）。"
            )
        return self

    def to_definition(self) -> AxisDefinition:
        """派生クラスのまま先へ渡すと、Pydanticの等価判定がクラスまで見るため
        `is_cosmetic_only_update`の突き合わせが常に不一致になる。基底の型へ戻す。"""
        return AxisDefinition(**self.model_dump())


class AxisDefinitionResponse(AxisDefinition):
    """一覧・単体取得のレスポンスボディ。DB由来の既存データをそのまま返すため、
    `AxisDefinitionPayload`の検証（`check_axis_definition`）は継承せず`AxisDefinition`から派生する
    ——通らなくなった行も見せて直させる。

    `display`: `domain/axis_display.py: axis_display_for()`の計算結果
    （`GET /api/axis-catalog`と同じ関数）。軸スタジオのGUI（AxisComposer.tsx）が
    「自動導出が失敗している（kind="none"）ので、この軸の材料には地図表示用のデータ取得
    経路がまだ用意されていない」という注記を出すために必要——下書き軸（is_published=False）
    は`GET /api/axis-catalog`に現れないため、編集中に自己診断できる経路がこの管理APIの
    レスポンスにしか無い。"""

    display: AxisDisplaySpec
    #: この軸を（保存した既定の重みで）公開したとき、公開軸の既定の重みの合計に占める割合（0〜1）。公開済みの軸は
    #: 今の割合。合計が0ならNone。総合難易度が重みの合計で割るのと同じ分母（`difficulty.weight_share`）で、
    #: 画面は計算し直さない。
    weight_share_when_published: float | None


def _to_response(definition: AxisDefinition, definitions: Mapping[str, AxisDefinition]) -> AxisDefinitionResponse:
    """`AxisDefinitionResponse`は`AxisDefinition`へ`display`と`weight_share_when_published`を足すだけなので、
    フィールドを手書き列挙せずmodel_dump()経由で展開する。`definitions`は割合の分母を作る全軸。"""
    other_published = [
        other.default_weight
        for axis_id, other in definitions.items()
        if other.is_published and axis_id != definition.axis_id
    ]
    return AxisDefinitionResponse(
        **definition.model_dump(),
        display=axis_display_for(definition),
        weight_share_when_published=weight_share(definition.default_weight, other_published),
    )


async def _all_definitions(service: "AxisRegistryAdminService") -> Mapping[str, AxisDefinition]:
    return await _guard_db_errors(service.list_all())


@router.get("")
async def list_axis_definitions(
    service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service),
) -> list[AxisDefinitionResponse]:
    definitions = await _guard_db_errors(service.list_all())
    return [_to_response(definition, definitions) for definition in definitions.values()]


@router.get("/{axis_id}")
async def get_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    definition = await _guard_db_errors(service.get(axis_id))
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません")
    return _to_response(definition, await _all_definitions(service))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_axis_definition(
    payload: AxisDefinitionPayload, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    definition = payload.to_definition()
    try:
        await _guard_db_errors(service.create(definition))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_response(definition, await _all_definitions(service))


@router.put("/{axis_id}")
async def update_axis_definition(
    axis_id: str,
    payload: AxisDefinitionPayload,
    service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service),
) -> AxisDefinitionResponse:
    if payload.axis_id != axis_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="axis_idはURLとボディで一致させてください"
        )
    definition = payload.to_definition()
    try:
        await _guard_db_errors(service.update(axis_id, definition))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません") from exc
    except ValueError as exc:
        # 公開済み軸の更新拒否（AxisPublishedImmutableError）と材料の
        # 排他チェック（AxisMaterialConflictError）の両方がここを通る。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_response(definition, await _all_definitions(service))


@router.delete("/{axis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> None:
    try:
        await _guard_db_errors(service.delete(axis_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{axis_id}/unpublish")
async def unpublish_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    """公開済み軸を下書きへ戻す。`update()`と異なり公開済み軸に対しても
    成功する——これが`update()`ではなく専用エンドポイントである理由（is_published以外の
    フィールドは一切変更しない、「公開済みは編集不可」原則を保ったまま公開フラグの
    反転だけに穴を開ける）。下書きへ戻った軸は通常のPUTで再編集・再公開できる。"""
    try:
        await _guard_db_errors(service.unpublish(axis_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"axis_id={axis_id} が見つかりません") from exc
    definition = await _guard_db_errors(service.get(axis_id))
    if definition is None:
        # assert文は`python -O`実行時に取り除かれるため使わない（本番起動コマンドが-Oを
        # 使っていなくても、将来変更されると不変条件チェックごと消える不安定な保護に
        # なる）。unpublishが例外なく返った直後のため通常は必ず存在するが、その不変条件を
        # 常に有効な形で守る。
        raise RuntimeError(f"axis_id={axis_id} のunpublish直後にgetが空を返しました（不変条件違反）")
    return _to_response(definition, await _all_definitions(service))


class AxisPreviewRequest(StrictModel):
    """分布プレビューの入力。軸全体ではなく`shape`だけを受け取る——プレビューは
    保存前の編集中に呼ぶもので、ラベル等の書き込み用フィールドが揃っている必要はない。"""

    shape: AxisShape


class ValueDistributionResponse(StrictModel):
    """延長で重み付けた値の分布（`services/axis_preview_service.py`参照）。

    折れ点を通す前の**生値**を返し、折れ点の当てはめはフロント側が行う——折れ点を1つ
    動かすたびに通信すると編集の手応えが失われるうえ、折れ点は区分線形の写像でしかなく、
    生値のヒストグラムがあればクライアントで正確に求まる。
    """

    sample_ways: int
    total_km: float
    quantiles: dict[str, float]
    # (階級の下限, 上限, その階級が占める延長の割合)
    bins: list[tuple[float, float, float]]
    zero_share: float


@router.post("/preview-distribution")
async def preview_axis_distribution(
    payload: AxisPreviewRequest,
    repository: RoadGraphRepository = Depends(get_road_graph_repository),
) -> ValueDistributionResponse:
    """編集中の`shape`で、実データの生値がどう分布するかを返す。

    軸スタジオは数値の入力欄を並べるだけでは折れ点の妥当性を判断できず、公開して地図と
    ルートを見るまで結果が分からない。この分布に折れ点を当てはめれば、「延長の何%が
    満点に張り付くか」が編集中に分かる。
    """
    distribution = await _guard_db_errors(
        axis_raw_value_distribution(repository, payload.shape)
    )
    return ValueDistributionResponse(**asdict(distribution))


class ScoresPreviewRequest(StrictModel):
    """折れ点の下書きで、値がそれぞれ何点になるかの問い合わせ。点数は評価と同じ計算で出す。"""

    shape: BreakpointLinearShape
    #: 折れ点の横軸の値（項の合成・前処理の後）。分布の階級の代表値など。
    xs: list[float] = Field(default_factory=list)
    #: 1つ目の項の材料の値。その項の重みと前処理を当てて横軸の値にしてから点数にする（材料の参考点の効き目）。
    material_values: list[float] = Field(default_factory=list)


class ScorePoint(StrictModel):
    x: float
    score: float


class ScoresPreviewResponse(StrictModel):
    #: `xs`の順の点数。
    scores: list[float]
    #: `material_values`の順の、横軸の値と点数。
    material_points: list[ScorePoint]


@router.post("/preview-scores")
async def preview_scores(payload: ScoresPreviewRequest) -> ScoresPreviewResponse:
    """編集中の折れ点で、値がそれぞれ何点になるかを返す。DBを読まない。

    軸スタジオは折れ点を動かすたびにこれを問い合わせ、分布の帯の割合と効き目の表を出す。点数の計算を
    画面で作り直すと、評価と画面で同じ折れ点に別の点数が付きうる（同じxの点が並ぶところ等）。
    """
    shape = payload.shape
    weight = shape.terms[0].weight
    points = []
    for value in payload.material_values:
        x = shape.preprocessed(value * weight)
        points.append(ScorePoint(x=x, score=shape.score_at(x)))
    return ScoresPreviewResponse(scores=[shape.score_at(x) for x in payload.xs], material_points=points)


class DisplayThresholdsPreviewRequest(StrictModel):
    """段の境界の下書きの問い合わせ。段を決めるのに要る入力だけを受け取る
    （`domain/axis_display.py: thresholds_the_map_drops`）。"""

    axis_id: str = Field(min_length=1)
    shape: AxisShape
    priority_overrides: list[PriorityCondition] = Field(default_factory=list)
    thresholds: list[float] = Field(min_length=1)

    @field_validator("thresholds")
    @classmethod
    def _thresholds_must_be_strictly_ascending(cls, value: list[float]) -> list[float]:
        return AxisDefinition.check_display_thresholds_ascending(value)


class DisplayThresholdsPreviewResponse(StrictModel):
    #: 入力のうち、地図が段として作らない境界（入力の並び順）。
    dropped_on_map: list[float]
    #: 地図の各段が入力のどの段に当たるか（入力の段の番号、下から0始まり。地図の段の並び順）。
    #: 体感ラベルはこの番号で引く。
    bands_on_map: list[int]


@router.post("/preview-display-thresholds")
async def preview_display_thresholds(payload: DisplayThresholdsPreviewRequest) -> DisplayThresholdsPreviewResponse:
    """編集中の軸で、人が刻んだ段の境界のうち地図では効かないものと、地図に残る段を返す。

    判定は保存後に地図が段を作るのと同じ関数で行い、軸スタジオは結果を印として出すだけにする。
    """
    args = (payload.axis_id, payload.shape, payload.priority_overrides, payload.thresholds)
    return DisplayThresholdsPreviewResponse(
        dropped_on_map=thresholds_the_map_drops(*args),
        bands_on_map=bands_the_map_keeps(*args),
    )
