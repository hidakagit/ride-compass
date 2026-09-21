import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cache_policy import CachePolicyMiddleware
from app.api.routers import api_router
from app.config import settings
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.database import get_session_factory
from app.infrastructure.debug_control import install_ring_buffer_handler
from app.infrastructure.http_client import close_all_http_clients, get_http_client
from app.infrastructure import graph_material_cache, tile_cache, tile_score_matrix_cache
from app.infrastructure.jma_tile_client import JmaTileClient
from app.infrastructure.msm_client import refresh as refresh_msm
from app.infrastructure.request_log import (
    LOG_FORMAT,
    JstLogFormatter,
    RequestIdLogFilter,
    request_log_middleware,
    unhandled_exception_handler,
)
from app.infrastructure.response_compression import ContentTypeGZipMiddleware
from app.infrastructure.tuning_overrides import refresh_tuning_values
from app.services.axis_registry_service import refresh_axis_definitions
from app.services.jma_amedas_service import AMEDAS_REFRESH_INTERVAL_MINUTES, JmaAmedasService
from app.services.jma_tile_prewarm_service import prewarm_jma_tiles

logging.basicConfig(level=logging.DEBUG if settings.debug_mode else logging.INFO)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RequestIdLogFilter())
    _handler.setFormatter(JstLogFormatter(LOG_FORMAT))

install_ring_buffer_handler()

# httpxは1リクエストごとに"HTTP Request: ..."をINFOで出す。外部呼び出しの記録は
# log_external_call(debug_log.py)が担うため、タイルプロキシ等でログを埋めるだけのこれは抑える。
logging.getLogger("httpx").setLevel(logging.WARNING)

logging.getLogger("ridecompass.startup").info(
    "starting commit=%s debug_mode=%s",
    settings.git_commit,
    settings.debug_mode,
)

# DATABASE_URLへ実際に接続できない構成では/api/routes/generate・/api/routes/previewが
# 常に失敗する。起動自体は妨げないため、「起動するが全リクエスト失敗」という分かりにくい
# 状態をログから読み解けるよう接続先を残す（接続確認はイベントループ起動前のため行わない）。
logging.getLogger("ridecompass.startup").info(
    "ルート生成・プレビューにはDATABASE_URL(%s)への実接続が必須です。",
    settings.database_url.split("@")[-1] if "@" in settings.database_url else "設定値",
)

_scheduler = AsyncIOScheduler()


