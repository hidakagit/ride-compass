"""CI専用: まっさらなDB（DATABASE_URL）へ基本スキーマ作成＋全migration適用を行う
（改善計画T350）。

`scripts/apply_migrations.py`は基本スキーマ作成（`create_tables()`）を行わない前提
（docstring参照）のため、テーブルが1つも無いCIのpostgresサービスコンテナに対しては
本番の唯一のブートストラップ経路（`app/batch/import_pbf.py`が使う
`create_tables()`→`apply_pending_migrations()`の順、`tests/test_migrate.py`の
ブートストラップテストが検証する経路と同一）を先に通す必要がある。CIの`api-contract`
ジョブ（`.github/workflows/ci.yml`）が`scripts/export_openapi.py`実行前に、
migration適用済みのDBからaxis_definitions（改善計画T350でDBが唯一の正本になった）を
読み込めるようにするためだけに使う。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\bootstrap_ci_db.py
    （環境変数DATABASE_URLで.envの値を上書き可能）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.infrastructure.migrate import apply_pending_migrations  # noqa: E402
from app.infrastructure.road_graph_repository import create_tables  # noqa: E402


async def main() -> int:
    engine = create_async_engine(settings.database_url)
    try:
        await create_tables(engine)
        applied = await apply_pending_migrations(engine)
    except Exception as exc:  # noqa: BLE001 CI失敗時に原因をそのまま表示する
        print(f"BOOTSTRAP FAILED: {exc!r}")
        return 1
    finally:
        await engine.dispose()

    print(f"bootstrapped schema, applied {len(applied)} migration(s): {', '.join(applied)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
