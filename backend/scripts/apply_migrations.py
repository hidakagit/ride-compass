"""DATABASE_URL（既定は.env）に対して、未適用のマイグレーション（backend/migrations/）を
すべて適用する（改善計画T17）。create_tables()相当の基本スキーマ作成は行わないため、
初回セットアップ時はcheck_db_connection.py等で接続確認後、アプリ起動やimport_pbf.pyの
実行（create_tables()を内部で呼ぶ）を先に行うこと。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\apply_migrations.py
    （環境変数DATABASE_URLで.envの値を上書き可能）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.infrastructure.migrate import apply_pending_migrations  # noqa: E402


async def main() -> int:
    engine = create_async_engine(settings.database_url)
    try:
        applied = await apply_pending_migrations(engine)
    except Exception as exc:  # noqa: BLE001 適用失敗の内容をそのまま表示する
        print(f"MIGRATION FAILED: {exc!r}")
        return 1
    finally:
        await engine.dispose()

    if applied:
        print(f"applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("no pending migrations (already up to date)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