def _with_failure_log(
    logger_name: str, label: str
) -> Callable[[Callable[[], Awaitable[None]]], Callable[[], Awaitable[None]]]:
    """スケジューラへ載せるジョブを包み、失敗をWARNINGで残す。

    APScheduler自身のログはこのプロジェクトの命名規約（`ridecompass.*`）から外れるため、
    どのジョブが失敗したかを揃った名前で追えるようにする。
    """

    def decorate(func: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
        @functools.wraps(func)
        async def job() -> None:
            try:
                await func()
            except Exception:
                logging.getLogger(logger_name).warning("%sに失敗しました", label, exc_info=True)

        return job

    return decorate


@_with_failure_log("ridecompass.jma_amedas_scheduler", "アメダス定期更新")
async def _refresh_amedas_job() -> None:
    """JMAアメダスは1地点だけを絞り込めず全国ぶんを1レスポンスで返すため、リクエストごとに
    引くのではなくここでまとめて取得しRedisへ書き戻す。"""
    count = await JmaAmedasService(get_http_client(10.0)).refresh_all_stations()
    logging.getLogger("ridecompass.jma_amedas_scheduler").debug("アメダス定期更新完了 count=%d", count)


@_with_failure_log("ridecompass.jma_tile_prewarm_scheduler", "JMAタイルの定期プリウォーム")
async def _prewarm_jma_tile_job() -> None:
    await prewarm_jma_tiles(JmaTileClient(get_http_client(15.0)))


@_with_failure_log("ridecompass.msm_sync_scheduler", "MSMの定期同期")
async def _sync_msm_job() -> None:
    """気象庁MSM（風・降水の予報）の.omファイルをローカルへ同期する。

    風グリッド・ルート評価はこのローカルファイルだけを読むため、同期が止まるとデータは
    順次古くなり、予報終端が現在時刻へ追いつくと風グリッドは502を返す。
    """
    await refresh_msm(get_http_client(60.0))


@_with_failure_log("ridecompass.tile_cache_prune", "ディスク永続キャッシュの旧世代削除")
async def _prune_stale_disk_generations_job() -> None:
    """ディスク永続化キャッシュの古い世代を削除する。

    世代番号は参照先を切り替えるだけで、ディスク上の古い実体は残り続ける。削除対象が
    大きい（数百MB規模）ことがあるためスレッドで実行する。
    """
    freed = 0
    for prune in (graph_material_cache.prune_stale_disk_generations, tile_score_matrix_cache.prune_stale_disk_generations):
        freed += await asyncio.to_thread(prune)
    # 焼き済みタイルの置き場は鍵に世代を持たないため、世代単位では消せない。古い順で落とす。
    freed += await asyncio.to_thread(
        tile_cache.prune_to_size_limit, settings.tile_cache_size_limit_mb * 1024 * 1024
    )
    if freed:
        logging.getLogger("ridecompass.tile_cache_prune").info(
            "ディスク永続キャッシュの旧世代を削除しました freed_mb=%.1f", freed / 1e6
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # httpx.AsyncClientの生成はSSLコンテキスト構築を伴い、環境によっては数百ms〜1秒かかる。
    # 遅延生成のままだとデプロイ直後の最初のリクエストがこのコストを負い、接続タイムアウトが
    # タイトな外部呼び出しではConnectTimeoutを誘発する。実際に使うtimeout値を先に構築しておく。
    get_http_client(10.0)
    get_http_client(15.0)

    async with get_session_factory()() as session:
        # 例外をここで捕捉しないため、軸定義を読めない状態では起動自体が失敗する（fail-fast）。
        await refresh_axis_definitions(AxisDefinitionRepository(session))
        # 較正値は行が1つも無ければ宣言どおりの既定値のまま動く（壊れた値の行だけが起動を止める）。
        await refresh_tuning_values(session)

    # next_run_time=nowで起動直後にも1回実行し、次の定期実行までキャッシュが空のまま
    # 502を返し続けるのを避ける。
    _scheduler.add_job(
        _refresh_amedas_job,
        trigger="interval",
        minutes=AMEDAS_REFRESH_INTERVAL_MINUTES,
        next_run_time=datetime.now(),
        id="refresh_amedas",
    )
    _scheduler.add_job(
        _prewarm_jma_tile_job,
        trigger="interval",
        minutes=settings.jma_tile_prewarm_interval_minutes,
        next_run_time=datetime.now(),
        id="prewarm_jma_tile",
    )
    # 初回はローカルにファイルが無く、完了するまで風グリッド・ルート評価の風が使えない。
    _scheduler.add_job(
        _sync_msm_job,
        trigger="interval",
        minutes=settings.msm_sync_interval_minutes,
        next_run_time=datetime.now(),
        id="sync_msm",
    )
    # 世代を上げたコードがデプロイされた直後がこのタイミングに当たる。
    _scheduler.add_job(
        _prune_stale_disk_generations_job,
        trigger="date",
        run_date=datetime.now(),
        id="prune_stale_disk_generations",
    )
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)
    await close_all_http_clients()


app = FastAPI(title="RideCompass API", lifespan=lifespan)

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

# 後から登録したミドルウェアが外側になる(リクエストIDの付与・アクセスログはCORS処理も
# 含めた全体を計測・記録したいため、CORSより外側に置く)。
app.middleware("http")(request_log_middleware)
# 未処理例外(500)発生時もX-Request-IDヘッダを付ける。
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(api_router)
