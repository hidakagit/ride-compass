# 試し（tasks#809）: backend のコードの変更
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_db_errors import install_admin_db_unavailable_handler
from app.api.cache_policy import CachePolicyMiddleware
from app.api.dependencies import get_amedas_service, get_jma_tile_client, open_region_service
from app.api.finite_json_body import reject_non_finite_json_body
from app.api.routers import api_router
from app.config import settings
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.database import get_session_factory
from app.infrastructure.debug_control import install_ring_buffer_handler
from app.infrastructure.http_client import JSON_API_TIMEOUT, TILE_PROXY_TIMEOUT, get_http_client
from app.infrastructure import road_network_store
from app.infrastructure.region_tile_cache import PRUNE_INTERVAL_HOURS
from app.infrastructure.msm_client import refresh as refresh_msm
from app.infrastructure.process_resources import close_process_resources
from app.infrastructure.request_log import (
    format_log_lines,
    request_log_middleware,
    unhandled_exception_handler,
)
from app.infrastructure.response_compression import ContentTypeGZipMiddleware
from app.infrastructure.single_process import require_single_worker
from app.infrastructure.jma_amedas_client import AMEDAS_REFRESH_INTERVAL_MINUTES
from app.services.axis_registry_service import refresh_axis_definitions
from app.services.tuning_service import refresh_tuning_values
from app.services.jma_tile_prewarm_service import prewarm_jma_tiles

logging.basicConfig(level=logging.DEBUG if settings.debug_mode else logging.INFO)
for _handler in logging.getLogger().handlers:
    format_log_lines(_handler)

install_ring_buffer_handler()

# httpxは1リクエストごとに"HTTP Request: ..."をINFOで出す。外部呼び出しの記録は
# log_external_call(debug_log.py)が担うため、タイルプロキシ等でログを埋めるだけのこれは抑える。
logging.getLogger("httpx").setLevel(logging.WARNING)

logging.getLogger("ridecompass.startup").info(
    "starting commit=%s debug_mode=%s",
    settings.git_commit,
    settings.debug_mode,
)

# DATABASE_URLへ実際に接続できない構成では/api/routes/generateが
# 常に失敗する。起動自体は妨げないため、「起動するが全リクエスト失敗」という分かりにくい
# 状態をログから読み解けるよう接続先を残す（接続確認はイベントループ起動前のため行わない）。
logging.getLogger("ridecompass.startup").info(
    "ルート生成にはDATABASE_URL(%s)への実接続が必須です。",
    settings.database_url.split("@")[-1] if "@" in settings.database_url else "設定値",
)

def _log_job_failure(event: JobExecutionEvent) -> None:
    """定期ジョブの失敗を`ridecompass.scheduler`へWARNINGで残す。

    APScheduler自身も失敗をスタックトレース付きで`apscheduler.executors`へ出すが、その名前は
    このプロジェクトの接頭辞（`ridecompass.*`）から外れ、接頭辞単位でレベルを絞ると漏れる。
    """
    logging.getLogger("ridecompass.scheduler").warning(
        "定期ジョブ%sに失敗しました: %r", event.job_id, event.exception
    )


async def _refresh_amedas_job() -> None:
    """JMAアメダスは1地点だけを絞り込めず全国ぶんを1レスポンスで返すため、リクエストごとに
    引くのではなくここでまとめて取得しRedisへ書き戻す。"""
    count = await get_amedas_service().refresh_all_stations()
    logging.getLogger("ridecompass.jma_amedas_scheduler").debug("アメダス定期更新完了 count=%d", count)


async def _prewarm_jma_tile_job() -> None:
    """対象範囲が読めなければ温めない（原因は`RegionService.get_ingested_area`がWARNINGで残す）。"""
    async with open_region_service() as region_service:
        area = await region_service.get_ingested_area()
    if area is not None:
        await prewarm_jma_tiles(get_jma_tile_client(), area)


async def _sync_msm_job() -> None:
    """気象庁MSM（風・降水の予報）の.omファイルをローカルへ同期する。

    風グリッド・ルート評価はこのローカルファイルだけを読むため、同期が止まるとデータは
    順次古くなり、予報終端が現在時刻へ追いつくと風グリッドは502を返す。
    """
    await refresh_msm(get_http_client(60.0))


async def _prune_stale_disk_generations_job() -> None:
    """ディスク永続化キャッシュの古い世代を削除する。

    世代番号は参照先を切り替えるだけで、ディスク上の古い実体は残り続ける。削除対象が
    大きい（数百MB規模）ことがあるためスレッドで実行する。
    """
    freed = await asyncio.to_thread(road_network_store.prune_other_shapes)
    if freed:
        logging.getLogger("ridecompass.disk_generation_prune").info(
            "ディスク永続キャッシュの旧世代を削除しました freed_mb=%.1f", freed / 1e6
        )


