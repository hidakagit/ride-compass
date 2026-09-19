import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx
import pytest
from sqlalchemy import literal_column, select, text

from app.batch import _common
from app.batch._common import (
    asyncpg_dsn,
    count_targets,
    download_to_path,
    reap_stale_running_import_runs,
    status_count,
    stream_id_chunks,
)
from tests.conftest import postgis_database_url


def test_asyncpg_dsn_normalizes_driver_and_ssl_param():
    assert (
        asyncpg_dsn("postgresql+asyncpg://u:p@db.example.supabase.co:5432/postgres?ssl=require")
        == "postgresql://u:p@db.example.supabase.co:5432/postgres?sslmode=require"
    )
    # ローカル（ssl指定なし）はドライバ指定の除去のみ
    assert (
        asyncpg_dsn("postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass")
        == "postgresql://ridecompass:ridecompass@localhost:5432/ridecompass"
    )


def test_status_count_parses_asyncpg_command_status():
    assert status_count("INSERT 0 123") == 123
    assert status_count("TRUNCATE TABLE") == 0


# 改善計画T467: reap_stale_running_import_runsはosm_import_runs等の実テーブルへのUPDATE...
# RETURNINGを伴うためridecompass_test DBへの実接続が要る（road_graph_session/
# road_graph_repositoryフィクスチャ、docs/testing.mdパターン2）。接続できない環境では
# フィクスチャがpytest.skip()する。
class TestReapStaleRunningImportRuns:
    pytestmark = [
        pytest.mark.asyncio(loop_scope="module"),
        pytest.mark.xdist_group(name="postgis"),
        pytest.mark.postgis,
    ]

    async def _insert_run(self, conn: asyncpg.Connection, *, started_at: datetime, status: str) -> int:
        return await conn.fetchval(
            "INSERT INTO osm_import_runs (pbf_name, profile_hash, status, started_at) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            "test.pbf", "test-hash", status, started_at,
        )

    async def test_marks_old_running_rows_as_failed(self, road_graph_repository, road_graph_session):
        conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
        try:
            stale_id = await self._insert_run(
                conn, started_at=datetime.now(timezone.utc) - timedelta(hours=12), status="running"
            )

            reaped = await reap_stale_running_import_runs(conn, "osm_import_runs")

            assert reaped == 1
            row = await conn.fetchrow("SELECT status, finished_at FROM osm_import_runs WHERE id = $1", stale_id)
            assert row["status"] == "failed"
            assert row["finished_at"] is not None
        finally:
            await conn.close()

    async def test_leaves_recent_running_rows_untouched(self, road_graph_repository, road_graph_session):
        conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
        try:
            recent_id = await self._insert_run(conn, started_at=datetime.now(timezone.utc), status="running")

            reaped = await reap_stale_running_import_runs(conn, "osm_import_runs")

            assert reaped == 0
            row = await conn.fetchrow("SELECT status FROM osm_import_runs WHERE id = $1", recent_id)
            assert row["status"] == "running"
        finally:
            await conn.close()

    async def test_leaves_succeeded_rows_untouched(self, road_graph_repository, road_graph_session):
        conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
        try:
            succeeded_id = await self._insert_run(
                conn, started_at=datetime.now(timezone.utc) - timedelta(hours=12), status="succeeded"
            )

            reaped = await reap_stale_running_import_runs(conn, "osm_import_runs")

            assert reaped == 0
            row = await conn.fetchrow("SELECT status FROM osm_import_runs WHERE id = $1", succeeded_id)
            assert row["status"] == "succeeded"
        finally:
            await conn.close()


_logger = logging.getLogger("test.batch_common")


class TestDownloadToPath:
    async def test_skips_download_when_dest_already_exists(self, tmp_path):
        dest = tmp_path / "existing.csv"
        dest.write_text("cached")

        async with httpx.AsyncClient() as client:
            result = await download_to_path(
                client, "https://example.invalid/never-called.csv", dest, logger=_logger, label="テスト", context="x=1"
            )

        assert result == dest
        assert dest.read_text() == "cached"

    async def test_downloads_and_replaces_part_file(self, tmp_path):
        dest = tmp_path / "downloaded.csv"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"hello")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            result = await download_to_path(
                client, "https://example.invalid/data.csv", dest, logger=_logger, label="テスト", context="x=1"
            )

        assert result == dest
        assert dest.read_bytes() == b"hello"
        assert not dest.with_suffix(dest.suffix + ".part").exists()

    async def test_returns_none_and_cleans_up_part_file_on_http_error(self, tmp_path):
        dest = tmp_path / "failing.csv"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            result = await download_to_path(
                client, "https://example.invalid/missing.csv", dest, logger=_logger, label="テスト", context="x=1"
            )

        assert result is None
        assert not dest.exists()
        assert not dest.with_suffix(dest.suffix + ".part").exists()


