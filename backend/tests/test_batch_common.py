import logging
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.batch import _common
from app.batch._common import asyncpg_dsn


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


_logger = logging.getLogger("test.batch_common")


class TestDerivedDataRevisionBump:
    """バッチが書いたあと、派生データの世代（`derived_data_meta.revision`）が進むこと。"""

    async def _run(self, monkeypatch, *, code: int) -> list[str]:
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

        result = await _common.with_derived_data_revision_bump(body(), database_url=None)
        assert result == code
        return touched

    @pytest.mark.asyncio
    async def test_successful_run_bumps(self, monkeypatch):
        assert "bump" in await self._run(monkeypatch, code=0)

    @pytest.mark.asyncio
    async def test_failed_run_does_not_bump(self, monkeypatch):
        assert await self._run(monkeypatch, code=1) == []

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

        result = await _common.with_derived_data_revision_bump(body(), database_url=None)

        assert result == 0


def test_every_batch_entry_point_bumps_the_derived_data_revision():
    """DBを書くバッチの入口が、世代を進める経路を通ること。

    新しいバッチが素の`asyncio.run(run(...))`で書かれると、そのバッチの後だけ材料が古い
    まま残る——症状が局所的で、次に誰かが同じ範囲を走るまで現れない。ここで入口の形を
    固定して、書き忘れを足した時点で止める。
    """
    batch_dir = Path(_common.__file__).parent
    missing = []
    for path in sorted(batch_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        # 入口を持たないモジュール（プロファイルの読み込み・PBFの読み取り等）は対象外。
        if "asyncio.run(" not in source:
            continue
        if "with_derived_data_revision_bump" in source:
            continue
        missing.append(path.name)
    assert missing == []
