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

from sqlalchemy.ext.asyncio import AsyncEngine  # noqa: E402

from app.infrastructure.migrate import apply_pending_migrations, run_as_cli_script  # noqa: E402


async def _apply(engine: AsyncEngine) -> int:
    applied = await apply_pending_migrations(engine)
    if applied:
        print(f"applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("no pending migrations (already up to date)")
    return 0


async def main() -> int:
    return await run_as_cli_script(_apply, failure_label="MIGRATION FAILED")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
