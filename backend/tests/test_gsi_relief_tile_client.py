import pytest

from app.infrastructure import tile_cache
from app.infrastructure.gsi_relief_tile_client import GsiReliefTileClient


@pytest.fixture(autouse=True)
def use_temp_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
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
