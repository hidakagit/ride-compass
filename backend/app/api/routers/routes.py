import asyncio
import logging
import math
from functools import partial
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, PrivateAttr, RootModel, field_validator, model_validator

from app.domain.time_zone import JST
from app.api.dependencies import (
    RouteGenerationSetupOpener,
    get_route_generation_setup_opener,
)
from app.api.rate_limit import client_id, enforce_rate_limit
from app.config import settings
from app.domain.hard_filters import HARD_FILTER_NAMES
from app.domain.route_preference import RoutePreference, check_axis_weights, published_axis_ids
from app.domain.route_request import (
    DEFAULT_DISTANCE_TOLERANCE_KM,
    DEFAULT_MAX_ROUTES,
    MAX_DISTANCE_TOLERANCE_KM,
    MAX_ROUTE_DISTANCE_KM,
    MAX_ROUTES,
    MAX_SPLICED_EDGES,
    MAX_WAYPOINTS,
    LoopTarget,
    RouteTarget,
    SplicedTarget,
    WaypointsTarget,
    check_point_distance,
    check_spliced_edge_count,
    check_waypoint_count,
)
from app.domain.geo import haversine_distance_km
from app.domain.wind import ASSUMED_SPEED_KMH, MAX_ASSUMED_SPEED_KMH, MIN_ASSUMED_SPEED_KMH
from app.domain.route import Coordinates, RouteCandidate
from app.infrastructure import job_registry
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.services.route_generation_setup import generate_route_candidates
from app.domain.strict_model import StrictModel

router = APIRouter()
logger = logging.getLogger("ridecompass.generate")

# ルート生成の同時実行上限（settings.generate_max_concurrent、config.pyのコメント参照）。
# 上限を超えた分は待たせず429で即座に返し、ブラウザのリトライや連打で外部サービスへの
# 負荷が積み上がることを防ぐ。
_generate_semaphore = asyncio.Semaphore(settings.generate_max_concurrent)

# 実行中のルート生成ジョブ（`create_task`の戻り値）。イベントループはタスクへの強参照を
# 持たないため、ここで保持しないとGCが実行中のジョブごと回収しうる。
_running_generate_tasks: set[asyncio.Task] = set()


class RoutePreferenceWeights(RootModel[dict[str, float]]):
    """Edge評価・区間難易度（絶対評価、難易度合成）の重み。
    キーはaxis_id（`domain/axis_definitions.py: AXIS_DEFINITIONS`）で、
    `domain/route_preference.py: RoutePreference`と同じ。

    軸ごとの固定フィールドではなくaxis_idキーの辞書にすることで、軸の増減でこのモデルの
    改修が不要になる。API境界では「キー省略時に既定値が黙って入る」ことを避けるため、
    公開軸のaxis_idを全部明示することを検証で強制する（上書きするなら全軸を明示する、
    という方針）。値の不変条件（公開軸のidだけ・有限かつ非負）は`check_axis_weights`。
    """

    @model_validator(mode="after")
    def _check_axis_keys(self) -> "RoutePreferenceWeights":
        missing = sorted(published_axis_ids() - self.root.keys())
        if missing:
            raise ValueError(f"route_preference must specify every published axis_id (missing={missing})")
        check_axis_weights(self.root)
        return self


class HardFilterOverride(RootModel[dict[str, bool]]):
    """0次ハードフィルタ（候補にすら入れない道路種別）の個別ON/OFF上書き。
    キーはdomain/hard_filters.py: HARD_FILTER_NAMESと同じ。RoutePreferenceWeightsと同じ
    「全フィールド必須」方針（上書きするなら全項目を明示する）。値がTrueのフィルタだけが
    有効（該当道路を探索対象から除外する）。
    """

    @model_validator(mode="after")
    def _check_filter_keys(self) -> "HardFilterOverride":
        expected = HARD_FILTER_NAMES
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
        return cls({name: name in active for name in sorted(HARD_FILTER_NAMES)})


