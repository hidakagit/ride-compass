"""CI専用: DB（DATABASE_URL）を一旦まっさらにした上で基本スキーマ作成＋全migration適用＋
axis_definitionsスナップショット読み込みを行う（改善計画T350・T361）。

`scripts/apply_migrations.py`は基本スキーマ作成（`create_tables()`）を行わない前提
（docstring参照）のため、テーブルが1つも無いCIのpostgresサービスコンテナに対しては
fresh bootstrap経路（`create_tables()`→`apply_pending_migrations()`→
`load_axis_definitions_snapshot()`、`tests/test_migrate.py`のブートストラップテストが
検証する経路と同一、`app/infrastructure/axis_definitions_snapshot.py`参照）を先に
通す必要がある。CIの`backend`ジョブ（`.github/workflows/ci.yml`）が
`scripts/export_openapi.py`実行前に、migration適用済みのDBからaxis_definitions
（改善計画T350でDBが唯一の正本になった）を読み込めるようにするためだけに使う。

**実行前に全テーブルをDROPする（改善計画T350のcode-review対応で追加）**: このスクリプトは
同じジョブ内でpytest（`backend`ジョブ、PostGIS統合テスト込み）を実行した**後**に呼ぶ
運用（`.github/workflows/ci.yml`のコメント参照）。pytestの`road_graph_session`
フィクスチャ（`tests/conftest.py`）は、それを使う各テストの後始末として
`Base.metadata.sorted_tables`の全テーブルを毎回TRUNCATEする——このTRUNCATEは
`axis_definitions`テーブルの行も含めて消すが、migration適用済みかどうかを記録する
`schema_migrations`テーブル（`Base.metadata`外、生SQLで作成）はTRUNCATE対象外のまま残る。
そのため、単純に`apply_pending_migrations()`を呼ぶだけだと「`schema_migrations`は
適用済みと記録しているが実データ（axis_definitionsの行）は別テストのTRUNCATEで
消えている」という不整合が起こりうる（ローカルで実際に再現・確認済み）。CI専用の
使い捨てコンテナに対してのみ実行するスクリプトのため、まっさらな状態からの再構築
（`tests/test_migrate.py`の`_drop_all_public_tables`と同じ方針）で、この不整合を
構造的に起こらないようにする（改善計画T361以降は`load_axis_definitions_snapshot()`が
どのみち無条件にテーブルを空にしてから投入し直すため、この経路のTRUNCATE耐性は
二重の安全策になっている）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\bootstrap_ci_db.py
    （環境変数DATABASE_URLで.envの値を上書き可能）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker  # noqa: E402

from app.infrastructure.axis_definition_repository import AxisDefinitionRepository  # noqa: E402
from app.infrastructure.axis_definitions_snapshot import load_axis_definitions_snapshot  # noqa: E402
from app.infrastructure.migrate import apply_pending_migrations, run_as_cli_script  # noqa: E402
from app.infrastructure.road_graph_repository import create_tables  # noqa: E402


async def _drop_all_public_tables(engine: AsyncEngine) -> None:
    """publicスキーマの既存テーブルを（PostGIS付属のspatial_ref_sysを除いて）全てDROPする
    （`tests/test_migrate.py: _drop_all_public_tables`と同じ方針）。"""
    async with engine.begin() as conn:
        rows = (await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))).all()
        for (table_name,) in rows:
            if table_name == "spatial_ref_sys":
                continue  # PostGIS拡張付属のテーブル。DROPすると拡張自体が壊れる。
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))


async def _bootstrap(engine: AsyncEngine) -> int:
    await _drop_all_public_tables(engine)
    await create_tables(engine)
    applied = await apply_pending_migrations(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        axis_count = await load_axis_definitions_snapshot(AxisDefinitionRepository(session))
    print(
        f"bootstrapped schema, applied {len(applied)} migration(s): {', '.join(applied)}; "
        f"loaded {axis_count} axis definition(s) from snapshot"
    )
    return 0


async def main() -> int:
    return await run_as_cli_script(_bootstrap, failure_label="BOOTSTRAP FAILED")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
