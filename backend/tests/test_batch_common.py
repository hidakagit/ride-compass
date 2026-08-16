import logging

import httpx

from app.batch._common import asyncpg_dsn, download_to_path


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