class RouteGenerateRequest(StrictModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    # 周回の目標距離。経由地・目的地を置いたときは探索の範囲になり、置いた点からbackendが決める
    # （`_resolve_target`。送られた値は使わない）ため省略できる。
    distance_km: float | None = Field(default=None, gt=0, le=MAX_ROUTE_DISTANCE_KM)
    distance_tolerance_km: float = Field(gt=0, le=MAX_DISTANCE_TOLERANCE_KM, default=DEFAULT_DISTANCE_TOLERANCE_KM)
    route_type: Literal["loop"] = "loop"
    # 評価重みのリクエスト単位の上書き（研究用）。省略時はAXIS_DEFINITIONS由来の既定値
    # （`RoutePreference()`）を使う。
    # 実際に適用された値はレスポンスのconditionsへエコーされる。
    route_preference: RoutePreferenceWeights | None = None
    # 主観的割増と時間の換算レート（P）。**省略が既定**で、そのとき使う値は
    # リクエスト処理時に較正値から読む（`domain/evaluation.py: resolve_penalty_strength`、
    # 値の意味と根拠もそちら）。ここへ既定値を書くとimport時に束ねられ、DBの上書きが効かない。
    penalty_strength: float | None = Field(ge=0, default=None)
    # 0次ハードフィルタの勾配しきい値（%、絶対値。省略時は除外なし。
    # `domain/hard_filters.py: compute_hard_filter_excluded`参照）。
    max_average_grade_percent: float | None = Field(ge=0, default=None)
    # 0次ハードフィルタ名（no_bicycle/motorway/trunk）の個別ON/OFF上書き。
    # 省略時は全フィルタ有効（DEFAULT_HARD_FILTERS）。
    hard_filters: HardFilterOverride | None = None
    # 返す周回候補の上限件数（フロンティア方式の折返し点候補から距離フィルタ合格・
    # overall_difficulty昇順の上位この件数を返す）。経由地の無い目的地ルート
    # （destination指定・waypoints未指定）はvia-node方式の代替経路にも同じ値が効く。
    # 経由地を1つ以上伴う経由地・目的地指定ルートでは無視される（常に1件、経由地が
    # あるとレグごとに代替案が組合せで増えるため）。上限・既定値はOpenAPI生成物
    # （route-generate-config.json）経由でフロントへ渡す唯一の情報源にする。
    max_routes: int = Field(ge=1, le=MAX_ROUTES, default=DEFAULT_MAX_ROUTES)
    # 仮定巡航速度（km/h）。各区間の通過予定時刻（探索時の風の時刻選択）・到達予想時刻の
    # 算出に使う。範囲・既定値はOpenAPI生成物（route-generate-config.json）経由でフロントへ
    # 渡す唯一の情報源にする。
    assumed_speed_kmh: float = Field(ge=MIN_ASSUMED_SPEED_KMH, le=MAX_ASSUMED_SPEED_KMH, default=ASSUMED_SPEED_KMH)
    # ユーザーが地図上で指定した経由地（起点→経由地1→...→起点の順で通過する単一経路を
    # 生成する）。指定時は周回候補の生成を行わない。bboxが際限なく広がらないよう、
    # 起点からdistance_km以内という緩いガードのみ課す（詳細な妥当性はルーティング自体の
    # 成否に委ねる）。
    waypoints: list[Coordinates] | None = Field(default=None, max_length=MAX_WAYPOINTS)
    # 指定時は起点に戻らず目的地で終わる片道ルートにする（経由地のみの場合は起点で
    # 終わる周回）。
    destination: Coordinates | None = None
    # 地図のレンズ（色分け）が表示を要求している軸id。探索の重みが0の軸でも、レンズに
    # 選ばれていれば区間表示のためにレグごとの風で評価する（探索コストには影響しない）。
    # 未知のidや軸以外（総合難易度・なし）は無視される。
    lens_axis_id: str | None = None
    # 出発時刻（省略時はサーバーの現在時刻）。風の時間変化評価（レグごとの通過予測時刻）の
    # 起点になる。naive値はJSTとして扱う。
    start_time: datetime | None = None
    # 区間の乗り換え: クライアントが候補の`edge_ids`から区間を差し替えて組み立てた経路。
    # 指定時は探索を行わず、この経路だけを既存候補と同じ経路で評価して1件返す
    # （`destination`が必須。`waypoints`・`max_routes`は使わない）。
    # 生成と同じコスト曲線（`prepare`が支配的）のため、別エンドポイントにせず同じ
    # ジョブ機構へ載せる。
    spliced_edge_ids: list[str] | None = Field(default=None, min_length=1, max_length=MAX_SPLICED_EDGES)

    # 画面の操作で届く上限は、制約（英語の文を返す）より先に日本語で止める。制約は契約に載せるため残す。
    @field_validator("waypoints", mode="before")
    @classmethod
    def _check_waypoint_count(cls, value: object) -> object:
        if isinstance(value, list):
            check_waypoint_count(len(value))
        return value

    @field_validator("spliced_edge_ids", mode="before")
    @classmethod
    def _check_spliced_edge_count(cls, value: object) -> object:
        if isinstance(value, list):
            check_spliced_edge_count(len(value))
        return value

    _target: RouteTarget = PrivateAttr()

    @model_validator(mode="after")
    def _resolve_target(self) -> "RouteGenerateRequest":
        # 経由地・目的地を置いたときの距離は探索の範囲と「点が遠すぎないか」の検査に使う値で、最も遠い点より
        # 必ず長くする。周回では距離が目標そのものなので送られた値が要る。
        points = [*(self.waypoints or []), *([self.destination] if self.destination else [])]
        if not points:
            if self.spliced_edge_ids:
                raise ValueError("spliced_edge_ids requires destination")
            if self.distance_km is None:
                raise ValueError("distance_km is required without waypoints/destination")
            self._target = LoopTarget(distance_km=self.distance_km)
            return self
        origin = Coordinates(latitude=self.latitude, longitude=self.longitude)
        farthest_km = max(haversine_distance_km(origin, point) for point in points)
        check_point_distance(farthest_km)
        distance_km = min(MAX_ROUTE_DISTANCE_KM, math.ceil(farthest_km) + 1)
        if self.spliced_edge_ids:
            # 合成の対象は目的地ルートだけ（周回は起点へ戻る制約があり、途中で別候補へ
            # 乗り換えると戻れる保証が無くなる）。
            if self.destination is None:
                raise ValueError("spliced_edge_ids requires destination")
            first, *rest = self.spliced_edge_ids
            self._target = SplicedTarget(
                distance_km=distance_km, destination=self.destination, edge_ids=(first, *rest)
            )
        else:
            self._target = WaypointsTarget(
                distance_km=distance_km, waypoints=self.waypoints or [], destination=self.destination
            )
        return self

    @property
    def target(self) -> RouteTarget:
        """検証を通った要求が何を生成するか（周回・経由地と目的地・差し替えた経路）。"""
        return self._target


def _resolve_start_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(JST)
    if value.tzinfo is None:
        return value.replace(tzinfo=JST)
    return value.astimezone(JST)


class GenerationConditions(StrictModel):
    """この生成に実際に適用された条件のエコー（実験の記録・再現用、研究IF改善 §10-6）。

    route_preference は「リクエストで上書きされた値」または「既定値」のうち実際に
    使われた方。レスポンスJSONを保存すれば、同じ条件をroute_preferenceとしてそのまま
    再送して再現できる。
    """

    latitude: float
    longitude: float
    distance_km: float
    distance_tolerance_km: float
    route_preference: RoutePreferenceWeights
    # 主観的割増と時間の換算レート（P）。
    penalty_strength: float
    # 0次ハードフィルタの勾配しきい値（%、Noneは除外なし）。
    max_average_grade_percent: float | None
    # 0次ハードフィルタの個別ON/OFF上書き（実際に適用された値）。
    hard_filters: HardFilterOverride
    # 候補数の上限（実際に適用された値）。経由地を伴う生成では、指定によらず
    # `route_request.ROUTES_WITH_WAYPOINTS`。
    max_routes: int
    # 実際に適用された出発時刻（JST）。
    start_time: datetime
    # 仮定巡航速度（km/h、実際に適用された値）。
    assumed_speed_kmh: float
    # 指定された経由地（未指定はNone、周回候補の生成）。
    waypoints: list[Coordinates] | None
    # 指定された目的地（未指定はNone、経由地のみなら起点に戻る周回）。
    destination: Coordinates | None
    # 経由地の無い目的地ルートで、`destination`がメインの道路網から孤立した
    # Node（歩道橋・私有地内通路等）にスナップされたため、実際にはアクセス可能な最寄りNode
    # へ補正して探索した場合の座標。補正しなかった（`destination`をそのまま使えた）場合は
    # None。
    corrected_destination: Coordinates | None = None
    # ISO8601（JST）。周回の風評価は生成時刻に依存するため、厳密な再現はできない点に注意
    generated_at: str


class RouteGenerateResponse(StrictModel):
    routes: list[RouteCandidate]
    conditions: GenerationConditions
    # routesが空のとき、原因の要約（RouteGenerator.last_no_candidates_reason、
    # route_generator.pyのlogger.warning行と同じ情報源）。ユーザーが原因を推測できず
    # SSHでサーバーログを見る以外に切り分け手段が無い状態を避けるための情報。
    # routesが1件以上あるときは常にNone。
    no_candidates_reason: str | None = None


class RouteGenerateJobCreatedResponse(StrictModel):
    """`POST /api/routes/generate`の応答。

    生成は数秒〜数十秒かかる（探索範囲が広いほど長い）ため、ブラウザのfetchを塞がないよう
    バックグラウンドジョブで走らせ、この応答は即座に返る。結果は`GET /api/routes/generate/
    {job_id}`をポーリングして取得する。
    """

    job_id: str


class RouteGenerateJobPending(StrictModel):
    status: Literal["queued", "running"]


class RouteGenerateJobDone(StrictModel):
    status: Literal["done"] = "done"
    result: RouteGenerateResponse


class RouteGenerateJobFailed(StrictModel):
    status: Literal["failed"] = "failed"
    error: str


# ジョブの状態。結果は完了のときだけ、失敗の理由は失敗のときだけ在る。
RouteGenerateJobStatusResponse = Annotated[
    RouteGenerateJobPending | RouteGenerateJobDone | RouteGenerateJobFailed, Field(discriminator="status")
]


@router.post("/api/routes/generate", response_model=RouteGenerateJobCreatedResponse, status_code=202)
async def generate_routes(
    request: RouteGenerateRequest,
    http_request: Request,
    open_setup: RouteGenerationSetupOpener = Depends(get_route_generation_setup_opener),
) -> RouteGenerateJobCreatedResponse:
    enforce_rate_limit(http_request, "generate", settings.generate_rate_limit_per_minute)

    # 同時実行数の上限に達している場合は待たせず即座に429を返す（外部サービスへの負荷が
    # 積み上がるのを防ぐ）。`locked()`確認を`_run_generate_job`側でのみ行うと、間に
    # 起動待ちが挟まり、複数リクエストがほぼ同時に届くと上限を超える数のジョブが202で
    # 受理されてしまうレースになる。`locked()`確認と`acquire()`をこのハンドラ内で
    # awaitを挟まず連続実行する
    # （`asyncio.Semaphore.acquire()`は値が残っていれば内部の待機用awaitへ到達せず
    # 同期的に減算するため、この2行の間に他コルーチンが割り込む隙間は無い）ことで、
    # 「投稿時点で即429」という既定の挙動を隙間なく保証する。取得したセマフォは
    # `_run_generate_job`側のfinallyで解放する（このacquireより後のコードは例外を
    # 投げない前提——投げうる検証はすべてこれより前で済ませてある）。
    if _generate_semaphore.locked():
        record_rate_limit_rejection(
            "generate-concurrency", client_id(http_request), f"concurrent={settings.generate_max_concurrent}"
        )
        raise HTTPException(status_code=429, detail="ルート生成が混み合っています。しばらく待ってから再試行してください。")
    await _generate_semaphore.acquire()

    job_id = job_registry.create_job()
    # ジョブ本体は`BackgroundTasks`ではなく`create_task`で起動する。`BackgroundTasks`は
    # レスポンス送出が完了してから実行されるため、送出中の失敗（クライアント切断・
    # ミドルウェアの例外）でジョブが一度も起動せず、上で取得したセマフォを解放する
    # finallyへ到達しない。`generate_max_concurrent`分だけこれが起きるとルート生成が
    # プロセス再起動まで全断する（`/health`は正常を返すため外形監視にもかからない）。
    task = asyncio.create_task(_run_generate_job(job_id, request, open_setup))
    # イベントループはタスクへの強参照を持たないため、参照を保持しないとGCが実行中の
    # ジョブごと回収しうる（そのときもセマフォは解放されない）。
    _running_generate_tasks.add(task)
    task.add_done_callback(_running_generate_tasks.discard)
    return RouteGenerateJobCreatedResponse(job_id=job_id)


@router.get("/api/routes/generate/{job_id}", response_model=RouteGenerateJobStatusResponse)
async def get_generate_job(job_id: str) -> RouteGenerateJobStatusResponse:
    record = job_registry.get_job(job_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="ジョブが見つかりません[完了から時間が経過して破棄された、"
            "またはサーバーが再起動された可能性があります]",
        )
    if record.status == "done":
        return RouteGenerateJobDone(result=record.result)
    if record.status == "failed":
        # `job_registry.set_failed`は理由を必ず受け取る。
        return RouteGenerateJobFailed(error=cast(str, record.error))
    return RouteGenerateJobPending(status=record.status)


async def _run_generate_job(job_id: str, request: RouteGenerateRequest, open_setup: RouteGenerationSetupOpener) -> None:
    """`generate_routes`が`asyncio.create_task`で起動するジョブ本体。
    例外はここで捕捉してjob_registryへ記録する——切り離されたタスクの例外はどこにも
    伝播せず、素通しするとサーバーログにしか残らずクライアントは永久にポーリングし
    続けることになる。

    `_generate_semaphore`は投稿時点の`generate_routes`側で既に取得済み（TOCTOUレース
    対応）。ここでは成否によらず必ずfinallyで解放する。"""
    try:
        # 重みの上書き（省略時はエンジンを組む側で既定値を読む）。
        # 適用された値はconditionsへエコーする。
        preference_override = (
            RoutePreference(weights=dict(request.route_preference.root)) if request.route_preference else None
        )
        hard_filters_override = request.hard_filters.to_frozenset() if request.hard_filters else None

        job_registry.set_running(job_id)
        start_time = _resolve_start_time(request.start_time)
        target = request.target
        generated = await generate_route_candidates(
            partial(
                open_setup,
                preference_override=preference_override,
                penalty_strength=request.penalty_strength,
                max_average_grade_percent=request.max_average_grade_percent,
                hard_filters_override=hard_filters_override,
                assumed_speed_kmh=request.assumed_speed_kmh,
                lens_axis_id=request.lens_axis_id,
            ),
            origin=Coordinates(latitude=request.latitude, longitude=request.longitude),
            target=target,
            start_time=start_time,
            max_routes=request.max_routes,
            distance_tolerance_km=request.distance_tolerance_km,
        )
        applied = generated.conditions
        response = RouteGenerateResponse(
            routes=generated.candidates,
            no_candidates_reason=generated.no_candidates_reason,
            conditions=GenerationConditions(
                latitude=request.latitude,
                longitude=request.longitude,
                distance_km=target.distance_km,
                distance_tolerance_km=request.distance_tolerance_km,
                route_preference=RoutePreferenceWeights(applied.route_preference.weights),
                penalty_strength=applied.penalty_strength,
                max_average_grade_percent=applied.max_average_grade_percent,
                hard_filters=HardFilterOverride.from_frozenset(applied.hard_filters),
                max_routes=generated.max_routes,
                start_time=start_time,
                assumed_speed_kmh=applied.assumed_speed_kmh,
                waypoints=request.waypoints,
                destination=request.destination,
                corrected_destination=generated.corrected_destination,
                generated_at=datetime.now(JST).isoformat(),
            ),
        )
        job_registry.set_done(job_id, response)
    except Exception:  # noqa: BLE001 バックグラウンドジョブの例外はここで必ず捕捉し記録する
        # ここは例外の種類を選ばず捕まえるため、DB接続やPostGISの例外もそのまま入る。
        # それらの`str(exc)`には接続先やSQLが混じるので、詳細はログ（logger.exception、
        # トレースバック込み）にだけ残し、クライアントへは汎用メッセージを返す。
        # 突き合わせにはjob_idを使う（クライアントがポーリング先として既に知っている）。
        logger.exception("ルート生成ジョブが失敗 job_id=%s", job_id)
        job_registry.set_failed(job_id, "ルート生成に失敗しました。時間をおいて再度お試しください。")
    finally:
        _generate_semaphore.release()
