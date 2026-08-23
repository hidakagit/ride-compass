import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.infrastructure.migrate import _split_statements, apply_pending_migrations
from tests.conftest import TEST_DATABASE_URL

# xdist_group="postgis": migration_engineは同じridecompass_test DBに対して
# `CREATE TABLE IF NOT EXISTS schema_migrations`を実行する。他のpostgis系テストと
# 別workerで並走すると、IF NOT EXISTSのチェックと作成がPostgres側で並行実行時に
# 完全にはアトミックでないため、pg_type カタログのユニーク制約違反で失敗しうる
# （docs/testing.md参照）。
pytestmark = pytest.mark.xdist_group(name="postgis")


def test_split_statements_ignores_blank_and_trailing_semicolon():
    sql = """
    CREATE TABLE a (x int);

    CREATE TABLE b (y int);
    """
    assert _split_statements(sql) == ["CREATE TABLE a (x int)", "CREATE TABLE b (y int)"]


def test_split_statements_empty_input_returns_empty_list():
    assert _split_statements("   \n  ") == []


@pytest_asyncio.fixture
async def migration_engine():
    """ridecompass_test DBに対する素のAsyncEngine。PostGIS統合テストと同じ接続先・
    skip方針を使う（conftest.pyのroad_graph_sessionとは別に、schema_migrations専用の
    後始末を行うため独自にengineだけ用意する）。
    """
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"ridecompass_test DBに接続できないためスキップ: {exc}")
    yield engine
    await engine.dispose()


async def _cleanup(engine, table_names: list[str], migration_filenames: list[str]) -> None:
    async with engine.begin() as conn:
        for table_name in table_names:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        if migration_filenames:
            await conn.execute(
                text("DELETE FROM schema_migrations WHERE filename = ANY(:filenames)"),
                {"filenames": migration_filenames},
            )


@pytest.mark.asyncio
async def test_apply_pending_migrations_applies_new_file_and_records_it(tmp_path, migration_engine):
    probe_table = f"_migrate_test_{uuid.uuid4().hex[:8]}"
    filename = f"9001_{probe_table}.sql"
    (tmp_path / filename).write_text(f"CREATE TABLE {probe_table} (id int);", encoding="utf-8")

    try:
        applied = await apply_pending_migrations(migration_engine, migrations_dir=tmp_path)
        assert applied == [filename]

        async with migration_engine.connect() as conn:
            exists = (
                await conn.execute(text("SELECT to_regclass(:name)"), {"name": probe_table})
            ).scalar()
            assert exists == probe_table

            recorded = (
                await conn.execute(
                    text("SELECT filename FROM schema_migrations WHERE filename = :f"), {"f": filename}
                )
            ).scalar()
            assert recorded == filename
    finally:
        await _cleanup(migration_engine, [probe_table], [filename])


@pytest.mark.asyncio
async def test_apply_pending_migrations_is_idempotent_on_second_call(tmp_path, migration_engine):
    probe_table = f"_migrate_test_{uuid.uuid4().hex[:8]}"
    filename = f"9001_{probe_table}.sql"
    (tmp_path / filename).write_text(f"CREATE TABLE {probe_table} (id int);", encoding="utf-8")

    try:
        first = await apply_pending_migrations(migration_engine, migrations_dir=tmp_path)
        second = await apply_pending_migrations(migration_engine, migrations_dir=tmp_path)
        assert first == [filename]
        assert second == []  # 既に適用済みのため再実行しない（DDLの再実行エラーにもならない）
    finally:
        await _cleanup(migration_engine, [probe_table], [filename])


@pytest.mark.asyncio
async def test_apply_pending_migrations_skips_already_applied_and_runs_rest_in_order(
    tmp_path, migration_engine
):
    suffix = uuid.uuid4().hex[:8]
    already_applied_table = f"_migrate_test_a_{suffix}"
    pending_table = f"_migrate_test_b_{suffix}"
    already_applied_filename = f"9001_{already_applied_table}.sql"
    pending_filename = f"9002_{pending_table}.sql"

    (tmp_path / already_applied_filename).write_text(
        f"CREATE TABLE {already_applied_table} (id int);", encoding="utf-8"
    )
    (tmp_path / pending_filename).write_text(f"CREATE TABLE {pending_table} (id int);", encoding="utf-8")

    try:
        # 9001は「過去のデプロイで既に適用済み」を模擬するため、SQLを実行せず記録だけ行う。
        async with migration_engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
            )
            await conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f)"),
                {"f": already_applied_filename},
            )

        applied = await apply_pending_migrations(migration_engine, migrations_dir=tmp_path)

        assert applied == [pending_filename]  # 既適用の9001は再実行されない

        async with migration_engine.connect() as conn:
            already_applied_table_exists = (
                await conn.execute(text("SELECT to_regclass(:name)"), {"name": already_applied_table})
            ).scalar()
            pending_table_exists = (
                await conn.execute(text("SELECT to_regclass(:name)"), {"name": pending_table})
            ).scalar()
            assert already_applied_table_exists is None  # 記録だけで実行はされていない
            assert pending_table_exists == pending_table
    finally:
        await _cleanup(
            migration_engine,
            [already_applied_table, pending_table],
            [already_applied_filename, pending_filename],
        )
