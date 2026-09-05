import pytest

from app.infrastructure import gsi_relief_tile_client, tile_cache
from app.infrastructure.gsi_relief_tile_client import GsiReliefTileClient, ReliefTileNotFound


@pytest.fixture(autouse=True)
def use_temp_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
    # 改善計画T605: 恒久404の記憶（_not_found_paths）はプロセス内モジュール変数のため、
    # テスト間で漏れないよう毎回空にする（_target_times_cache.clear()と同じ理由）。
    gsi_relief_tile_client._not_found_paths.clear()
    yield


class FakeResponse:
    def __init__(self, content: bytes, content_type: str):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        pass


class FakeHttpClient:
    def __init__(self, content: bytes, content_type: str, raises=None):
        self._content = content
        self._content_type = content_type
        self._raises = raises
        self.requested_urls = []

    async def get(self, url):
        self.requested_urls.append(url)
        if self._raises:
            raise self._raises
        return FakeResponse(self._content, self._content_type)


async def test_get_passes_through_binary_content_unmodified():
    http_client = FakeHttpClient(b"\x89PNG\x00\x01", "image/png")
    client = GsiReliefTileClient(http_client)

    content, content_type = await client.get("xyz/relief/12/3637/1612.png")

    assert content == b"\x89PNG\x00\x01"
    assert content_type == "image/png"
    assert http_client.requested_urls == ["https://cyberjapandata.gsi.go.jp/xyz/relief/12/3637/1612.png"]


async def test_get_caches_result_and_skips_second_upstream_request():
    http_client = FakeHttpClient(b"cached-bytes", "image/png")
    client = GsiReliefTileClient(http_client)

    await client.get("xyz/relief/12/3637/1612.png")
    await client.get("xyz/relief/12/3637/1612.png")

    assert len(http_client.requested_urls) == 1


async def test_get_returns_none_on_upstream_failure():
    import httpx

    http_client = FakeHttpClient(
        b"", "image/png", raises=httpx.ConnectError("boom", request=httpx.Request("GET", "http://x"))
    )
    client = GsiReliefTileClient(http_client)

    result = await client.get("xyz/relief/12/3637/1612.png")

    assert result is None


async def test_get_returns_relief_tile_not_found_for_404():
    # 改善計画T605: 整備区域外（404）は珍しくない正常系のため、他の失敗と区別する。
    import httpx

    request = httpx.Request("GET", "https://cyberjapandata.gsi.go.jp/x")
    response = httpx.Response(404, request=request)
    http_client = FakeHttpClient(
        b"", "image/png", raises=httpx.HTTPStatusError("404", request=request, response=response)
    )
    client = GsiReliefTileClient(http_client)

    result = await client.get("xyz/relief/12/3637/1612.png")

    assert isinstance(result, ReliefTileNotFound)


async def test_get_caches_404_and_skips_second_upstream_request():
    # 改善計画T605: 恒久404を確認したタイルは、次回get()が上流へ問い合わせず
    # ReliefTileNotFoundを即座に返す。
    import httpx

    request = httpx.Request("GET", "https://cyberjapandata.gsi.go.jp/x")
    response = httpx.Response(404, request=request)
    http_client = FakeHttpClient(
        b"", "image/png", raises=httpx.HTTPStatusError("404", request=request, response=response)
    )
    client = GsiReliefTileClient(http_client)
    path = "xyz/relief/12/3637/1612.png"

    first = await client.get(path)
    second = await client.get(path)

    assert isinstance(first, ReliefTileNotFound)
    assert isinstance(second, ReliefTileNotFound)
    assert len(http_client.requested_urls) == 1


async def test_404_is_not_counted_as_an_error_in_debug_stats():
    import httpx

    from app.infrastructure import debug_log

    debug_log.reset_stats()
    request = httpx.Request("GET", "https://cyberjapandata.gsi.go.jp/x")
    response = httpx.Response(404, request=request)
    http_client = FakeHttpClient(
        b"", "image/png", raises=httpx.HTTPStatusError("404", request=request, response=response)
    )
    client = GsiReliefTileClient(http_client)

    await client.get("xyz/relief/12/3637/1612.png")

    stats = debug_log.get_stats()["external"]["gsi-relief-tile"]
    assert stats["errors"] == 0
