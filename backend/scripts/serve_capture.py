"""撮影の道具（`frontend/scripts/capture.mjs`の`--backend`）のために、この作業ツリーのbackendをDBを読まずに起動する。

本体（`app/main.py: app`）の起動の段はDBの軸定義を読み、読めなければ起動しない。担当のランナーのDBは空なので、起動の段だけを
HTTPの接続を閉じるだけのものに替え、ルーターとミドルウェアは本体のまま使う。DBを読む経路は失敗するので、撮影の道具は
選んだパスの頭（DBを読まないタイルの中継等）だけをここへ向け、残りは`--api`のbackendへ向ける。

    python backend/scripts/serve_capture.py <ポート>
"""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.http_client import close_all_http_clients
from app.main import app


@asynccontextmanager
async def _without_db(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_all_http_clients()


app.router.lifespan_context = _without_db

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]))
