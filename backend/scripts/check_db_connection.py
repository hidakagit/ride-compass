"""DATABASE_URL（既定は.env）への接続確認。ホスト・PostgreSQLバージョン・PostGIS拡張の
有無・DBサイズを表示する。Oracle Cloud VM等のリモートDBへ取込む前の疎通チェック用
（改善計画T263で本番はOracle Cloud VMへ移行済み）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\check_db_connection.py
    （環境変数DATABASE_URLで.envの値を上書き可能）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402


async def main() -> int:
    url = settings.database_url
    host = url.split("@")[1].split("/")[0] if "@" in url else "(unknown)"
    print(f"host: {host}")

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            print("SELECT 1 ->", (await conn.execute(text("SELECT 1"))).scalar())
            print("server_version:", (await conn.execute(text("SHOW server_version"))).scalar())
            row = (
                await conn.execute(
                    text(
                        "SELECT default_version, installed_version "
                        "FROM pg_available_extensions WHERE name='postgis'"
                    )
                )
            ).first()
            print("postgis (available, installed):", row)
            size = (await conn.execute(text("SELECT pg_database_size(current_database())"))).scalar()
            print(f"db_size_mb: {size / 1e6:.0f}")
        return 0
    except Exception as exc:  # noqa: BLE001 疎通チェックの失敗内容をそのまま表示する
        print(f"CONNECTION FAILED: {exc!r}")
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
