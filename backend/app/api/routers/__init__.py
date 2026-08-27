"""全ルータの組み立て（main.pyはこのapi_routerだけをincludeする）。

エンドポイントは関心ごとに分割している（改善計画T5。旧api/routes.pyの単一ファイルから分割）:
- health.py: /health, /api/debug/stats（デプロイ確認・運用統計）、
  /api/debug/db-status（本番DB置き去り対策A: migration適用状況・データ投入バッチ実行状況、改善計画T74）
- routes.py: /api/routes/preview, /api/routes/generate（ルート生成）
- weather.py: /api/weather, /api/weather/wind-grid（風の格子点マップ、改善計画T178フォローアップ）
- region.py: /api/region/road-surface-tiles/{z}/{x}/{y}.pbf（地域路面レイヤー）
- accidents.py: /api/region/accident-tiles/{z}/{x}/{y}.pbf（外部静的データソース T50。
  警察庁交通事故統計レイヤー）
- basemap.py: /api/basemap/{path}, /api/basemap/refresh（基礎地図プロキシ）
- axis_admin.py: /api/admin/axis-definitions（評価軸定義のCRUD管理API、改善計画T221
  Stage D。共有トークンheaderによる認可が必要）
- axis_catalog.py: /api/axis-catalog（評価軸カタログの読み取り専用API、改善計画T269。
  認可不要。一般向けルート設定画面がGUI編集済みの軸を再デプロイなしに取得するために使う）
- material_catalog.py: /api/material-catalog（材料カタログの読み取り専用API、改善計画T277。
  認可不要。軸スタジオの材料選択候補を、材料自体の追加はコード変更のみのまま動的取得させる）
- debug_admin.py: /api/admin/debug（debug_modeのランタイム切替・直近ログ取得、改善計画
  T378。axis_admin.pyと同じHTTP Basic認証が必要。本番でSSHせずに一時的なDEBUGログ
  取得を行うための運用API）

DI工場（サービスの組み立て）はapi/dependencies.pyに集約している。
"""

from fastapi import APIRouter

from app.api.routers import (
    accidents,
    axis_admin,
    axis_catalog,
    basemap,
    debug_admin,
    health,
    material_catalog,
    region,
    routes,
    weather,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(routes.router)
api_router.include_router(weather.router)
api_router.include_router(region.router)
api_router.include_router(accidents.router)
api_router.include_router(basemap.router)
api_router.include_router(axis_admin.router)
api_router.include_router(axis_catalog.router)
api_router.include_router(material_catalog.router)
api_router.include_router(debug_admin.router)
