"""評価軸定義のCRUD管理API（ADR: docs/records/decisions/t221-axis-registry.md）。

`domain/axis_definitions.py: AXIS_DEFINITIONS`をDBの内容と同期させる書き込み口。
ルート生成の振る舞いを直接変えられるため、他のエンドポイントと異なり認可を要求する
（require_admin_basic_auth）。GUI編集画面（軸スタジオ、frontend `/admin`）はこのAPIの
上に構築されており、軸の追加・更新・公開/非公開・削除はすべてこのAPIを通る
（docs/modules/frontend/axis-studio.md参照）。
"""

from collections.abc import Mapping
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field, field_validator, model_validator

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_axis_preview_service, get_axis_registry_admin_service
from app.domain.value_distribution import ValueDistribution
from app.services.axis_preview_service import AxisPreviewService
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    axis_error,
    AxisDefinition,
    AxisShape,
    BreakpointLinearShape,
    PriorityCondition,
    ScorePoint,
    check_axis_definition,
    first_term_points,
    named_references,
    referenced_materials,
    weight_share_when_published,
)
from app.domain.axis_display import axis_display_for, bands_the_map_keeps, thresholds_the_map_drops
from app.domain.registry import AxisDisplaySpec
from app.services.axis_registry_service import AxisRegistryAdminService
from app.services.dedicated_way_values import served_dedicated_way_value_material
from app.domain.strict_model import StrictModel

router = APIRouter(
    prefix="/api/admin/axis-definitions", tags=["axis-admin"], dependencies=[Depends(require_admin_basic_auth)]
)


def _axis_not_found() -> HTTPException:
    """指された軸が無い。画面から届くのは、開いている間にほかで消された軸なので、読み直しを促す。"""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="この軸はもうありません（ほかの画面で削除された可能性があります）。一覧を読み直してください。",
    )


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
        check_axis_definition(self, AXIS_DEFINITIONS)
        return self

    @model_validator(mode="after")
    def _check_dedicated_layer_is_implemented(self) -> "AxisDefinitionPayload":
        """`dedicated_way_value_layer`は、配信の実装がある材料をちょうど1つ参照する軸にだけ立てられる。

        フィーチャー→値の配信はPythonのサービス本体（`services/dedicated_way_values.py`の
        `DEDICATED_WAY_VALUE_SERVICES`、材料ごとに1つ）が必要で、軸スタジオでの宣言だけでは
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
                f"（この軸が指す材料: {named_references(materials, AXIS_DEFINITIONS)}）。"
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
    （`GET /api/axis-catalog`と同じ関数）。軸スタジオの編集画面が
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
    return AxisDefinitionResponse(
        **definition.model_dump(),
        display=axis_display_for(definition),
        weight_share_when_published=weight_share_when_published(definition, definitions),
    )


@router.get("")
async def list_axis_definitions(
    service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service),
) -> list[AxisDefinitionResponse]:
    definitions = await service.list_all()
    return [_to_response(definition, definitions) for definition in definitions.values()]


@router.get("/{axis_id}")
async def get_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    definitions = await service.list_all()
    if axis_id not in definitions:
        raise _axis_not_found()
    return _to_response(definitions[axis_id], definitions)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_axis_definition(
    payload: AxisDefinitionPayload, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> AxisDefinitionResponse:
    definition = payload.to_definition()
    try:
        definitions = await service.create(definition)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_response(definition, definitions)


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
        definitions = await service.update(axis_id, definition)
    except KeyError as exc:
        raise _axis_not_found() from exc
    except ValueError as exc:
        # 公開済み軸の更新拒否（AxisPublishedImmutableError）と材料の
        # 排他チェック（AxisMaterialConflictError）の両方がここを通る。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_response(definition, definitions)


@router.delete("/{axis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_axis_definition(
    axis_id: str, service: AxisRegistryAdminService = Depends(get_axis_registry_admin_service)
) -> None:
    try:
        await service.delete(axis_id)
    except KeyError as exc:
        raise _axis_not_found() from exc
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
        definitions = await service.unpublish(axis_id)
    except KeyError as exc:
        raise _axis_not_found() from exc
    return _to_response(definitions[axis_id], definitions)


class AxisPreviewRequest(StrictModel):
    """分布プレビューの入力。軸全体ではなく`shape`だけを受け取る——プレビューは
    保存前の編集中に呼ぶもので、ラベル等の書き込み用フィールドが揃っている必要はない。"""

    shape: AxisShape


@router.post("/preview-distribution")
async def preview_axis_distribution(
    payload: AxisPreviewRequest,
    preview: AxisPreviewService = Depends(get_axis_preview_service),
) -> ValueDistribution:
    """編集中の`shape`で、実データの生値（折れ点を通す前）がどう分布するかを返す。

    軸スタジオは数値の入力欄を並べるだけでは折れ点の妥当性を判断できず、公開して地図と
    ルートを見るまで結果が分からない。この分布に折れ点を当てはめれば、「延長の何%が
    満点に張り付くか」が編集中に分かる。
    """
    return await preview.raw_value_distribution(payload.shape)


class ScoresPreviewRequest(StrictModel):
    """折れ点の下書きで、値がそれぞれ何点になるかの問い合わせ。点数は評価と同じ計算で出す。"""

    shape: BreakpointLinearShape
    #: 折れ点の横軸の値（項の合成・前処理の後）。分布の階級の代表値など。
    xs: list[float] = Field(default_factory=list)
    #: 1つ目の項の材料の値（材料の参考点の効き目）。ほかの項の材料は無い道として、評価と同じ計算で点数にする。
    material_values: list[float] = Field(default_factory=list)


class ScoresPreviewResponse(StrictModel):
    #: `xs`の順の点数。
    scores: list[float]
    #: `material_values`の順の、横軸の値と点数。評価がその道を欠損にする値（ほかの項に必須の材料がある）はnull。
    material_points: list[ScorePoint | None]


@router.post("/preview-scores")
async def preview_scores(payload: ScoresPreviewRequest) -> ScoresPreviewResponse:
    """編集中の折れ点で、値がそれぞれ何点になるかを返す。DBを読まない。

    軸スタジオは折れ点を動かすたびにこれを問い合わせ、分布の帯の割合と効き目の表を出す。点数の計算を
    画面で作り直すと、評価と画面で同じ折れ点に別の点数が付きうる（同じxの点が並ぶところ等）。
    """
    return ScoresPreviewResponse(
        scores=[payload.shape.score_at(x) for x in payload.xs],
        material_points=first_term_points(payload.shape, payload.material_values),
    )


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
