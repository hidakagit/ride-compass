"""`/api/admin/`配下の全ルートがBasic認証の依存を持つことの機械的検証。

個々のルーターのテストが「このエンドポイントは401を返す」と個別に確かめても、
**新しく足したエンドポイントが認可を付け忘れた**ことは検知できない。
`test_cache_policy.py`が対応表の網羅性を全ルート走査で見るのと同じ形を、認可にも置く。

管理APIは全利用者へ影響する操作（タイルキャッシュの全消去・軸定義の変更）と、全表走査を
伴う重い集計を持つ。付け忘れは「動くが誰でも叩ける」という形で出るため、型でも例外でも
現れない。
"""

from fastapi.routing import APIRoute

from app.api.admin_auth import require_admin_basic_auth
from app.main import app

ADMIN_PATH_PREFIX = "/api/admin/"


def _admin_routes() -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(ADMIN_PATH_PREFIX)
    ]


def _depends_on_admin_auth(route: APIRoute) -> bool:
    return any(
        dependency.call is require_admin_basic_auth
        for dependency in route.dependant.dependencies
    )


def test_the_scan_is_not_empty():
    # 管理APIが1本も見つからない＝パスの前置きが変わった等でこの検査が空回りしている。
    assert _admin_routes(), f"{ADMIN_PATH_PREFIX}配下のルートが1本も見つからない"


def test_every_admin_route_requires_basic_auth():
    unprotected = [route.path for route in _admin_routes() if not _depends_on_admin_auth(route)]

    assert unprotected == [], f"require_admin_basic_authが付いていない管理API: {unprotected}"
