import pytest

from app.infrastructure import tile_cache
from app.infrastructure.basemap_client import BasemapClient


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


async def test_get_rewrites_upstream_host_in_json_responses():
    style_json = b'{"sprite":"https://tiles.openfreemap.org/sprites/ofm_f384/ofm","sources":{"openmaptiles":{"url":"https://tiles.openfreemap.org/planet"}}}'
    http_client = FakeHttpClient(style_json, "application/json")
    client = BasemapClient(http_client, "http://localhost:8000/api/basemap")

    content, content_type = await client.get("styles/liberty")

    assert b"tiles.openfreemap.org" not in content
    assert b'"http://localhost:8000/api/basemap/sprites/ofm_f384/ofm"' in content
    assert b'"http://localhost:8000/api/basemap/planet"' in content
    assert content_type == "application/json"


async def test_get_passes_through_binary_content_unmodified():
    http_client = FakeHttpClient(b"\x00\x01\x02", "application/x-protobuf")
    client = BasemapClient(http_client, "http://localhost:8000/api/basemap")

    content, content_type = await client.get("planet/20260101/12/3232/1450.pbf")

    assert content == b"\x00\x01\x02"
    assert content_type == "application/x-protobuf"


async def test_get_caches_result_and_skips_second_upstream_request():
    http_client = FakeHttpClient(b"cached-bytes", "image/png")
    client = BasemapClient(http_client, "http://localhost:8000/api/basemap")

    await client.get("sprites/ofm_f384/ofm.png")
    await client.get("sprites/ofm_f384/ofm.png")

    assert len(http_client.requested_urls) == 1


async def test_get_returns_none_on_upstream_failure():
    import httpx

    http_client = FakeHttpClient(b"", "text/plain", raises=httpx.ConnectError("boom", request=httpx.Request("GET", "http://x")))
    client = BasemapClient(http_client, "http://localhost:8000/api/basemap")

    result = await client.get("styles/liberty")

    assert result is None


async def test_json_is_cached_unrewritten_so_proxy_base_url_change_applies_immediately():
    style_json = b'{"sprite":"https://tiles.openfreemap.org/sprites/ofm_f384/ofm"}'
    http_client = FakeHttpClient(style_json, "application/json")

    first = BasemapClient(http_client, "http://localhost:3000/api/basemap")
    content, _ = await first.get("styles/liberty")
    assert b'"http://localhost:3000/api/basemap/sprites/ofm_f384/ofm"' in content

    second = BasemapClient(http_client, "https://backend.example/api/basemap")
    content, content_type = await second.get("styles/liberty")

    assert len(http_client.requested_urls) == 1
    assert b'"https://backend.example/api/basemap/sprites/ofm_f384/ofm"' in content
    assert b"tiles.openfreemap.org" not in content
    assert content_type == "application/json"
