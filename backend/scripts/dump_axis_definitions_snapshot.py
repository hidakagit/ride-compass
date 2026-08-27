"""現在のDB（DATABASE_URL）のaxis_definitions全行を、fresh bootstrap用スナップショット
ファイル（backend/fixtures/axis_definitions_snapshot.json）へダンプする（改善計画T361）。

軸定義の行データはaxis_admin API経由でのみ変更する運用（migrationでの変更は0022で
終了、`app/infrastructure/axis_definitions_snapshot.py`のモジュールdocstring参照）に
したため、API経由でDB（本番/dev）の軸を変更した後は、fresh bootstrap環境（CI・新規
開発環境・disaster recovery）にもその変更を反映させたければ、このスクリプトを手動実行して
スナップショットを再生成しコミットすること。自動化はしていない（意図的な手動運用、
モジュールdocstring参照）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\dump_axis_definitions_snapshot.py
    （環境変数DATABASE_URLで.envの値を上書き可能）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker  # noqa: E402

from app.infrastructure.axis_definition_repository import AxisDefinitionRepository  # noqa: E402
from app.infrastructure.axis_definitions_snapshot import dump_axis_definitions_snapshot  # noqa: E402
from app.infrastructure.migrate import run_as_cli_script  # noqa: E402


async def _dump(engine: AsyncEngine) -> int:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        count = await dump_axis_definitions_snapshot(AxisDefinitionRepository(session))
    print(f"dumped {count} axis definition(s) to fixtures/axis_definitions_snapshot.json")
    return 0


async def main() -> int:
    return await run_as_cli_script(_dump, failure_label="SNAPSHOT DUMP FAILED")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
