"""`infrastructure/basemap_client.py`——OpenFreeMapのプロキシと、自分自身へのURL書き換え。

ここで見ないもの:
- ディスクキャッシュそのものの読み書き → `test_tile_cache.py`
- プロキシ先のURLを決める設定と、キャッシュを捨てる導線 → `api/routers/basemap.py`側

ディスクキャッシュと上流HTTPは差し替えて与える。上流の応答は
`tests/fake_tile_http.py`の共有フェイクから取る。
"""

import threading

import pytest

from app.infrastructure import basemap_client
from tests.fake_external_log import record_external_calls
from tests.fake_tile_cache import FakeTileCache
from tests.fake_tile_http import FakeHttpClient

STYLE_PATH = "styles/bright"
TILE_PATH = "planet/14/14552/6451.pbf"
PROXY = "http://localhost:8000/api/basemap"
OTHER_PROXY = "https://ridecompass.example/api/basemap"


def install_fakes(monkeypatch, cache=None):
    """ディスクキャッシュと`log_external_call`を差し替え、記録先を返す。"""
    cache = cache or FakeTileCache()
    monkeypatch.setattr(basemap_client, "tile_cache", cache)
    return cache, record_external_calls(monkeypatch, basemap_client)


def http_status_error(status_code: int):
    httpx = basemap_client.httpx
    request = httpx.Request("GET", f"{basemap_client.UPSTREAM_HOST}/{STYLE_PATH}")
    return httpx.HTTPStatusError(
        "upstream returned an error", request=request, response=httpx.Response(status_code, request=request)
    )


def style_json(host: str) -> bytes:
    return ('{"sprite":"%s/sprites/ofm","glyphs":"%s/fonts/{fontstack}/{range}.pbf"}' % (host, host)).encode()


async def test_cached_resource_is_returned_without_asking_upstream(monkeypatch):
    cache, recorded = install_fakes(monkeypatch, FakeTileCache({TILE_PATH: (b"cached-tile", "application/x-protobuf")}))
    http_client = FakeHttpClient(b"fresh-tile", "application/x-protobuf")

    result = await basemap_client.BasemapClient(http_client, PROXY).get(TILE_PATH)

    assert result == (b"cached-tile", "application/x-protobuf")
    assert http_client.requested_urls == []
    assert recorded[0].fields["cache"] == "hit"


@pytest.mark.parametrize("content_type", ["application/json", "application/json; charset=utf-8"])
async def test_style_json_is_cached_as_received_and_served_pointing_at_this_server(monkeypatch, content_type):
    """スタイルJSONは上流のURLのまま保存し、返す直前に自分自身のURLへ書き換える。

    MapLibreは相対URLをスタイルの取得元ではなくページのオリジンへ解決するため、
    絶対URLでなければならない。文字コードを添えた名乗り方をされても同じ扱いにする。
    """
    cache, recorded = install_fakes(monkeypatch)
    upstream_json = style_json(basemap_client.UPSTREAM_HOST)
    http_client = FakeHttpClient(upstream_json, content_type)

    result = await basemap_client.BasemapClient(http_client, PROXY).get(STYLE_PATH)

    assert result == (style_json(PROXY), content_type)
    assert http_client.requested_urls == [f"{basemap_client.UPSTREAM_HOST}/{STYLE_PATH}"]
    assert cache.entries == {basemap_client._RAW_JSON_CACHE_PREFIX + STYLE_PATH: (upstream_json, content_type)}
    assert recorded[0].fields["cache"] == "miss"
    assert recorded[0].fields["result"] == "ok"
    assert recorded[0].fields["status"] == 200


async def test_the_upstream_name_in_running_text_is_left_alone(monkeypatch):
    """地の文に現れる上流の名前まで書き換えると、誰が作った地図なのかの表示が嘘になる。"""
    install_fakes(monkeypatch)
    host = basemap_client.UPSTREAM_HOST
    upstream_json = ('{"sprite":"%s/sprites/ofm","attribution":"© %s contributors"}' % (host, host)).encode()
    http_client = FakeHttpClient(upstream_json, "application/json")

    content, _ = await basemap_client.BasemapClient(http_client, PROXY).get(STYLE_PATH)

    assert f'"{PROXY}/sprites/ofm"'.encode() in content
    assert f"© {host} contributors".encode() in content