# precompute系4本が対象IDの取得に使う共有実装。サーバーサイドカーソルの挙動（分割・
# 順序・空集合）はSQLAlchemy＋asyncpgの実接続でしか確認できないため、road_graph_session
# フィクスチャ経由の実DBテストにする（docs/testing.mdパターン2、接続できない環境では
# フィクスチャがpytest.skip()する）。検証対象はカーソルの読み進め方であってテーブルの
# 内容ではないため、行は`generate_series`で用意し実テーブルへは書き込まない。
class TestStreamIdChunks:
    pytestmark = [
        pytest.mark.asyncio(loop_scope="module"),
        pytest.mark.xdist_group(name="postgis"),
        pytest.mark.postgis,
    ]

    def _session_factory(self, road_graph_session):
        @asynccontextmanager
        async def _factory():
            yield road_graph_session

        return _factory

    def _series_stmt(self, count: int):
        return (
            select(literal_column("i"))
            .select_from(text(f"generate_series(1, {count}) AS t(i)"))
            .order_by(literal_column("i"))
        )

    async def test_yields_fixed_size_chunks_preserving_statement_order(self, road_graph_session):
        chunks = [
            chunk
            async for chunk in stream_id_chunks(self._session_factory(road_graph_session), self._series_stmt(5), 2)
        ]

        assert chunks == [[1, 2], [3, 4], [5]]

    async def test_yields_nothing_when_no_rows_match(self, road_graph_session):
        stmt = self._series_stmt(1).where(literal_column("i") < 0)

        chunks = [chunk async for chunk in stream_id_chunks(self._session_factory(road_graph_session), stmt, 2)]

        assert chunks == []

    async def test_count_targets_matches_streamed_row_count(self, road_graph_session):
        stmt = self._series_stmt(7)
        factory = self._session_factory(road_graph_session)

        # count_targetsはORDER BYを外す（件数に影響しないソートのコストを避ける）。
        total = await count_targets(factory, stmt)
        streamed = sum([len(chunk) async for chunk in stream_id_chunks(factory, stmt, 3)])

        assert total == 7
        assert streamed == total


class TestDerivedDataRevisionBump:
    """バッチが書いたあと、派生データの世代（`derived_data_meta.revision`）が進むこと。

    進まないと、backendがディスクへ既にキャッシュ済みの材料を「作り直されていない」と
    判断して古いまま復元し続ける（未訪問のタイルだけが新しい値になるため気づきにくい）。
    """

    async def _run(self, monkeypatch, *, code: int, dry_run: bool) -> list[str]:
        """世代更新のためにDBへ触りにいったかを記録して返す。"""
        touched: list[str] = []

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        @asynccontextmanager
        async def fake_session_factory(database_url):
            touched.append("session_factory")
            yield lambda: FakeSession()

        async def fake_bump(session):
            touched.append("bump")
            return 42

        monkeypatch.setattr(_common, "batch_session_factory", fake_session_factory)
        monkeypatch.setattr(_common.derived_data_meta, "bump_revision", fake_bump)

        async def body() -> int:
            return code

        result = await _common.with_derived_data_revision_bump(
            body(), database_url=None, dry_run=dry_run
        )
        assert result == code
        return touched

    @pytest.mark.asyncio
    async def test_successful_run_bumps(self, monkeypatch):
        assert "bump" in await self._run(monkeypatch, code=0, dry_run=False)

    @pytest.mark.asyncio
    async def test_dry_run_does_not_bump(self, monkeypatch):
        # DBを書いていないため、世代を進めるとキャッシュを無駄に捨てるだけになる。
        assert await self._run(monkeypatch, code=0, dry_run=True) == []

    @pytest.mark.asyncio
    async def test_failed_run_does_not_bump(self, monkeypatch):
        assert await self._run(monkeypatch, code=1, dry_run=False) == []

    @pytest.mark.asyncio
    async def test_bump_failure_does_not_change_exit_code(self, monkeypatch):
        # データは既に書けている。世代の更新に失敗しても、次のTTLでの確認で回復する。
        @asynccontextmanager
        async def exploding_session_factory(database_url):
            raise RuntimeError("DBに触れない")
            yield  # pragma: no cover

        monkeypatch.setattr(_common, "batch_session_factory", exploding_session_factory)

        async def body() -> int:
            return 0

        result = await _common.with_derived_data_revision_bump(body(), database_url=None, dry_run=False)

        assert result == 0


def test_every_batch_entry_point_bumps_the_derived_data_revision():
    """DBを書くバッチの入口が、世代を進める経路を通ること。

    新しいバッチが素の`asyncio.run(run(...))`で書かれると、そのバッチの後だけ材料が古い
    まま残る——症状が局所的で、次に誰かが同じ範囲を走るまで現れない。ここで入口の形を
    固定して、書き忘れを足した時点で止める。
    """
    batch_dir = Path(_common.__file__).parent
    # データを書かないモジュール（取込プロファイルの読み込み・PBFの読み取り）は対象外。
    not_writers = {"_common.py", "__init__.py", "profile.py", "pbf_source.py"}
    missing = []
    for path in sorted(batch_dir.glob("*.py")):
        if path.name in not_writers:
            continue
        source = path.read_text(encoding="utf-8")
        if "asyncio.run(" not in source:
            continue
        if "with_derived_data_revision_bump" in source or "run_simple_batch_cli" in source:
            continue
        missing.append(path.name)
    assert missing == []
