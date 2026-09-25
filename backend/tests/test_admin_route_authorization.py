"""管理API（`/api/admin/`配下）の認可境界。

2つに分けて見る:
- **全ルートが`require_admin_basic_auth`を依存に持つこと**——全ルート走査。新しく足した
  エンドポイントが認可を付け忘れたことを、口ごとのテストでは検知できない。
  `test_cache_policy.py`が対応表の網羅性を全ルート走査で見るのと同じ形を、認可にも置く。
- **その依存が資格情報の欠落・不一致・未設定を401で拒むこと**——依存を持つ口ならどれで
  確かめても同じなので、1つの口で見る。

口ごとに「認証なしで401」を確かめるテストは、この2つの組で足りるため置かない。

管理APIは全利用者へ影響する操作（タイルキャッシュの全消去・軸定義の変更）と、全表走査を
伴う重い集計を持つ。付け忘れは「動くが誰でも叩ける」という形で出るため、型でも例外でも
現れない。
"""

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.admin_auth import require_admin_basic_auth
from app.config import settings
from app.main import app
from tests.admin_auth import ADMIN_USERNAME, AUTH_HEADERS, basic_auth_header

ADMIN_PATH_PREFIX = "/api/admin/"

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


def test_the_scan_is_not_empty():
    # 管理APIが1本も見つからない＝パスの前置きが変わった等でこの検査が空回りしている。
    assert _admin_routes(), f"{ADMIN_PATH_PREFIX}配下のルートが1本も見つからない"


def test_every_admin_route_requires_basic_auth():
    unprotected = [route.path for route in _admin_routes() if not _depends_on_admin_auth(route)]

    assert unprotected == [], f"require_admin_basic_authが付いていない管理API: {unprotected}"


def test_update_mode_rejects_missing_credentials(admin_credentials):
    response = client.post("/api/admin/debug/mode", json={"enabled": True})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="RideCompass admin"'


def test_update_mode_rejects_wrong_credentials(admin_credentials):
    response = client.post(
        "/api/admin/debug/mode",
        json={"enabled": True},
        headers={"Authorization": basic_auth_header(ADMIN_USERNAME, "wrong")},
    )

    assert response.status_code == 401


def test_update_mode_rejects_any_credentials_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "admin_basic_auth_username", "")
    monkeypatch.setattr(settings, "admin_basic_auth_password", "")

    response = client.post("/api/admin/debug/mode", json={"enabled": True}, headers=AUTH_HEADERS)

    assert response.status_code == 401
