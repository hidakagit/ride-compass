import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.infrastructure.request_log import RequestIdLogFilter, request_log_middleware

# ログレベルの方針(詳細は docs/logging.md):
# - INFO以上(アクセスサマリ・ルート生成サマリ・外部APIエラーWARNING等)は常時出力し、
#   実運用(debug_mode=False)の調査に足る情報をRenderのログに残す。
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

# 起動時の構成スナップショット。Renderのログだけで「どのコミット・どのエンジン設定で
# 動いていたか」を後から確認できるようにする(/healthと同じ情報のログ版)。
logging.getLogger("ridecompass.startup").info(
    "starting commit=%s engine=%s debug_mode=%s",
    settings.render_git_commit,
    settings.routing_engine,
    settings.debug_mode,
)

app = FastAPI(title="RideCompass API")

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

app.include_router(router)
