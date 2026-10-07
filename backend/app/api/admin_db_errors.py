"""管理API（`/api/admin/...`）のDB障害を、どの口でも503で返すアプリ単位の例外の扱い。

管理APIは空やフォールバック値へ倒さない——軸スタジオの編集画面にフォールバック値を出すと
気付かないままDBの実データを上書きし、診断用の集計を空で返すと「問題なし」に見える。
捕まえるのはDB障害として扱う例外（`DB_UNAVAILABLE_ERRORS`）だけで、実装の誤り
（`TypeError`等）は500のまま表へ出す。管理API以外の経路は、DB障害を自分で空へ倒すか
500として表へ出すかを口ごとに決めているため、ここでは送り直して今の500の経路
（アクセスログのスタックトレースと`unhandled_exception_handler`）へ渡す。
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.infrastructure.database import DB_UNAVAILABLE_ERRORS

ADMIN_PATH_PREFIX = "/api/admin/"


async def admin_db_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    if not request.url.path.startswith(ADMIN_PATH_PREFIX):
        raise exc
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "DBへのアクセスに失敗しました（DB接続と、テーブルが作られているかを確認してください）"},
    )


def install_admin_db_unavailable_handler(app: FastAPI) -> None:
    for error_type in DB_UNAVAILABLE_ERRORS:
        app.add_exception_handler(error_type, admin_db_unavailable_handler)
