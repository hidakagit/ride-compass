"""最小マイグレーション機構（改善計画T17、decisions/pre-static-attributes-gate.md 決定3）。

`backend/migrations/` 配下の番号付きSQLファイルを、ファイル名の昇順で1回だけ適用する。
適用済みファイル名は `schema_migrations` テーブルへ記録し、以降の呼び出しでは再実行しない。
Alembicのような自動生成・downgradeは持たない最小構成（このプロジェクトの規模には過剰と
判断したため導入しない、decisions/pre-static-attributes-gate.md 決定3参照）。

1ファイル=1トランザクションで適用する（ファイル内の全文が成功するか、丸ごと未適用のまま
残るかのいずれかになり、一部だけ適用された中途半端な状態にはならない）。

SQLAlchemyのasyncpg方言はprepared statement経由でSQLを実行するため、';'区切りの複数文を
1回の`execute()`にまとめて渡すことができない（実機確認: `PostgresSyntaxError: cannot insert
multiple commands into a prepared statement`）。そのため単純な';'区切りで文単位に分割してから
1文ずつ`execute()`する。マイグレーションSQLは文字列リテラル内に';'を含まない単純なDDL/DMLのみを
想定しており、本モジュールは汎用SQLパーサーではない。
"""

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("ridecompass.migrate")

# backend/app/infrastructure/migrate.py から見て backend/migrations/
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _split_statements(sql: str) -> list[str]:
    return [chunk.strip() for chunk in sql.split(";") if chunk.strip()]


async def apply_pending_migrations(engine: AsyncEngine, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """未適用のマイグレーションをファイル名の昇順ですべて適用する。

    戻り値は今回新たに適用したファイル名の一覧（空リストなら全て適用済み、no-op）。
    `schema_migrations` テーブルが無ければ作成する。
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
        )
        applied = {
            row[0] for row in (await conn.execute(text("SELECT filename FROM schema_migrations"))).all()
        }

    pending = sorted(path for path in migrations_dir.glob("*.sql") if path.name not in applied)

    newly_applied: list[str] = []
    for path in pending:
        statements = _split_statements(path.read_text(encoding="utf-8"))
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
            await conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:filename)"),
                {"filename": path.name},
            )
        logger.info("migration applied filename=%s statements=%d", path.name, len(statements))
        newly_applied.append(path.name)

    return newly_applied


async def list_pending_migrations(engine: AsyncEngine, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """未適用マイグレーションのファイル名一覧を返す（読み取り専用、適用はしない）。

    改善計画T74の本番適用時、`route_designations`等を新設するmigration 0007自体が
    本番へ一度も適用されていなかった（devだけ整備されて本番が置き去りになる）ことが
    事後にしか発覚しなかった反省から、`/api/debug/db-status`が常時この状態を返せるように
    する（対策A）。`apply_pending_migrations`と違い`schema_migrations`テーブルを
    作成しない（GETリクエストでスキーマを変更しない）。テーブル自体が無い場合は
    全マイグレーションを未適用として扱う。
    """
    async with engine.connect() as conn:
        table_exists = await conn.scalar(text("SELECT to_regclass('schema_migrations') IS NOT NULL"))
        applied: set[str] = set()
        if table_exists:
            applied = {
                row[0] for row in (await conn.execute(text("SELECT filename FROM schema_migrations"))).all()
            }
    return sorted(path.name for path in migrations_dir.glob("*.sql") if path.name not in applied)
