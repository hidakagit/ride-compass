"""`infrastructure/gsi_tile_client.py`——地理院タイルの取り寄せと、整備区域外の記憶。

ここで見ないもの:

- ディスクキャッシュの表現（ファイル名・書き込みの原子性） → `test_tile_cache.py`
- HTTPクライアントの使い回し → `test_http_client.py`
- 取り寄せたタイルの配信・変換 → `test_gsi_tile_routes.py`・`test_gsi_dem_tile.py`

**上流もディスクも触らない。** HTTPは`fake_tile_http.py`のフェイク、`tile_cache`は読み書きを
覚えるだけの差し替えを与える。記録された結果は`/api/debug/stats`が読む集計を通して確かめる。
区域外の記憶はプロセス大域のため、各テストの前後で空にする。
"""

import threading

import httpx
import pytest

from app.infrastructure import debug_log, gsi_tile_client
from app.infrastructure.gsi_tile_client import GSI_TILE_NOT_FOUND, UPSTREAM_HOST, GsiTileClient
from tests.fake_tile_http import FakeHttpClient

CATEGORY = "gsi-relief-tile"
PATH_A = "relief_a/10/900/400.png"
TILE_A = b"tile_a"
TILE_TYPE = "image/png"


class FakeTileCache:
    """`tile_cache`の読み書きを覚えるだけの差し替え（`threads`は読み書きを行ったスレッド）。"""

    def __init__(self):
        self.entries: dict[str, tuple[bytes, str]] = {}
        self.threads: set[int] = set()

    def get(self, path: str) -> tuple[bytes, str] | None:
        self.threads.add(threading.get_ident())
        return self.entries.get(path)

    def set(self, path: str, content: bytes, content_type: str) -> None:
        self.threads.add(threading.get_ident())
        self.entries[path] = (content, content_type)


@pytest.fixture(autouse=True)
def store(monkeypatch):
    fake = FakeTileCache()
    monkeypatch.setattr(gsi_tile_client.tile_cache, "get", fake.get)
    monkeypatch.setattr(gsi_tile_client.tile_cache, "set", fake.set)
    debug_log.reset_stats()
    gsi_tile_client._not_found_paths.clear()
    yield fake
    debug_log.reset_stats()
    gsi_tile_client._not_found_paths.clear()


def _client(http_client) -> GsiTileClient:
    return GsiTileClient(http_client)


def _upstream(content: bytes = TILE_A, content_type: str = TILE_TYPE, raises=None) -> FakeHttpClient:
    return FakeHttpClient(content, content_type, raises=raises)


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"{UPSTREAM_HOST}/{PATH_A}")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(str(status_code), request=request, response=response)


def _stats() -> dict:
    return debug_log.get_stats()["external"][CATEGORY]


class TestFetchingATile:
    async def test_the_path_is_asked_for_under_the_map_agency_host(self):
        http_client = _upstream()

        await _client(http_client).get(PATH_A)

        assert http_client.requested_urls == [f"{UPSTREAM_HOST}/{PATH_A}"]

    async def test_what_came_back_is_returned_with_its_content_type(self):
        assert await _client(_upstream()).get(PATH_A) == (TILE_A, TILE_TYPE)

    async def test_what_came_back_is_kept_for_the_next_request(self, store):
        """残さないと、同じ1枚を要求のたびに地理院へ取りに行く。"""
        await _client(_upstream()).get(PATH_A)

        assert store.entries == {PATH_A: (TILE_A, TILE_TYPE)}

    async def test_a_tile_already_kept_is_served_without_asking_upstream(self, store):
        store.entries[PATH_A] = (TILE_A, TILE_TYPE)
        http_client = _upstream(b"other")

        result = await _client(http_client).get(PATH_A)

        assert result == (TILE_A, TILE_TYPE)
        assert http_client.requested_urls == []
        assert _stats()["cache_hits"] == 1

    async def test_the_disk_is_read_and_written_off_the_event_loop(self, store):
        """イベントループ上でディスクを触ると、同時に処理中のルート生成まで詰まる。"""
        await _client(_upstream()).get(PATH_A)

        assert store.threads and threading.get_ident() not in store.threads


class TestTilesOutsideTheMappedArea:
    async def test_a_missing_tile_is_told_apart_from_a_failure(self):
        """同じNoneで返すと、呼び出し側は「地理院に無い」と「取れなかった」を区別できない。"""
        result = await _client(_upstream(raises=_status_error(404))).get(PATH_A)

        assert result is GSI_TILE_NOT_FOUND

    async def test_a_missing_tile_is_not_counted_as_an_error(self):
        """区域外は珍しくない。エラーに数えると、集計の中で本物の障害が埋もれる。"""
        await _client(_upstream(raises=_status_error(404))).get(PATH_A)

        assert _stats()["errors"] == 0

    async def test_a_missing_tile_is_not_written_to_disk(self, store):
        """書くと、地理院が整備を広げてもファイルを消すまで「無い」を返し続ける。"""
        await _client(_upstream(raises=_status_error(404))).get(PATH_A)

        assert store.entries == {}

    async def test_a_tile_known_to_be_missing_is_not_asked_for_again(self):
        """区域外のタイルは地図を動かすたびに要求されるため、毎回上流へ行くと帯域を食い潰す。"""
        http_client = _upstream(raises=_status_error(404))
        client = _client(http_client)

        await client.get(PATH_A)
        again = await client.get(PATH_A)

        assert again is GSI_TILE_NOT_FOUND
        assert len(http_client.requested_urls) == 1


class TestWhenTheFetchFails:
    async def test_a_server_error_has_no_tile(self):
        result = await _client(_upstream(raises=_status_error(500))).get(PATH_A)

        assert result is None
        assert _stats()["errors"] == 1

    async def test_a_connection_failure_has_no_tile(self):
        result = await _client(_upstream(raises=httpx.RequestError("boom"))).get(PATH_A)

        assert result is None
        assert _stats()["errors"] == 1

    async def test_a_failure_is_not_remembered_as_a_missing_tile(self):
        """一時的な障害を区域外として憶えると、上流が復旧してもプロセスを再起動するまで出ない。"""
        await _client(_upstream(raises=_status_error(500))).get(PATH_A)

        assert await _client(_upstream()).get(PATH_A) == (TILE_A, TILE_TYPE)

    async def test_a_failure_is_not_written_to_disk(self, store):
        await _client(_upstream(raises=httpx.RequestError("boom"))).get(PATH_A)

        assert store.entries == {}
