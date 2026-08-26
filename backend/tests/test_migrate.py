import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.migrate import MIGRATIONS_DIR, _split_statements, apply_pending_migrations
from app.infrastructure.road_graph_repository import create_tables
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


async def _drop_all_public_tables(engine) -> None:
    """publicスキーマの既存テーブルを（PostGIS付属のspatial_ref_sysを除いて）全てDROPする。

    本番の唯一のブートストラップ経路（create_tables→apply_pending_migrations）は
    「テーブルが1つも無いまっさらな状態」から始まることが前提のため、フィクスチャの
    実行順序（他のテストが先にschema_migrations等を作っている可能性）に依らずこの前提を
    保証する（タスク指示: まっさらな状態を保証できない場合は冒頭で明示的に全DROPする）。
    """
    async with engine.begin() as conn:
        rows = (
            await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        ).all()
        for (table_name,) in rows:
            if table_name == "spatial_ref_sys":
                continue  # PostGIS拡張付属のテーブル。DROPすると拡張自体が壊れる。
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))


@pytest_asyncio.fixture
async def bootstrap_engine():
    """まっさらな状態からのブートストラップ経路検証専用engine。

    migration_engineフィクスチャと同じTEST_DATABASE_URLへ接続するが、テスト開始時に
    publicスキーマの既存テーブルを明示的に全てDROPしてから使う点が異なる
    （create_tables()→apply_pending_migrations()の一連の流れを「テーブルが1つも無い」
    前提から検証するため）。
    """
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"ridecompass_test DBに接続できないためスキップ: {exc}")

    await _drop_all_public_tables(engine)

    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_bootstrap_from_empty_db_create_tables_then_migrate_succeeds(bootstrap_engine):
    """本番の唯一のブートストラップ経路（app/batch/import_pbf.pyが使う
    create_tables()→apply_pending_migrations()の順）を、テーブルが1つも無いまっさらな
    状態から検証する。

    road_graph_engineフィクスチャ（tests/conftest.py）はBase.metadata.create_allのみで
    migrationを一度も経由せず、この組み合わせを検証する自動テストがCIに存在しなかった
    ことが、migration 0010〜0020のIF NOT EXISTS欠如という同一バグが2回連続で発生した
    直接の原因だった（改善計画T321・T328、backend/scripts/verify_postgis_phase0.py
    ステップ0〜1相当をpytest化する）。
    """
    await create_tables(bootstrap_engine)  # 例外なく完了すること
    applied = await apply_pending_migrations(bootstrap_engine)  # 例外なく完了すること

    expected_filenames = {path.name for path in MIGRATIONS_DIR.glob("*.sql")}
    assert expected_filenames, "migrations/配下にファイルが見つからない（テスト前提が崩れている）"
    assert set(applied) == expected_filenames  # migrations/配下の全SQLファイルが適用された

    second_applied = await apply_pending_migrations(bootstrap_engine)
    assert second_applied == []  # 2回目は空リスト（冪等、再適用しない）

    async with bootstrap_engine.connect() as conn:
        axis_count = (await conn.execute(text("SELECT count(*) FROM axis_definitions"))).scalar()
    # 公開8軸（migrations/0014・0021）+ car_stress内部軸6（migrations/0017）= 14行
    assert axis_count == 14

    # 改善計画T348: migrationを通してDBへ投入した組み込み軸14件の内容が、
    # domain/axis_definitions.py: AXIS_DEFINITIONS（Python正本）と完全一致することを
    # 検証する。手書きmigrationがPython側の変更に追従し忘れる（T347で実際に発覚した、
    # migration 0017のshape_paramsがT336時点のcar_stress_bicycle_infra_adjustment再設計に
    # 追従せず旧categorical形のまま取り残されていた実例）ドリフトを、コミット前ではなく
    # ここで機械的に検知する。
    async with AsyncSession(bootstrap_engine) as session:
        db_definitions = await AxisDefinitionRepository(session).list_all()
    assert set(db_definitions) == set(AXIS_DEFINITIONS)
    for axis_id, expected in AXIS_DEFINITIONS.items():
        assert db_definitions[axis_id] == expected, (
            f"axis_id={axis_id}: DBの内容がaxis_definitions.pyの定義と一致しません"
            "（対応するmigrationの手書き内容が古い可能性があります）"
        )
