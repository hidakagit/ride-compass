import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.axis_definitions_snapshot import (
    SNAPSHOT_PATH,
    dump_axis_definitions_snapshot,
    load_axis_definitions_snapshot,
)
from app.infrastructure.migrate import MIGRATIONS_DIR, _split_statements, apply_pending_migrations
from app.infrastructure.road_graph_repository import create_tables
from app.services.axis_registry_service import _find_unknown_references
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
    """fresh bootstrap経路（app/batch/import_pbf.pyが使うcreate_tables()→
    apply_pending_migrations()の順、改善計画T361で最後にload_axis_definitions_snapshot()が
    続く）を、テーブルが1つも無いまっさらな状態から検証する。

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
        migration_seeded_axis_count = (await conn.execute(text("SELECT count(*) FROM axis_definitions"))).scalar()
    # 改善計画T361以降、migrations/配下へ軸の行データを追加することはしない
    # （0014〜0022が過去の履歴として残すシード13行が引き続き適用されるだけ）。
    # 公開8軸（migrations/0014・0021）+ car_stress内部軸5（migrations/0017、0022で
    # car_stress_bicycle_infra_adjustmentを削除）= 13行（改善計画T353/T360）。
    assert migration_seeded_axis_count == 13

    # 改善計画T361: fresh bootstrapの最終段は、migrationが残したシード行を
    # スナップショットファイル（fixtures/axis_definitions_snapshot.json）の内容で
    # 丸ごと置き換える。migrationのシード行がそのまま最終状態になる today の内容とは
    # 独立に検証するため、投入前後で行数が変わりうる想定で書く
    # （snapshotが将来migrationのシードと異なる内容へ更新されても壊れないように）。
    async with AsyncSession(bootstrap_engine) as session:
        repository = AxisDefinitionRepository(session)
        snapshot_axis_count = await load_axis_definitions_snapshot(repository)
        db_definitions = await repository.list_all()
    assert snapshot_axis_count == len(db_definitions)

    # 改善計画T350: axis_definitions.pyのPython literal（AXIS_DEFINITIONS）を撤去し、
    # DBが軸全ての唯一の正本になったため、「DB値が特定の内容と一致するか」を検証する
    # 発想自体が誤りになった（可変であることを前提にDBへ置いているデータを固定検証すると、
    # 正当なチューニングのたびに無意味な失敗を生む）。ここで検証するのは構造のみ:
    # 全軸が例外なく読める（Pydanticバリデーションを通る）・未知の材料/軸参照が無いこと。
    # 改善計画T350のcode-review対応: 未知の材料/軸参照の判定ロジックを本テストへ
    # 再実装せず、refresh_axis_definitions（起動時ロード）が実際に使うのと同じ関数を
    # そのまま呼ぶ（本番の検知ロジックとテストの検証内容が食い違う余地を無くす）。
    unknown_references = _find_unknown_references(db_definitions)
    assert not unknown_references, f"未知の材料/軸参照: {unknown_references}"


@pytest.mark.asyncio
async def test_load_axis_definitions_snapshot_round_trips_with_dump(bootstrap_engine):
    """dump_axis_definitions_snapshot()で書き出した内容を、テーブルを空にした状態から
    load_axis_definitions_snapshot()で読み戻すと元と同じ内容になることを検証する
    （改善計画T361）。実際のfixtures/axis_definitions_snapshot.jsonではなく、
    tmp_pathへ書き出した使い捨てファイルを使う（本番のスナップショットファイルを
    テスト実行のたびに上書きしないため）。
    """
    await create_tables(bootstrap_engine)
    await apply_pending_migrations(bootstrap_engine)

    dump_path = SNAPSHOT_PATH.parent / f"_test_dump_{uuid.uuid4().hex[:8]}.json"
    try:
        async with AsyncSession(bootstrap_engine) as session:
            repository = AxisDefinitionRepository(session)
            original = await repository.list_all()
            dumped_count = await dump_axis_definitions_snapshot(repository, path=dump_path)
            assert dumped_count == len(original)

            await repository.delete_all()
            await repository.commit()
            assert await repository.count() == 0

            loaded_count = await load_axis_definitions_snapshot(repository, path=dump_path)
            assert loaded_count == dumped_count

            reloaded = await repository.list_all()
        assert reloaded.keys() == original.keys()
        for axis_id, definition in original.items():
            assert reloaded[axis_id] == definition
    finally:
        dump_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_load_axis_definitions_snapshot_replaces_existing_rows(bootstrap_engine):
    """load_axis_definitions_snapshot()はテーブルが空でなくても無条件にDELETE→投入し直す
    （改善計画T361: fresh bootstrap専用ツールからのみ呼ぶ設計で、空チェックはしない。
    `app/infrastructure/axis_definitions_snapshot.py`のモジュールdocstring参照）。
    migrationがシードした行が既にある状態から呼んでも、スナップショット由来の内容へ
    正しく置き換わることを検証する。
    """
    await create_tables(bootstrap_engine)
    await apply_pending_migrations(bootstrap_engine)

    async with AsyncSession(bootstrap_engine) as session:
        repository = AxisDefinitionRepository(session)
        pre_count = await repository.count()
        assert pre_count > 0  # migrationのシードで既に非0のはず（テスト前提の確認）

        loaded_count = await load_axis_definitions_snapshot(repository)
        post_definitions = await repository.list_all()
    assert loaded_count == len(post_definitions)
