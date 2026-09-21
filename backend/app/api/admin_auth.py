"""管理API共通の認可境界。管理ルーターはいずれもこれを`Depends`で挟む。"""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

_basic_auth = HTTPBasic(realm="RideCompass admin", auto_error=False)


async def require_admin_basic_auth(credentials: HTTPBasicCredentials | None = Depends(_basic_auth)) -> None:
    """資格情報が設定値と一致しなければ401を送出する。

    資格情報が未設定（既定の空文字）の環境では常に拒否する——うっかり無保護公開しない。
    `auto_error=False`でHTTPBasic自体の自動401を止め、資格情報の有無に関わらずこの関数が
    `WWW-Authenticate`付きの401を返す（ブラウザの標準Basic認証ダイアログを起動させる）。
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
