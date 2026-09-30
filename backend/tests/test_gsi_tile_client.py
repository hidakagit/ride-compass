"""`infrastructure/gsi_tile_client.py`——地理院タイルのプロキシとディスクキャッシュ。

ここで見ないもの:
- ディスクキャッシュそのものの読み書き → `test_tile_cache.py`
- 標高タイルをMapLibreが読む形へ移す変換 → `services/terrain_tile_service.py`側
- 整備区域外の記憶を入れる器の大きさ（`NOT_FOUND_MAX_ENTRIES`の使い道） → `api/dependencies.py`側

ディスクキャッシュと上流HTTPは差し替えて与える。上流はrespxの経路で応答を決める。
"""

import threading

import httpx
import pytest
import respx

from app.infrastructure import gsi_tile_client
from tests.fake_external_log import record_external_calls
from tests.fake_http import client_for
from tests.fake_tile_cache import FakeTileCache

PATH = "xyz/relief/12/3637/1612.png"


@pytest.fixture
def upstream():
    """地理院タイルの代役。応答はテストごとに経路を足して決め、経路に無いURLを引けば失敗する。"""
    return respx.Router(base_url=gsi_tile_client.UPSTREAM_HOST)


def install_fakes(monkeypatch, cache=None):
    """ディスクキャッシュと`log_external_call`を差し替え、記録先を返す。"""
    cache = cache or FakeTileCache()
    monkeypatch.setattr(gsi_tile_client, "tile_cache", cache)
    return cache, record_external_calls(monkeypatch, gsi_tile_client)


def make_client(upstream, not_found_paths=None):
    return gsi_tile_client.GsiTileClient(
        client_for(upstream),
        not_found_paths if not_found_paths is not None else gsi_tile_client.LRUCache(maxsize=8),
    )


async def test_path_known_to_be_outside_coverage_skips_cache_and_upstream(monkeypatch, upstream):
    """整備区域外と分かっているパスは、ディスクも上流も触らずに済ませる。"""
    cache, recorded = install_fakes(monkeypatch)
    not_found_paths = gsi_tile_client.LRUCache(maxsize=8)
    not_found_paths[PATH] = None

    result = await make_client(upstream, not_found_paths).get(PATH)

    assert isinstance(result, gsi_tile_client.GsiTileNotFound)
    assert cache.thread_idents == []
    assert not upstream.calls
    assert recorded == []


async def test_cached_tile_is_returned_without_asking_upstream(monkeypatch, upstream):
    cache, recorded = install_fakes(monkeypatch, FakeTileCache({PATH: (b"cached", "image/png")}))

    result = await make_client(upstream).get(PATH)

    assert result == (b"cached", "image/png")
    assert not upstream.calls
    assert recorded[0].fields["cache"] == "hit"


async def test_uncached_tile_is_fetched_from_gsi_and_kept_for_next_time(monkeypatch, upstream):
    cache, recorded = install_fakes(monkeypatch)
    tile = upstream.get(f"/{PATH}").respond(content=b"png-bytes", content_type="image/png")

    result = await make_client(upstream).get(PATH)

    assert result == (b"png-bytes", "image/png")
    assert tile.call_count == 1
    assert cache.entries[PATH] == (b"png-bytes", "image/png")
    assert recorded[0].fields["cache"] == "miss"
    assert recorded[0].fields["result"] == "ok"
    assert recorded[0].fields["status"] == 200


async def test_tile_without_a_content_type_header_is_served_as_png(monkeypatch, upstream):
    """上流がContent-Typeを付けずに返しても、地理院タイルはPNGとして配れる。"""
    cache, _ = install_fakes(monkeypatch)
    upstream.get(f"/{PATH}").respond(content=b"png-bytes")

    result = await make_client(upstream).get(PATH)

    assert result == (b"png-bytes", "image/png")
    assert cache.entries[PATH] == (b"png-bytes", "image/png")


async def test_upstream_404_is_remembered_and_not_counted_as_a_failure(monkeypatch, upstream):
    """整備区域外は平常運転の一部なので、エラー集計へ載せない。"""
    cache, recorded = install_fakes(monkeypatch)
    not_found_paths = gsi_tile_client.LRUCache(maxsize=8)
    upstream.get(f"/{PATH}").respond(404)

    result = await make_client(upstream, not_found_paths).get(PATH)

    assert isinstance(result, gsi_tile_client.GsiTileNotFound)
    assert PATH in not_found_paths
    assert cache.entries == {}
    assert recorded[0].fields["result"] == "ok"
    assert recorded[0].fields["status"] == 404


async def test_upstream_server_error_is_reported_as_a_failure(monkeypatch, upstream):
    """404以外のHTTPステータスは取得失敗で、記憶もしない（次回また取りに行く）。"""
    cache, recorded = install_fakes(monkeypatch)
    not_found_paths = gsi_tile_client.LRUCache(maxsize=8)
    upstream.get(f"/{PATH}").respond(503)

    result = await make_client(upstream, not_found_paths).get(PATH)

    assert result is None
    assert PATH not in not_found_paths
    assert cache.entries == {}
    assert recorded[0].fields["result"] == "error"
    assert recorded[0].fields["error_type"]


async def test_upstream_transport_failure_is_reported_as_a_failure(monkeypatch, upstream):
    cache, recorded = install_fakes(monkeypatch)
    not_found_paths = gsi_tile_client.LRUCache(maxsize=8)
    upstream.get(f"/{PATH}").mock(side_effect=httpx.ConnectTimeout)

    result = await make_client(upstream, not_found_paths).get(PATH)

    assert result is None
    assert PATH not in not_found_paths
    assert recorded[0].fields["result"] == "error"
    assert recorded[0].fields["error_type"]


async def test_disk_cache_access_stays_off_the_event_loop(monkeypatch, upstream):
    """ディスクI/Oをイベントループ上で行うと、同時に処理中の他のリクエストが止まる。"""
    cache, _ = install_fakes(monkeypatch)
    upstream.get(f"/{PATH}").respond(content=b"png-bytes", content_type="image/png")

    await make_client(upstream).get(PATH)

    assert cache.thread_idents, "読みと書きの両方が記録されていない"
    assert threading.get_ident() not in cache.thread_idents
