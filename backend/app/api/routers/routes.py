import asyncio
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field, RootModel, model_validator

from app.api.dependencies import (
    PreviewBuilder,
    client_id,
    get_preview_builder,
    open_route_generation_setup,
)
from app.config import settings
from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.errors import RoutingError
from app.domain.evaluation import DEFAULT_HARD_FILTERS, RoutePreference
from app.domain.geo import haversine_distance_km
from app.domain.route import Coordinates, RouteCandidate, RouteSegment
from app.infrastructure import job_registry
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit
from app.services.route_generator import JST

router = APIRouter()
logger = logging.getLogger("ridecompass.generate")

# ルート生成の同時実行上限（settings.generate_max_concurrent、config.pyのコメント参照）。
# 上限を超えた分は待たせず429で即座に返し、ブラウザのリトライや連打で外部サービスへの
# 負荷が積み上がることを防ぐ。
_generate_semaphore = asyncio.Semaphore(settings.generate_max_concurrent)


class RoutePreviewRequest(BaseModel):
    origin: Coordinates
    destination: Coordinates


@router.post("/api/routes/preview", response_model=RouteSegment)
async def preview_route(
    request: RoutePreviewRequest,
    http_request: Request,
    preview: PreviewBuilder = Depends(get_preview_builder),
) -> RouteSegment:
    if not check_rate_limit(f"preview:{client_id(http_request)}", settings.preview_rate_limit_per_minute):
        record_rate_limit_rejection(
            "preview", client_id(http_request), f"{settings.preview_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    try:
        return await preview(request.origin, request.destination)
    except RoutingError as exc:
        raise HTTPException(status_code=502, detail=f"ルート取得に失敗しました: {exc}") from exc


class ScoringWeights(BaseModel):
    """total_score算出（候補集合内の相対評価、RouteScorer）の重み。キーはscoring.yamlと同じ。

    値は非負なら任意（合成時に有効な指標の重み和で正規化するため、合計を1.0にする必要は
    無い）。すべて0にした場合は合成不能としてtotal_score=Noneになる（RouteScorer参照）。
    """

    distance_weight: float = Field(ge=0)
    elevation_weight: float = Field(ge=0)
    wind_weight: float = Field(ge=0)
    road_weight: float = Field(ge=0)


class RoutePreferenceWeights(RootModel[dict[str, float]]):
    """Edge評価・区間難易度（絶対評価、EvaluationService/難易度合成）の重み。
    キーはaxis_id（`domain/axis_definitions.py: AXIS_DEFINITIONS`）で、
    `domain/evaluation.py: RoutePreference`と同じ。

    改善計画T221 Stage B: 軸ごとの固定フィールドをやめaxis_idキーの辞書へ一般化した
    （軸の増減でこのモデルの改修が不要になる）。API境界では「キー省略時に既定値が
    黙って入る」ことを避けるため、既知の全axis_idを明示することを検証で強制する
    （上書きするなら全軸を明示する、という方針）。値は非負。
    """

    @model_validator(mode="after")
    def _check_axis_keys(self) -> "RoutePreferenceWeights":
        # 改善計画T292: AXIS_DEFINITIONSには内部軸（is_published=False、他の公開軸から
        # 参照される専用の推定軸）も含まれるため、一般ユーザー向けAPIの上書き対象は
        # 公開軸のみへ絞る（domain/evaluation.py: RoutePreference._validate_and_fill_weightsと
        # 同じ絞り込み）。
        expected = {axis_id for axis_id, definition in AXIS_DEFINITIONS.items() if definition.is_published}
        actual = self.root.keys()
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            detail_parts = []
            if missing:
                detail_parts.append(f"missing={missing}")
            if extra:
                detail_parts.append(f"unknown={extra}")
            raise ValueError(
                f"route_preference must specify exactly the {len(expected)} known axis_id keys ({', '.join(detail_parts)})"
            )
        negative = sorted(axis_id for axis_id, weight in self.root.items() if weight < 0)
        if negative:
            raise ValueError(f"route_preference weights must be >= 0 (negative: {negative})")
        return self


class HardFilterOverride(RootModel[dict[str, bool]]):
    """0次ハードフィルタ（候補にすら入れない道路種別）の個別ON/OFF上書き（改善計画T266）。
    キーはdomain/evaluation.py: DEFAULT_HARD_FILTERSと同じ（'no_bicycle'/'motorway'/
    'trunk'）。RoutePreferenceWeightsと同じ「全フィールド必須」方針（上書きするなら
    全項目を明示する）。値がTrueのフィルタだけが有効（該当道路を探索対象から除外する）。
    """

    @model_validator(mode="after")
    def _check_filter_keys(self) -> "HardFilterOverride":
        expected = DEFAULT_HARD_FILTERS
        actual = set(self.root.keys())
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            detail_parts = []
            if missing:
                detail_parts.append(f"missing={missing}")
            if extra:
                detail_parts.append(f"unknown={extra}")
            raise ValueError(
                f"hard_filters must specify exactly the {len(expected)} known filter names ({', '.join(detail_parts)})"
            )
        return self

    def to_frozenset(self) -> frozenset[str]:
        return frozenset(name for name, enabled in self.root.items() if enabled)

    @classmethod
    def from_frozenset(cls, active: frozenset[str]) -> "HardFilterOverride":
        return cls({name: name in active for name in sorted(DEFAULT_HARD_FILTERS)})


class RouteGenerateRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    # 上限が無いと1リクエストで外部API無料枠（openrouteservice: 日次2000）を枯渇させたり、
    # road_graphエンジンでbboxが際限なく広がりタイル問い合わせが長時間ハングしうる。
    # 既存の実機検証は30kmまでのため、余裕を見つつも無制限は避ける値として100kmとする。
    distance_km: float = Field(gt=0, le=100)
    distance_tolerance_km: float = Field(gt=0, le=50, default=5.0)
    route_type: Literal["loop"] = "loop"
    # 評価重みのリクエスト単位の上書き（研究用、docs/research-interface-review-2026-08-15.md
    # §10-1）。省略時はscoring.yaml（おすすめ度）・AXIS_DEFINITIONS由来の既定値
    # （load_route_preference、改善計画T316）を使う。
    # 実際に適用された値はレスポンスのconditionsへエコーされる。
    scoring_weights: ScoringWeights | None = None
    route_preference: RoutePreferenceWeights | None = None
    # 改善計画T218・T12 ADR原則1: コスト式の割増率の強さ（P）。省略時は既定1.0
    # （従来どおり最悪でも距離2倍）。road_graphエンジンのみに効く
    # （domain/evaluation.py: compute_cost_from_axis_scores参照。openrouteservice
    # エンジンは経路確定後の評価表示のみのためコスト自体には影響しない）。
    penalty_strength: float = Field(ge=0, default=1.0)
    # 改善計画T218a・T12 ADR原則5: 0次ハードフィルタの勾配しきい値（%、絶対値。省略時は
    # 除外なし）。road_graphエンジンのみに効く（domain/evaluation.py: is_edge_allowed参照）。
    max_average_grade_percent: float | None = Field(ge=0, default=None)
    # 改善計画T266: 0次ハードフィルタ名（no_bicycle/motorway/trunk）の個別ON/OFF上書き。
    # 省略時は全フィルタ有効（DEFAULT_HARD_FILTERS、従来どおりの挙動）。road_graphエンジンの
    # みに効く。
    hard_filters: HardFilterOverride | None = None
    # 改善計画T364: ユーザーが地図上で指定した経由地（起点→経由地1→...→起点の順で
    # 通過する単一経路を生成する）。指定時は8方位探索を行わずroad_graphエンジンのみで
    # 対応する（openrouteservice_engine.py参照）。bboxが際限なく広がらないよう、
    # 起点からdistance_km以内という緩いガードのみ課す（詳細な妥当性はルーティング自体の
    # 成否に委ねる）。
    waypoints: list[Coordinates] | None = Field(default=None, max_length=8)
    # 改善計画T365: 指定時は起点に戻らず目的地で終わる片道ルートにする（経由地のみの
    # 場合は従来通り起点で終わる周回）。waypoints同様road_graphエンジンのみ対応。
    destination: Coordinates | None = None

    @model_validator(mode="after")
    def _check_waypoints_within_range(self) -> "RouteGenerateRequest":
        points = [*(self.waypoints or []), *([self.destination] if self.destination else [])]
        if not points:
            return self
        origin = Coordinates(latitude=self.latitude, longitude=self.longitude)
        for point in points:
            if haversine_distance_km(origin, point) > self.distance_km:
                raise ValueError("waypoints/destination must be within distance_km of the origin")
        return self


class GenerationConditions(BaseModel):
    """この生成に実際に適用された条件のエコー（実験の記録・再現用、研究IF改善 §10-6）。

    scoring_weights / route_preference は「リクエストで上書きされた値」または
    「YAML既定値」のうち実際に使われた方。レスポンスJSONを保存すれば、同じ条件を
    scoring_weights / route_preference としてそのまま再送して再現できる。
    """

    latitude: float
    longitude: float
    distance_km: float
    distance_tolerance_km: float
    scoring_weights: ScoringWeights
    route_preference: RoutePreferenceWeights
    # 改善計画T218・T12 ADR原則1: コスト式の割増率の強さ（P）。
    penalty_strength: float
    # 改善計画T218a・T12 ADR原則5: 0次ハードフィルタの勾配しきい値（%、Noneは除外なし）。
    max_average_grade_percent: float | None
    # 改善計画T266: 0次ハードフィルタの個別ON/OFF上書き（実際に適用された値）。
    hard_filters: HardFilterOverride
    # 改善計画T364: 指定された経由地（未指定はNone、従来どおりの8方位探索）。
    waypoints: list[Coordinates] | None
    # 改善計画T365: 指定された目的地（未指定はNone、経由地のみなら起点に戻る周回）。
    destination: Coordinates | None
    # ISO8601（JST）。周回の風評価は生成時刻に依存するため、厳密な再現はできない点に注意
    generated_at: str


class RouteGenerateResponse(BaseModel):
    routes: list[RouteCandidate]
    # どちらのルーティングエンジンが生成した候補かの識別子（"openrouteservice" | "road_graph"）。
    # wind_score等はエンジンによって算出の意味が異なる（openrouteservice_engine.py参照）ため、
    # 評価値の精査・比較時にどちらの定義の数値かを判別できるようにする。
    engine: str
    conditions: GenerationConditions


class RouteGenerateJobCreatedResponse(BaseModel):
    """`POST /api/routes/generate`の応答（改善計画T265）。

    冷パス（未splitな新規エリアへの初回アクセス、数十秒〜最大316秒[T248実測]）が
    ブラウザのfetchを長時間ブロックしないよう、実際の生成はバックグラウンドジョブへ
    切り出した。この応答は即座（数百ms）に返る。結果は`GET /api/routes/generate/
    {job_id}`をポーリングして取得する（frontend services/routeApi.ts参照）。
    """

    job_id: str


class RouteGenerateJobStatusResponse(BaseModel):
    status: job_registry.JobStatus
    result: RouteGenerateResponse | None = None
    error: str | None = None


@router.post("/api/routes/generate", response_model=RouteGenerateJobCreatedResponse, status_code=202)
async def generate_routes(request: RouteGenerateRequest, http_request: Request, background_tasks: BackgroundTasks) -> RouteGenerateJobCreatedResponse:
    if not check_rate_limit(f"generate:{client_id(http_request)}", settings.generate_rate_limit_per_minute):
        record_rate_limit_rejection(
            "generate", client_id(http_request), f"{settings.generate_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    # 同時実行数の上限に達している場合は待たせず即座に429を返す（外部サービスへの負荷が
    # 積み上がるのを防ぐ。locked()確認とacquireの間に隙間はあるが、多少の超過は許容する簡易実装）。
    # 改善計画T265: バックグラウンドジョブ化後もこの「投稿時点で即429」という既定の挙動は
    # 変えない（ジョブを積んで順番待ちさせる設計は今回のスコープ外）。
    if _generate_semaphore.locked():
        record_rate_limit_rejection(
            "generate-concurrency", client_id(http_request), f"concurrent={settings.generate_max_concurrent}"
        )
        raise HTTPException(status_code=429, detail="ルート生成が混み合っています。しばらく待ってから再試行してください。")

    # 改善計画T364/T365: 経由地・目的地指定はroad_graphエンジンのみ対応
    # （openrouteservice_engine.pyはget_route(waypoints)の任意長リスト対応自体は
    # あるが、今回未検証のため明示的に拒否する）。改善計画T265: 以前はRouteGenerationSetup
    # を組み立ててからengine_nameを見ていたが、engine_nameはsettings.routing_engineから
    # 一意に決まる（road_graph_engine.py/openrouteservice_engine.pyのクラス属性参照）ため、
    # 投稿時点でジョブを作らず即座に判定できる。
    if (request.waypoints or request.destination) and settings.routing_engine != "road_graph":
        raise HTTPException(
            status_code=400, detail="waypoints/destinationはroad_graphエンジンでのみ利用できます。"
        )

    job_id = job_registry.create_job()
    background_tasks.add_task(_run_generate_job, job_id, request)
    return RouteGenerateJobCreatedResponse(job_id=job_id)


@router.get("/api/routes/generate/{job_id}", response_model=RouteGenerateJobStatusResponse)
async def get_generate_job(job_id: str) -> RouteGenerateJobStatusResponse:
    record = job_registry.get_job(job_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail="ジョブが見つかりません（完了から時間が経過して破棄された可能性があります）"
        )
    return RouteGenerateJobStatusResponse(status=record.status, result=record.result, error=record.error)


async def _run_generate_job(job_id: str, request: RouteGenerateRequest) -> None:
    """`generate_routes`が`BackgroundTasks`経由でレスポンス送出後に実行するジョブ本体
    （改善計画T265）。例外はここで捕捉してjob_registryへ記録する——`BackgroundTasks`の
    例外はどこにも伝播せず、素通しするとサーバーログにしか残らずクライアントは
    永久にポーリングし続けることになる。"""
    try:
        # 重みの上書き（省略時はopen_route_generation_setup側でYAML既定値を読む）。
        # 適用された値はconditionsへエコーする。
        preference_override = (
            RoutePreference(weights=dict(request.route_preference.root)) if request.route_preference else None
        )
        scoring_override = request.scoring_weights.model_dump() if request.scoring_weights else None
        hard_filters_override = request.hard_filters.to_frozenset() if request.hard_filters else None

        async with _generate_semaphore:
            job_registry.set_running(job_id)
            async with open_route_generation_setup(
                preference_override,
                scoring_override,
                request.penalty_strength,
                request.max_average_grade_percent,
                hard_filters_override,
            ) as setup:
                origin = Coordinates(latitude=request.latitude, longitude=request.longitude)
                if request.waypoints or request.destination:
                    candidates = await setup.generator.generate_via_waypoints(
                        origin=origin,
                        waypoints=request.waypoints or [],
                        distance_km=request.distance_km,
                        destination=request.destination,
                    )
                else:
                    candidates = await setup.generator.generate_loops(
                        origin=origin,
                        distance_km=request.distance_km,
                        distance_tolerance_km=request.distance_tolerance_km,
                    )
                response = RouteGenerateResponse(
                    routes=candidates,
                    engine=setup.generator.engine_name,
                    conditions=GenerationConditions(
                        latitude=request.latitude,
                        longitude=request.longitude,
                        distance_km=request.distance_km,
                        distance_tolerance_km=request.distance_tolerance_km,
                        scoring_weights=ScoringWeights(**setup.scoring_weights),
                        route_preference=RoutePreferenceWeights(setup.route_preference.weights),
                        penalty_strength=setup.penalty_strength,
                        max_average_grade_percent=setup.max_average_grade_percent,
                        hard_filters=HardFilterOverride.from_frozenset(setup.hard_filters),
                        waypoints=request.waypoints,
                        destination=request.destination,
                        generated_at=datetime.now(JST).isoformat(),
                    ),
                )
        job_registry.set_done(job_id, response)
    except Exception as exc:  # noqa: BLE001 バックグラウンドジョブの例外はここで必ず捕捉し記録する
        logger.exception("ルート生成ジョブが失敗 job_id=%s", job_id)
        job_registry.set_failed(job_id, str(exc))
