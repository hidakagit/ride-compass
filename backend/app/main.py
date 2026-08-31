import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import api_router
from app.config import settings
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.database import get_session_factory
from app.infrastructure.debug_control import install_ring_buffer_handler
from app.infrastructure.http_client import close_all_http_clients, get_http_client
from app.infrastructure.jma_tile_client import JmaTileClient
from app.infrastructure.request_log import RequestIdLogFilter, request_log_middleware, unhandled_exception_handler
from app.services.axis_registry_service import refresh_axis_definitions
from app.services.jma_amedas_service import AMEDAS_REFRESH_INTERVAL_MINUTES, JmaAmedasService
from app.services.jma_tile_prewarm_service import prewarm_jma_tiles

# ログレベルの方針(詳細は docs/logging.md):
# - INFO以上(アクセスサマリ・ルート生成サマリ・外部APIエラーWARNING等)は常時出力し、
#   実運用(debug_mode=False)の調査に足る情報を本番のログに残す。
# - DEBUG(外部API/タイルキャッシュのイベント単位ログ等)はdebug_mode有効時のみ出力する。
# %(request_id)sはRequestIdLogFilterが全レコードへ注入する(request_log.py参照)。
logging.basicConfig(
    level=logging.DEBUG if settings.debug_mode else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s [req:%(request_id)s]: %(message)s",
)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RequestIdLogFilter())

# 改善計画T379: debug_modeをSSH不要で切り替え・確認できるよう、直近ログをメモリに
# 保持するハンドラをルートロガーへ追加する（api/routers/debug_admin.py経由で取得）。
install_ring_buffer_handler()

# httpxは1リクエストごとに"HTTP Request: ..."をINFOで出す。外部API呼び出しの記録は
# log_external_call(debug_log.py)が成功=DEBUG/失敗=WARNINGの方針で担っており、
# 常時出るhttpxのINFOはタイルプロキシ等でログを埋めるだけなのでWARNING以上に抑える。
logging.getLogger("httpx").setLevel(logging.WARNING)

# 起動時の構成スナップショット。ログだけで「どのコミットで動いていたか」を
# 後から確認できるようにする(/healthと同じ情報のログ版)。
logging.getLogger("ridecompass.startup").info(
    "starting commit=%s debug_mode=%s",
    settings.git_commit,
    settings.debug_mode,
)

# DATABASE_URLへ実際に接続できない環境(.env未作成のDBなし構成等)では
# /api/routes/generate・/api/routes/previewが常に失敗する(GraphServiceは改善計画T222で
# repository必須へ一本化済み)。起動自体は妨げず、「起動するが全リクエスト失敗」という
# 分かりにくい状態を早期に説明するWARNINGを出す。接続確認はイベントループ起動前のため
# ここでは行わず、設定値をそのままログへ出すだけに留める(実際に接続不可かはリクエスト時
# のエラーで判明する。ここはその読み解きの補助)。
logging.getLogger("ridecompass.startup").info(
    "ルート生成・プレビューにはDATABASE_URL(%s)への実接続が必須です。",
    settings.database_url.split("@")[-1] if "@" in settings.database_url else "設定値",
)

_scheduler = AsyncIOScheduler()


async def _refresh_amedas_job() -> None:
    """定期バッチ本体（改善計画T387）。JMAアメダスは1地点だけを絞り込めず全国約1,300
    観測所ぶんを1レスポンスで返すAPIのため、都度リクエストのたびに個別フェッチするのではなく
    ここで全国分をまとめて取得しRedisへ書き戻す（jma_amedas_service.pyのdocstring参照）。
    ジョブ内の例外はAPSchedulerがログするが、このプロジェクトの命名規約（ridecompass.*）に
    揃えたWARNINGも残す（外部API呼び出し自体の詳細WARNINGはjma_amedas_client.py内の
    log_external_callが別途出す）。
    """
    try:
        count = await JmaAmedasService(get_http_client(10.0)).refresh_all_stations()
        logging.getLogger("ridecompass.jma_amedas_scheduler").debug("アメダス定期更新完了 count=%d", count)
    except Exception:
        logging.getLogger("ridecompass.jma_amedas_scheduler").warning("アメダス定期更新に失敗しました", exc_info=True)


