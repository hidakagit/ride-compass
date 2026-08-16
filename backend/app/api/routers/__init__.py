"""全ルータの組み立て（main.pyはこのapi_routerだけをincludeする）。

エンドポイントは関心ごとに分割している（改善計画T5。旧api/routes.pyの単一ファイルから分割）:
- health.py: /health, /api/debug/stats（デプロイ確認・運用統計）、
  /api/debug/db-status（本番DB置き去り対策A: migration適用状況・データ投入バッチ実行状況、改善計画T74）
- routes.py: /api/routes/preview, /api/routes/generate（ルート生成）
- weather.py: /api/weather
- region.py: /api/region/road-surface-tiles/{z}/{x}/{y}.pbf（地域路面レイヤー）
- accidents.py: /api/region/accident-tiles/{z}/{x}/{y}.pbf（外部静的データソース T50。
  警察庁交通事故統計レイヤー）
- basemap.py: /api/basemap/{path}, /api/basemap/refresh（基礎地図プロキシ）

DI工場（サービスの組み立て）はapi/dependencies.pyに集約している。
"""

from fastapi import APIRouter

from app.api.routers import accidents, basemap, health, region, routes, weather

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(routes.router)
api_router.include_router(weather.router)
api_router.include_router(region.router)
api_router.include_router(accidents.router)
api_router.include_router(basemap.router)
