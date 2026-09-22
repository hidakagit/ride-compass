"""`infrastructure/gsi_tile_client.py`——地理院タイルのプロキシとディスクキャッシュ。

ここで見ないもの:
- ディスクキャッシュそのものの読み書き（アトミック書き込み・容量上限） → `test_tile_cache.py`
- 標高タイルをMapLibreが読む形へ移す変換 → `services/terrain_tile_service.py`側
- 整備区域外の記憶を入れる器の大きさ（`NOT_FOUND_MAX_ENTRIES`の使い道） → `api/dependencies.py`側

ディスクキャッシュと上流HTTPは差し替えて与える。上流の応答は
`tests/fake_tile_http.py`の共有フェイクから取る。
"""

import contextlib
import threading

from app.infrastructure import gsi_tile_client
from tests.fake_tile_http import FakeHttpClient

PATH = "xyz/relief/12/3637/1612.png"


class FakeTileCache:
    """`tile_cache`の差し替え。読み書きが走ったスレッドも憶える。"""

    def __init__(self, seed: dict | None = None):
        self.entries = dict(seed or {})
        self.thread_idents: list[int] = []

    def get(self, path):
        self.thread_idents.append(threading.get_ident())
        return self.entries.get(path)

    def set(self, path, content, content_type):
        self.thread_idents.append(threading.get_ident())
        self.entries[path] = (content, content_type)


def install_fakes(monkeypatch, cache=None):
    """ディスクキャッシュと`log_external_call`を差し替え、記録先を返す。

    `fields`は`/api/debug/stats`のエラー集計とWARNINGの出し分けに使われるため、
    その中身自体がこのモジュールの外向きの成果物になる。
    """
    cache = cache or FakeTileCache()
    recorded: list[dict] = []

    @contextlib.contextmanager
    def fake_log_external_call(category, **fields):
        recorded.append(fields)
        yield fields

    monkeypatch.setattr(gsi_tile_client, "tile_cache", cache)
    monkeypatch.setattr(gsi_tile_client, "log_external_call", fake_log_external_call)
    return cache, recorded


def make_client(http_client, not_found_paths=None):
    return gsi_tile_client.GsiTileClient(
        http_client, not_found_paths if not_found_paths is not None else gsi_tile_client.LRUCache(maxsize=8)
    )


def http_status_error(status_code: int):
    httpx = gsi_tile_client.httpx
    request = httpx.Request("GET", f"{gsi_tile_client.UPSTREAM_HOST}/{PATH}")
    return httpx.HTTPStatusError(
        "upstream returned an error", request=request, response=httpx.Response(status_code, request=request)
    )


async def test_path_known_to_be_outside_coverage_skips_cache_and_upstream(monkeypatch):
    """整備区域外と分かっているパスは、ディスクも上流も触らずに済ませる。"""
    cache, recorded = install_fakes(monkeypatch)
    not_found_paths = gsi_tile_client.LRUCache(maxsize=8)
    not_found_paths[PATH] = None
    http_client = FakeHttpClient(b"tile", "image/png")

    result = await make_client(http_client, not_found_paths).get(PATH)

    assert isinstance(result, gsi_tile_client.GsiTileNotFound)
    assert cache.thread_idents == []
    assert http_client.requested_urls == []
    assert recorded == []


async def test_cached_tile_is_returned_without_asking_upstream(monkeypatch):
    cache, recorded = install_fakes(monkeypatch, FakeTileCache({PATH: (b"cached", "image/png")}))
    http_client = FakeHttpClient(b"fresh", "image/png")

    result = await make_client(http_client).get(PATH)

    assert result == (b"cached", "image/png")
    assert http_client.requested_urls == []
    assert recorded[0]["cache"] == "hit"


async def test_uncached_tile_is_fetched_from_gsi_and_kept_for_next_time(monkeypatch):
    cache, recorded = install_fakes(monkeypatch)
    http_client = FakeHttpClient(b"png-bytes", "image/png")

    result = await make_client(http_client).get(PATH)

    assert result == (b"png-bytes", "image/png")
    assert http_client.requested_urls == [f"{gsi_tile_client.UPSTREAM_HOST}/{PATH}"]
    assert cache.entries[PATH] == (b"png-bytes", "image/png")
    assert recorded[0]["cache"] == "miss"
    assert recorded[0]["result"] == "ok"
    assert recorded[0]["status"] == 200


async def test_tile_without_a_content_type_header_is_served_as_png(monkeypatch):
    """上流がContent-Typeを付けずに返しても、地理院タイルはPNGとして配れる。"""
    cache, _ = install_fakes(monkeypatch)
    http_client = FakeHttpClient(b"png-bytes", None)

    result = await make_client(http_client).get(PATH)

    assert result == (b"png-bytes", "image/png")
    assert cache.entries[PATH] == (b"png-bytes", "image/png")


async def test_upstream_404_is_remembered_and_not_counted_as_a_failure(monkeypatch):
    """整備区域外は平常運転の一部なので、エラー集計へ載せない。"""
    cache, recorded = install_fakes(monkeypatch)
    not_found_paths = gsi_tile_client.LRUCache(maxsize=8)
    http_client = FakeHttpClient(b"", "image/png", raises=http_status_error(404))

    result = await make_client(http_client, not_found_paths).get(PATH)

    assert isinstance(result, gsi_tile_client.GsiTileNotFound)
    assert PATH in not_found_paths
    assert cache.entries == {}
    assert recorded[0]["result"] == "ok"
    assert recorded[0]["status"] == 404


async def test_upstream_server_error_is_reported_as_a_failure(monkeypatch):
    """404以外のHTTPステータスは取得失敗で、記憶もしない（次回また取りに行く）。"""
    cache, recorded = install_fakes(monkeypatch)
    not_found_paths = gsi_tile_client.LRUCache(maxsize=8)
    http_client = FakeHttpClient(b"", "image/png", raises=http_status_error(503))

    result = await make_client(http_client, not_found_paths).get(PATH)

    assert result is None
    assert PATH not in not_found_paths
    assert cache.entries == {}
    assert recorded[0]["result"] == "error"
    assert recorded[0]["error_type"]


async def test_upstream_transport_failure_is_reported_as_a_failure(monkeypatch):
    cache, recorded = install_fakes(monkeypatch)
    not_found_paths = gsi_tile_client.LRUCache(maxsize=8)
    http_client = FakeHttpClient(b"", "image/png", raises=gsi_tile_client.httpx.ConnectTimeout("timed out"))

    result = await make_client(http_client, not_found_paths).get(PATH)

    assert result is None
    assert PATH not in not_found_paths
    assert recorded[0]["result"] == "error"
    assert recorded[0]["error_type"]


async def test_disk_cache_access_stays_off_the_event_loop(monkeypatch):
    """ディスクI/Oをイベントループ上で行うと、同時に処理中の他のリクエストが止まる。"""
    cache, _ = install_fakes(monkeypatch)
    http_client = FakeHttpClient(b"png-bytes", "image/png")

    await make_client(http_client).get(PATH)

    assert cache.thread_idents, "読みと書きの両方が記録されていない"
    assert threading.get_ident() not in cache.thread_idents