async def _prewarm_jma_tile_job() -> None:
    """定期バッチ本体（改善計画T510）。JMA動的タイル（キキクル・線状降水帯予測マップ・
    雷/竜巻ナウキャスト）をアプリの実運用範囲ぶんあらかじめRedisへ温める
    （jma_tile_prewarm_service.pyのdocstring参照）。ジョブ内の例外はAPSchedulerがログするが、
    このプロジェクトの命名規約（ridecompass.*）に揃えたWARNINGも残す。
    """
    try:
        await prewarm_jma_tiles(JmaTileClient(get_http_client(15.0)))
    except Exception:
        logging.getLogger("ridecompass.jma_tile_prewarm_scheduler").warning("JMAタイルの定期プリウォームに失敗しました", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # httpx.AsyncClientのウォームアップ（デプロイ直後の天候API失敗調査より）:
    # infrastructure/http_client.pyのコメントの通りクライアント生成はSSLコンテキスト構築
    # （CA証明書バンドルの読み込み・パース）を伴い、環境によっては数百ms〜1秒かかる。
    # 遅延生成のままだとデプロイ直後の最初のリクエストがこのコストを負い、
    # weather_client.pyのように接続タイムアウトがタイト（connect=3.0秒）な外部呼び出しでは
    # ConnectTimeoutを誘発しやすい（F5で再試行すると成功する非対称性の主因）。
    # dependencies.pyで実際に使われているtimeout値（10.0, 15.0）をここで前もって構築し、
    # 起動完了後の最初のリクエストからコストを払わずに済むようにする。
    get_http_client(10.0)
    get_http_client(15.0)

    # 改善計画T221 Stage D / T349: 評価軸定義（domain/axis_definitions.py: AXIS_DEFINITIONS）を
    # DBから読み込む。未migration・DB未接続・DB定義が半端に古い場合はAxisDefinitionSyncError
    # を送出し、ここで捕捉しないため起動自体が失敗する（fail-fast、
    # services/axis_registry_service.py参照）。
    async with get_session_factory()() as session:
        await refresh_axis_definitions(AxisDefinitionRepository(session))

    # 改善計画T387: JMAアメダスの定期バッチ。next_run_time=nowで起動直後にも1回即時実行し、
    # 次の定期実行（interval分後）を待たずにデータを温める（コールドスタート時に
    # /api/weather/amedasがinterval分ぶんキャッシュ空で502になり続けるのを避ける）。
    _scheduler.add_job(
        _refresh_amedas_job,
        trigger="interval",
        minutes=AMEDAS_REFRESH_INTERVAL_MINUTES,
        next_run_time=datetime.now(),
        id="refresh_amedas",
    )
    # 改善計画T510: JMA動的タイルの定期プリウォーム。アメダスと同じくnext_run_time=nowで
    # 起動直後にも1回即時実行し、次の定期実行を待たずにRedisを温める。
    _scheduler.add_job(
        _prewarm_jma_tile_job,
        trigger="interval",
        minutes=settings.jma_tile_prewarm_interval_minutes,
        next_run_time=datetime.now(),
        id="prewarm_jma_tile",
    )
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)
    # 改善計画T464: httpx.AsyncClientの明示close（http_client.pyのdocstring参照）。
    await close_all_http_clients()


app = FastAPI(title="RideCompass API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
    # フロントエンドはbackendへ直接fetchする(cross-origin)ため、X-Request-IDを
    # ブラウザのJSから読めるようexposeする(request_log.py参照)。
    expose_headers=["X-Request-ID"],
)

# 後から登録したミドルウェアが外側になる(リクエストIDの付与・アクセスログはCORS処理も
# 含めた全体を計測・記録したいため、CORSより外側に置く)。
app.middleware("http")(request_log_middleware)
# 改善計画T464: 未処理例外(500)発生時もX-Request-IDヘッダを付けるための
# Exceptionハンドラ(request_log.pyのモジュールdocstring参照)。
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(api_router)
