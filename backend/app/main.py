import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import api_router
from app.config import settings
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.database import get_session_factory
from app.infrastructure.http_client import get_http_client
from app.infrastructure.request_log import RequestIdLogFilter, request_log_middleware
from app.services.axis_registry_service import refresh_axis_definitions

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

# httpxは1リクエストごとに"HTTP Request: ..."をINFOで出す。外部API呼び出しの記録は
# log_external_call(debug_log.py)が成功=DEBUG/失敗=WARNINGの方針で担っており、
# 常時出るhttpxのINFOはタイルプロキシ等でログを埋めるだけなのでWARNING以上に抑える。
logging.getLogger("httpx").setLevel(logging.WARNING)

# 起動時の構成スナップショット。ログだけで「どのコミット・どのエンジン設定で
# 動いていたか」を後から確認できるようにする(/healthと同じ情報のログ版)。
logging.getLogger("ridecompass.startup").info(
    "starting commit=%s engine=%s debug_mode=%s",
    settings.git_commit,
    settings.routing_engine,
    settings.debug_mode,
)

# 改善計画T249: 既定エンジンがroad_graph(T247)になったため、DATABASE_URLへ実際に
# 接続できない環境(.env未作成のDBなし構成等)では/api/routes/generateが常に失敗する
# (GraphServiceは改善計画T222でrepository必須へ一本化済み)。起動自体は妨げず、
# 「起動するが全リクエスト失敗」という分かりにくい状態を早期に説明するWARNINGを出す。
# 接続確認はイベントループ起動前のためここでは行わず、設定の組み合わせだけで判定する
# (実際に接続不可かはリクエスト時のエラーで判明する。ここはその読み解きの補助)。
if settings.routing_engine == "road_graph":
    logging.getLogger("ridecompass.startup").info(
        "routing_engine=road_graphはDATABASE_URL(%s)への実接続が必須です。"
        "接続できない環境では/api/routes/generateが失敗します"
        "(DBなしで動かす場合はROUTING_ENGINE=openrouteserviceを指定してください)",
        settings.database_url.split("@")[-1] if "@" in settings.database_url else "設定値",
    )

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

    # 改善計画T221 Stage D: 評価軸定義（domain/axis_definitions.py: AXIS_DEFINITIONS）を
    # DBから読み込む（未migration・DB未接続の環境ではWARNINGログのみでコード内蔵の
    # 既定値のまま起動を続ける、services/axis_registry_service.py参照）。
    async with get_session_factory()() as session:
        await refresh_axis_definitions(AxisDefinitionRepository(session))
    yield


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

app.include_router(api_router)
