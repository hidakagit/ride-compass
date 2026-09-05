"""管理API共通の認可境界。`axis_admin.py`・`debug_admin.py`の複数の管理ルーターが
共有する（複製を避けるためここへ切り出してある）。
"""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

_basic_auth = HTTPBasic(realm="RideCompass admin", auto_error=False)


async def require_admin_basic_auth(credentials: HTTPBasicCredentials | None = Depends(_basic_auth)) -> None:
    """管理APIの認可境界。

    HTTP Basic認証（環境変数`ADMIN_BASIC_AUTH_USERNAME`/`ADMIN_BASIC_AUTH_PASSWORD`、
    settings参照）。`secrets.compare_digest`でタイミング攻撃を避ける（ユーザー名・
    パスワードどちらも）。
    未設定（既定""）の環境では常に拒否し、うっかり無保護公開しない。
    認可判定をこの1関数（FastAPI Dependency）へ集約しているため、将来アカウント制へ
    差し替える際もこの関数の中身だけを変えればよい（Stage D設計の継続）。
    401はブラウザの標準Basic認証ダイアログを起動させるため`WWW-Authenticate`ヘッダを
    付ける（`auto_error=False`でHTTPBasic自体の自動401を無効化し、常にこの関数が
    ヘッダ付きの401を明示的に返す——資格情報の有無に関わらず一貫した応答にするため）。
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="管理APIへのアクセスが許可されていません",
        headers={"WWW-Authenticate": 'Basic realm="RideCompass admin"'},
    )
    if not settings.admin_basic_auth_username or not settings.admin_basic_auth_password:
        raise unauthorized
    if credentials is None:
        raise unauthorized
    username_ok = secrets.compare_digest(credentials.username, settings.admin_basic_auth_username)
    password_ok = secrets.compare_digest(credentials.password, settings.admin_basic_auth_password)
    if not (username_ok and password_ok):
        raise unauthorized
