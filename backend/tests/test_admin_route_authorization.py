"""管理API（`/api/admin/`配下）の認可境界。

2つに分けて見る:
- **全ルートが`require_admin_basic_auth`を依存に持つこと**——全ルート走査。新しく足した
  エンドポイントが認可を付け忘れたことを、口ごとのテストでは検知できない。
  `test_cache_policy.py`が対応表の網羅性を全ルート走査で見るのと同じ形を、認可にも置く。
- **その依存が資格情報の欠落・不一致・未設定を401で拒むこと**——依存を持つ口ならどれで
  確かめても同じなので、1つの口で見る。

口ごとに「認証なしで401」を確かめるテストは、この2つの組で足りるため置かない。正しい資格情報で通ることは、
管理APIの経路ごとのテストが通す。

管理APIは全利用者へ影響する操作（タイルキャッシュの全消去・軸定義の変更）と、全表走査を
伴う重い集計を持つ。付け忘れは「動くが誰でも叩ける」という形で出るため、型でも例外でも
現れない。
"""

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.admin_auth import require_admin_basic_auth
from app.api.admin_db_errors import ADMIN_PATH_PREFIX
from app.main import app
from tests.admin_auth import ADMIN_PASSWORD, ADMIN_USERNAME, AUTH_HEADERS, basic_auth_header

client = TestClient(app)


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


def test_every_admin_route_requires_basic_auth():
    admin_routes = _admin_routes()
    assert admin_routes, f"{ADMIN_PATH_PREFIX}配下のルートが1本も見つからない"
    unprotected = [route.path for route in admin_routes if not _depends_on_admin_auth(route)]

    assert unprotected == [], f"require_admin_basic_authが付いていない管理API: {unprotected}"


@pytest.mark.parametrize(
    ("admin_credentials", "headers"),
    [
        ((ADMIN_USERNAME, ADMIN_PASSWORD), {}),
        ((ADMIN_USERNAME, ADMIN_PASSWORD), {"Authorization": basic_auth_header(ADMIN_USERNAME, "wrong")}),
        (("", ""), AUTH_HEADERS),
    ],
    ids=["missing", "wrong", "unset"],
    indirect=["admin_credentials"],
)
def test_the_dependency_rejects_with_a_basic_auth_challenge(admin_credentials, headers):
    response = client.post("/api/admin/debug/mode", json={"enabled": True}, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="RideCompass admin"'
