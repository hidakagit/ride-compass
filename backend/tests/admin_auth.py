"""管理画面API（`require_admin_basic_auth`）のテストが共有するBasic認証の材料。

認証情報そのものは`admin_credentials`フィクスチャ（conftest.py）が`settings`へ入れる。
ここはヘッダーの組み立てだけを持つ。
"""

import base64

ADMIN_USERNAME = "admin-user"
ADMIN_PASSWORD = "secret-password"


def basic_auth_header(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


AUTH_HEADERS = {"Authorization": basic_auth_header(ADMIN_USERNAME, ADMIN_PASSWORD)}
