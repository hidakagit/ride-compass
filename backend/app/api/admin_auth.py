"""管理API共通の認可境界（改善計画T221 Stage D、Basic認証化はT272）。

元は`axis_admin.py`にのみ定義されていたが、T378（debug_modeの管理API化）で
2つ目の管理ルーターが同じ認可を必要としたため、複製を避けてここへ切り出した。
"""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

_basic_auth = HTTPBasic(realm="RideCompass admin", auto_error=False)


async def require_admin_basic_auth(credentials: HTTPBasicCredentials | None = Depends(_basic_auth)) -> None:
    """管理APIの認可境界（改善計画T221 Stage D、Basic認証化は改善計画T272）。

    HTTP Basic認証（環境変数`ADMIN_BASIC_AUTH_USERNAME`/`ADMIN_BASIC_AUTH_PASSWORD`、
    settings参照）。以前は共有トークンheader（X-Admin-Token）による簡易保護だったが、
    T272でユーザー方針（2026-08-24: 「将来的にはアカウント制としたいが、現状は動作確認・
    研究用のためBasic認証として後から拡張する」）に基づきBasic認証へ置き換えた。
    `secrets.compare_digest`でタイミング攻撃を避ける（ユーザー名・パスワードどちらも）。
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
