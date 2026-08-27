"""新規環境（新しいdev機・disaster recovery等）向けの唯一のブートストラップ経路を通しで
実行する（改善計画T361）。DATABASE_URLが指すDBに対し、以下を順に行う:

    1. create_tables()      — 基本スキーマ作成（冪等）
    2. apply_pending_migrations() — 未適用migrationの適用（冪等）
    3. load_axis_definitions_snapshot() — axis_definitionsをスナップショットファイル
       （fixtures/axis_definitions_snapshot.json）の内容で丸ごと置き換える

1・2は`app/batch/import_pbf.py`が既存データへの取込のたびに毎回行っている処理と同じ
（冪等なため繰り返し実行しても安全）。3だけは無条件に「テーブルを空にしてから
投入し直す」動作のため、**まっさらなDBに対してのみ**実行すること——既に稼働中で
axis_admin API経由の変更が入っているDBに対して実行すると、その変更が消える
（`app/infrastructure/axis_definitions_snapshot.py`のモジュールdocstring参照）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\bootstrap_fresh_db.py
    （環境変数DATABASE_URLで.envの値を上書き可能。新規環境のDATABASE_URLを指すこと）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker  # noqa: E402

from app.infrastructure.axis_definition_repository import AxisDefinitionRepository  # noqa: E402
from app.infrastructure.axis_definitions_snapshot import load_axis_definitions_snapshot  # noqa: E402
from app.infrastructure.migrate import apply_pending_migrations, run_as_cli_script  # noqa: E402
from app.infrastructure.road_graph_repository import create_tables  # noqa: E402


async def _bootstrap(engine: AsyncEngine) -> int:
    await create_tables(engine)
    applied = await apply_pending_migrations(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        axis_count = await load_axis_definitions_snapshot(AxisDefinitionRepository(session))
    print(
        f"bootstrapped schema, applied {len(applied)} migration(s), "
        f"loaded {axis_count} axis definition(s) from snapshot"
    )
    return 0


async def main() -> int:
    return await run_as_cli_script(_bootstrap, failure_label="BOOTSTRAP FAILED")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
