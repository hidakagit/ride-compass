"""全ルータの組み立て（main.pyはこのapi_routerだけをincludeする）。

エンドポイントは関心ごとにモジュールへ分割してある。**どのモジュールがどのパスを持つかは
下のinclude一覧と各モジュールのdocstringが正本**で、ここへ写し取った索引は持たない
（写すと、パスを1本足したときにこのdocstringだけが古くなる。実際の全パスは
`/docs`のOpenAPIか`backend/scripts/export_openapi.py`の出力で引ける）。

分割の基準は「外部との境界の種類」で、次の4系統がある:

- **アプリのユースケース**（ルート生成・気象）
- **タイル配信**（自前生成の路面/POI/事故と、外部タイルのプロキシ）——プロキシ系は
  「pathを丸ごと転送し永続ファイルキャッシュへ載せる」という同じ骨格を共有する
- **カタログの読み取り**（評価軸・材料。認可不要で、GUI編集済みの定義を再デプロイなしに
  frontendへ渡す）
- **管理API**（`/api/admin/...`。すべてHTTP Basic認証が必要で、認可境界は
  `api/admin_auth.py: require_admin_basic_auth`に1本化してある）

DI工場（サービスの組み立て）はapi/dependencies.pyに集約している。
"""

from fastapi import APIRouter

from app.api.routers import (
    accidents,
    axis_admin,
    axis_catalog,
    basemap,
    debug_admin,
    derived_data_freshness,
    gsi_relief_tile,
    health,
    jma_tile,
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
api_router.include_router(jma_tile.router)
api_router.include_router(gsi_relief_tile.router)
api_router.include_router(axis_admin.router)
api_router.include_router(axis_catalog.router)
api_router.include_router(material_catalog.router)
api_router.include_router(debug_admin.router)
api_router.include_router(derived_data_freshness.router)