async def test_changing_the_proxy_url_takes_effect_without_discarding_the_cache(monkeypatch):
    """配信元のURLを変えたら、キャッシュを消さなくても次の取得からその値で配る。"""
    cache, recorded = install_fakes(monkeypatch)
    upstream_json = style_json(basemap_client.UPSTREAM_HOST)
    http_client = FakeHttpClient(upstream_json, "application/json")
    await basemap_client.BasemapClient(http_client, PROXY).get(STYLE_PATH)

    result = await basemap_client.BasemapClient(http_client, OTHER_PROXY).get(STYLE_PATH)

    assert result == (style_json(OTHER_PROXY), "application/json")
    assert len(http_client.requested_urls) == 1
    assert recorded[1].fields["cache"] == "hit"


async def test_binary_resource_is_passed_through_untouched(monkeypatch):
    """JSON以外は書き換えの対象外——上流のホスト名がバイト列に現れても触らない。"""
    cache, _ = install_fakes(monkeypatch)
    payload = f"{basemap_client.UPSTREAM_HOST}".encode() + b"\x00\x01binary"
    http_client = FakeHttpClient(payload, "application/x-protobuf")

    result = await basemap_client.BasemapClient(http_client, PROXY).get(TILE_PATH)

    assert result == (payload, "application/x-protobuf")
    assert cache.entries == {TILE_PATH: (payload, "application/x-protobuf")}


async def test_resource_without_a_content_type_header_is_treated_as_binary(monkeypatch):
    cache, _ = install_fakes(monkeypatch)
    http_client = FakeHttpClient(b"\x00\x01binary", None)

    result = await basemap_client.BasemapClient(http_client, PROXY).get(TILE_PATH)

    assert result == (b"\x00\x01binary", "application/octet-stream")
    assert cache.entries == {TILE_PATH: (b"\x00\x01binary", "application/octet-stream")}


async def test_a_rewritten_style_left_at_the_plain_key_is_not_served(monkeypatch):
    """素の鍵にJSONが残っているのは、生の内容を別の鍵へ分ける前の世代が書いたもの。
    当時の配信先が焼き付いているため、採用すると配信先を変えても古いものが配られ続ける。"""
    cache, recorded = install_fakes(
        monkeypatch, FakeTileCache({STYLE_PATH: (style_json(OTHER_PROXY), "application/json")})
    )
    http_client = FakeHttpClient(style_json(basemap_client.UPSTREAM_HOST), "application/json")

    content, _ = await basemap_client.BasemapClient(http_client, PROXY).get(STYLE_PATH)

    assert content == style_json(PROXY)
    assert http_client.requested_urls == [f"{basemap_client.UPSTREAM_HOST}/{STYLE_PATH}"]
    assert recorded[0].fields["stale"] == "rewritten-json"


async def test_a_resource_the_upstream_does_not_have_is_not_a_failure(monkeypatch):
    """用意されていない書体の範囲などは平常運転の一部で、上流の障害ではない。"""
    cache, recorded = install_fakes(monkeypatch)
    http_client = FakeHttpClient(b"", None, raises=http_status_error(404))

    result = await basemap_client.BasemapClient(http_client, PROXY).get("fonts/NotoSans/40000-40255.pbf")

    assert isinstance(result, basemap_client.BasemapNotFound)
    assert cache.entries == {}
    assert recorded[0].fields["result"] == "ok"
    assert recorded[0].fields["status"] == 404


async def test_upstream_server_error_is_reported_as_a_failure(monkeypatch):
    cache, recorded = install_fakes(monkeypatch)
    http_client = FakeHttpClient(b"", None, raises=http_status_error(500))

    result = await basemap_client.BasemapClient(http_client, PROXY).get(TILE_PATH)

    assert result is None
    assert cache.entries == {}
    assert recorded[0].fields["result"] == "error"
    assert recorded[0].fields["error_type"]


async def test_upstream_failure_is_reported_as_a_failure(monkeypatch):
    cache, recorded = install_fakes(monkeypatch)
    http_client = FakeHttpClient(b"", None, raises=basemap_client.httpx.ConnectTimeout("timed out"))

    result = await basemap_client.BasemapClient(http_client, PROXY).get(TILE_PATH)

    assert result is None
    assert cache.entries == {}
    assert recorded[0].fields["result"] == "error"
    assert recorded[0].fields["error_type"]


async def test_disk_cache_access_stays_off_the_event_loop(monkeypatch):
    """基礎地図の読み込みでは数十件の要求が同時に来るため、ディスクI/Oがループを塞ぐと
    同時に処理中の他のリクエストが止まる。"""
    cache, _ = install_fakes(monkeypatch)
    http_client = FakeHttpClient(b"\x00\x01binary", "application/x-protobuf")

    await basemap_client.BasemapClient(http_client, PROXY).get(TILE_PATH)

    assert cache.thread_idents, "読みと書きの両方が記録されていない"
    assert threading.get_ident() not in cache.thread_idents