async def _prune_stale_region_tiles_job() -> None:
    """いま配っていない世代の地域タイル（路面・点・土地被覆）をディスクから消す。"""
    async with open_region_service() as region_service:
        removed = await region_service.prune_other_tile_generations()
    if removed:
        logging.getLogger("ridecompass.disk_generation_prune").info(
            "地域タイルの旧世代を削除しました removed=%d", removed
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    require_single_worker(sys.argv, os.environ)

    # httpx.AsyncClientの生成はSSLコンテキスト構築を伴い、環境によっては数百ms〜1秒かかる。
    # 遅延生成のままだとデプロイ直後の最初のリクエストがこのコストを負い、接続タイムアウトが
    # タイトな外部呼び出しではConnectTimeoutを誘発する。実際に使うtimeout値を先に構築しておく。
    get_http_client(JSON_API_TIMEOUT)
    get_http_client(TILE_PROXY_TIMEOUT)

    async with get_session_factory()() as session:
        # 例外をここで捕捉しないため、軸定義を読めない状態では起動自体が失敗する（fail-fast）。
        await refresh_axis_definitions(AxisDefinitionRepository(session))
        # 較正値は行が1つも無ければ宣言どおりの既定値のまま動く（壊れた値の行だけが起動を止める）。
        await refresh_tuning_values(session)

    # 定期ジョブはアプリの寿命の間だけ動くので、スケジューラもこの寿命の中で作る。
    scheduler = AsyncIOScheduler()
    scheduler.add_listener(_log_job_failure, EVENT_JOB_ERROR)
    # next_run_time=nowで起動直後にも1回実行し、次の定期実行までキャッシュが空のまま
    # 502を返し続けるのを避ける。
    scheduler.add_job(
        _refresh_amedas_job,
        trigger="interval",
        minutes=AMEDAS_REFRESH_INTERVAL_MINUTES,
        next_run_time=datetime.now(),
        id="refresh_amedas",
    )
    scheduler.add_job(
        _prewarm_jma_tile_job,
        trigger="interval",
        minutes=settings.jma_tile_prewarm_interval_minutes,
        next_run_time=datetime.now(),
        id="prewarm_jma_tile",
    )
    # 初回はローカルにファイルが無く、完了するまで風グリッド・ルート評価の風が使えない。
    scheduler.add_job(
        _sync_msm_job,
        trigger="interval",
        minutes=settings.msm_sync_interval_minutes,
        next_run_time=datetime.now(),
        id="sync_msm",
    )
    # 世代を上げたコードがデプロイされた直後がこのタイミングに当たる。
    scheduler.add_job(
        _prune_stale_disk_generations_job,
        trigger="date",
        run_date=datetime.now(),
        id="prune_stale_disk_generations",
    )
    # 地域タイルの世代は再起動なしにも変わる（派生の作り直し・取込）ので、起動直後のあとも定期に回す。
    scheduler.add_job(
        _prune_stale_region_tiles_job,
        trigger="interval",
        hours=PRUNE_INTERVAL_HOURS,
        next_run_time=datetime.now(),
        id="prune_stale_region_tiles",
    )
    scheduler.start()
    yield
    # 先に定期ジョブを止める。逆にすると、閉じたあとに走り出したジョブが閉じたクライアントで外部を呼ぶ。
    scheduler.shutdown(wait=False)
    await close_process_resources()


app = FastAPI(title="RideCompass API", lifespan=lifespan, dependencies=[Depends(reject_non_finite_json_body)])

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
    # フロントエンドはbackendへ直接fetchする(cross-origin)ため、X-Request-IDを
    # ブラウザのJSから読めるようexposeする。
    expose_headers=["X-Request-ID"],
)
# 圧縮はCORSより外側・request_log_middlewareより内側に置く（アクセスログの所要時間に
# 圧縮時間も含める）。Cache-Controlはヘッダしか触らないため前後関係が結果に影響しない。
app.add_middleware(ContentTypeGZipMiddleware)
app.add_middleware(CachePolicyMiddleware)

# 後から登録したミドルウェアが外側になる(アクセスログはCORS処理も含めた全体を計測・記録したい
# ため、CORSより外側に置く。リクエストIDはアクセスログの行にも載るよう、さらにその外側に置く)。
app.middleware("http")(request_log_middleware)
app.add_middleware(CorrelationIdMiddleware)
# 未処理例外(500)発生時もX-Request-IDヘッダを付ける。
app.add_exception_handler(Exception, unhandled_exception_handler)
install_admin_db_unavailable_handler(app)

app.include_router(api_router)
