"""`infrastructure/basemap_client.py`——基礎地図の中継と、スタイルJSONに埋まったURLの差し替え。

ここで見ないもの:

- ディスクキャッシュの表現（ファイル名・書き込みの原子性） → `test_tile_cache.py`
- 配信のヘッダ・レート制限・キャッシュの破棄API → `test_basemap_routes.py`
- HTTPクライアントの使い回し → `test_http_client.py`

**上流もディスクも触らない。** HTTPは`fake_tile_http.py`のフェイク、`tile_cache`は読み書きを
覚えるだけの差し替えを与える。**保存先のキー名は名指ししない**——外から見えるのは
「プロキシの宛先を変えたときに何が配られるか」で、キーの綴りはこのモジュールの内側にある。
"""

import threading

import httpx
import pytest

from app.infrastructure import basemap_client, debug_log
from app.infrastructure.basemap_client import UPSTREAM_HOST, BasemapClient
from tests.fake_tile_http import FakeHttpClient

CATEGORY = "basemap:openfreemap"
PROXY_A = "http://proxy_a/api/basemap"
PROXY_B = "http://proxy_b/api/basemap"
STYLE_PATH = "styles/style_a"
STYLE_JSON = f'{{"sprite": "{UPSTREAM_HOST}/sprites/s", "attribution": "© {UPSTREAM_HOST} contributors"}}'.encode()
JSON_TYPE = "application/json"
TILE_PATH = "planet/1/2/3.pbf"
TILE_A = b"tile_a"
TILE_TYPE = "application/x-protobuf"


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
    monkeypatch.setattr(basemap_client.tile_cache, "get", fake.get)
    monkeypatch.setattr(basemap_client.tile_cache, "set", fake.set)
    debug_log.reset_stats()
    yield fake
    debug_log.reset_stats()


def _client(http_client, proxy_base_url: str = PROXY_A) -> BasemapClient:
    return BasemapClient(http_client, proxy_base_url)


def _upstream(content: bytes, content_type: str, raises=None) -> FakeHttpClient:
    return FakeHttpClient(content, content_type, raises=raises)


def _stats() -> dict:
    return debug_log.get_stats()["external"][CATEGORY]


class TestFetchingFromUpstream:
    async def test_the_path_is_asked_for_under_the_basemap_host(self):
        http_client = _upstream(TILE_A, TILE_TYPE)

        await _client(http_client).get(TILE_PATH)

        assert http_client.requested_urls == [f"{UPSTREAM_HOST}/{TILE_PATH}"]

    async def test_the_disk_is_read_and_written_off_the_event_loop(self, store):
        """基礎地図は一度に数十件のタイル・フォントを要求するため、イベントループ上で
        ディスクを触ると、同時に処理中の他のリクエストがまとめて詰まる。
        """
        await _client(_upstream(TILE_A, TILE_TYPE)).get(TILE_PATH)

        assert store.threads and threading.get_ident() not in store.threads

    async def test_a_failing_upstream_has_no_content(self):
        result = await _client(_upstream(b"", TILE_TYPE, raises=httpx.RequestError("boom"))).get(TILE_PATH)

        assert result is None
        assert _stats()["errors"] == 1

    async def test_nothing_is_kept_when_the_fetch_failed(self, store):
        await _client(_upstream(b"", TILE_TYPE, raises=httpx.RequestError("boom"))).get(TILE_PATH)

        assert store.entries == {}


class TestTilesAndFonts:
    async def test_what_came_back_is_returned_and_kept_untouched(self, store):
        """バイナリに差し替えをかけると、たまたま一致した並びが書き換わって壊れる。"""
        result = await _client(_upstream(TILE_A, TILE_TYPE)).get(TILE_PATH)

        assert result == (TILE_A, TILE_TYPE)
        assert store.entries == {TILE_PATH: (TILE_A, TILE_TYPE)}

    async def test_something_already_kept_is_served_without_asking_upstream(self, store):
        store.entries[TILE_PATH] = (TILE_A, TILE_TYPE)
        http_client = _upstream(b"other", TILE_TYPE)

        result = await _client(http_client).get(TILE_PATH)

        assert result == (TILE_A, TILE_TYPE)
        assert http_client.requested_urls == []
        assert _stats()["cache_hits"] == 1


class TestStyleDocuments:
    async def test_the_upstream_address_is_pointed_back_at_this_server(self):
        """書き換えないと、ブラウザは地図の実体を上流から直に引き、こちらの中継を通らない。"""
        content, _ = await _client(_upstream(STYLE_JSON, JSON_TYPE)).get(STYLE_PATH)

        assert f'"{PROXY_A}/sprites/s"'.encode() in content

    async def test_an_address_that_is_not_a_url_of_its_own_is_left_alone(self):
        """本文に現れる上流の名前まで書き換えると、出典の表記が嘘になる。"""
        content, _ = await _client(_upstream(STYLE_JSON, JSON_TYPE)).get(STYLE_PATH)

        assert f"© {UPSTREAM_HOST} contributors".encode() in content

    async def test_the_content_type_upstream_gave_is_passed_through(self):
        _, content_type = await _client(_upstream(STYLE_JSON, JSON_TYPE)).get(STYLE_PATH)

        assert content_type == JSON_TYPE

    async def test_changing_the_proxy_address_takes_effect_without_clearing_the_disk(self):
        """書き換えた後の姿を残すと、宛先を変えてもキャッシュを消すまで古いURLを配り続ける。"""
        await _client(_upstream(STYLE_JSON, JSON_TYPE)).get(STYLE_PATH)
        http_client = _upstream(b"", JSON_TYPE, raises=httpx.RequestError("boom"))

        content, _ = await _client(http_client, PROXY_B).get(STYLE_PATH)

        assert f'"{PROXY_B}/sprites/s"'.encode() in content
        assert http_client.requested_urls == []

    async def test_a_rewritten_copy_left_under_the_plain_key_is_not_served(self, store):
        """世代の違う書き換え済みのJSONを拾うと、宛先を変えた後も古いURLが配られる。"""
        store.entries[STYLE_PATH] = (b'{"sprite": "http://proxy_old/sprites/s"}', JSON_TYPE)
        http_client = _upstream(STYLE_JSON, JSON_TYPE)

        content, _ = await _client(http_client).get(STYLE_PATH)

        assert f'"{PROXY_A}/sprites/s"'.encode() in content
        assert http_client.requested_urls == [f"{UPSTREAM_HOST}/{STYLE_PATH}"]

    async def test_the_plain_key_is_left_alone(self, store):
        """書き換え済みの姿をそのキーへ置くと、上の判定が自分で置いたものを拾い続ける。"""
        await _client(_upstream(STYLE_JSON, JSON_TYPE)).get(STYLE_PATH)

        assert STYLE_PATH not in store.entries
