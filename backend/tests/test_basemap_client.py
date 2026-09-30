"""`infrastructure/basemap_client.py`——OpenFreeMapのプロキシと、自分自身へのURL書き換え。

ここで見ないもの:
- ディスクキャッシュそのものの読み書き → `test_tile_cache.py`
- プロキシ先のURLを決める設定と、キャッシュを捨てる導線 → `api/routers/basemap.py`側

ディスクキャッシュと上流HTTPは差し替えて与える。上流はrespxの経路で応答を決める。
"""

import threading

import httpx
import pytest
import respx

from app.infrastructure import basemap_client
from tests.fake_external_log import record_external_calls
from tests.fake_http import client_for
from tests.fake_tile_cache import FakeTileCache

STYLE_PATH = "styles/bright"
TILE_PATH = "planet/14/14552/6451.pbf"
PROXY = "http://localhost:8000/api/basemap"
OTHER_PROXY = "https://ridecompass.example/api/basemap"


@pytest.fixture
def upstream():
    """OpenFreeMapの代役。応答はテストごとに経路を足して決め、経路に無いURLを引けば失敗する。"""
    return respx.Router(base_url=basemap_client.UPSTREAM_HOST)


def install_fakes(monkeypatch, cache=None):
    """ディスクキャッシュと`log_external_call`を差し替え、記録先を返す。"""
    cache = cache or FakeTileCache()
    monkeypatch.setattr(basemap_client, "tile_cache", cache)
    return cache, record_external_calls(monkeypatch, basemap_client)


def client(upstream, proxy=PROXY):
    return basemap_client.BasemapClient(client_for(upstream), proxy)


def style_json(host: str) -> bytes:
    return ('{"sprite":"%s/sprites/ofm","glyphs":"%s/fonts/{fontstack}/{range}.pbf"}' % (host, host)).encode()


async def test_cached_resource_is_returned_without_asking_upstream(monkeypatch, upstream):
    cache, recorded = install_fakes(monkeypatch, FakeTileCache({TILE_PATH: (b"cached-tile", "application/x-protobuf")}))

    result = await client(upstream).get(TILE_PATH)

    assert result == (b"cached-tile", "application/x-protobuf")
    assert not upstream.calls
    assert recorded[0].fields["cache"] == "hit"


@pytest.mark.parametrize("content_type", ["application/json", "application/json; charset=utf-8"])
async def test_style_json_is_cached_as_received_and_served_pointing_at_this_server(monkeypatch, upstream, content_type):
    """スタイルJSONは上流のURLのまま保存し、返す直前に自分自身のURLへ書き換える。

    MapLibreは相対URLをスタイルの取得元ではなくページのオリジンへ解決するため、
    絶対URLでなければならない。文字コードを添えた名乗り方をされても同じ扱いにする。
    """
    cache, recorded = install_fakes(monkeypatch)
    upstream_json = style_json(basemap_client.UPSTREAM_HOST)
    upstream.get(f"/{STYLE_PATH}").respond(content=upstream_json, content_type=content_type)

    result = await client(upstream).get(STYLE_PATH)

    assert result == (style_json(PROXY), content_type)
    assert upstream.calls.call_count == 1
    assert cache.entries == {basemap_client._RAW_JSON_CACHE_PREFIX + STYLE_PATH: (upstream_json, content_type)}
    assert recorded[0].fields["cache"] == "miss"
    assert recorded[0].fields["result"] == "ok"
    assert recorded[0].fields["status"] == 200


async def test_the_upstream_name_in_running_text_is_left_alone(monkeypatch, upstream):
    """地の文に現れる上流の名前まで書き換えると、誰が作った地図なのかの表示が嘘になる。"""
    install_fakes(monkeypatch)
    host = basemap_client.UPSTREAM_HOST
    upstream_json = ('{"sprite":"%s/sprites/ofm","attribution":"© %s contributors"}' % (host, host)).encode()
    upstream.get(f"/{STYLE_PATH}").respond(content=upstream_json, content_type="application/json")

    content, _ = await client(upstream).get(STYLE_PATH)

    assert f'"{PROXY}/sprites/ofm"'.encode() in content
    assert f"© {host} contributors".encode() in content


async def test_changing_the_proxy_url_takes_effect_without_discarding_the_cache(monkeypatch, upstream):
    """配信元のURLを変えたら、キャッシュを消さなくても次の取得からその値で配る。"""
    cache, recorded = install_fakes(monkeypatch)
    upstream.get(f"/{STYLE_PATH}").respond(
        content=style_json(basemap_client.UPSTREAM_HOST), content_type="application/json"
    )
    await client(upstream).get(STYLE_PATH)

    result = await client(upstream, OTHER_PROXY).get(STYLE_PATH)

    assert result == (style_json(OTHER_PROXY), "application/json")
    assert upstream.calls.call_count == 1
    assert recorded[1].fields["cache"] == "hit"


async def test_binary_resource_is_passed_through_untouched(monkeypatch, upstream):
    """JSON以外は書き換えの対象外——上流のホスト名がバイト列に現れても触らない。"""
    cache, _ = install_fakes(monkeypatch)
    payload = f"{basemap_client.UPSTREAM_HOST}".encode() + b"\x00\x01binary"
    upstream.get(f"/{TILE_PATH}").respond(content=payload, content_type="application/x-protobuf")

    result = await client(upstream).get(TILE_PATH)

    assert result == (payload, "application/x-protobuf")
    assert cache.entries == {TILE_PATH: (payload, "application/x-protobuf")}


async def test_resource_without_a_content_type_header_is_treated_as_binary(monkeypatch, upstream):
    """上流がContent-Typeを付けずに返すことは実際にあり、ヘッダの無い応答でしか確かめられない。"""
    cache, _ = install_fakes(monkeypatch)
    upstream.get(f"/{TILE_PATH}").respond(content=b"\x00\x01binary")

    result = await client(upstream).get(TILE_PATH)

    assert result == (b"\x00\x01binary", "application/octet-stream")
    assert cache.entries == {TILE_PATH: (b"\x00\x01binary", "application/octet-stream")}


async def test_a_rewritten_style_left_at_the_plain_key_is_not_served(monkeypatch, upstream):
    """素の鍵にJSONが残っているのは、生の内容を別の鍵へ分ける前の世代が書いたもの。
    当時の配信先が焼き付いているため、採用すると配信先を変えても古いものが配られ続ける。"""
    cache, recorded = install_fakes(
        monkeypatch, FakeTileCache({STYLE_PATH: (style_json(OTHER_PROXY), "application/json")})
    )
    upstream.get(f"/{STYLE_PATH}").respond(
        content=style_json(basemap_client.UPSTREAM_HOST), content_type="application/json"
    )

    content, _ = await client(upstream).get(STYLE_PATH)

    assert content == style_json(PROXY)
    assert upstream.calls.call_count == 1
    assert recorded[0].fields["stale"] == "rewritten-json"


async def test_a_resource_the_upstream_does_not_have_is_not_a_failure(monkeypatch, upstream):
    """用意されていない書体の範囲などは平常運転の一部で、上流の障害ではない。"""
    cache, recorded = install_fakes(monkeypatch)
    upstream.get("/fonts/NotoSans/40000-40255.pbf").respond(404)

    result = await client(upstream).get("fonts/NotoSans/40000-40255.pbf")

    assert isinstance(result, basemap_client.BasemapNotFound)
    assert cache.entries == {}
    assert recorded[0].fields["result"] == "ok"
    assert recorded[0].fields["status"] == 404


async def test_upstream_server_error_is_reported_as_a_failure(monkeypatch, upstream):
    cache, recorded = install_fakes(monkeypatch)
    upstream.get(f"/{TILE_PATH}").respond(500)

    result = await client(upstream).get(TILE_PATH)

    assert result is None
    assert cache.entries == {}
    assert recorded[0].fields["result"] == "error"
    assert recorded[0].fields["error_type"]


async def test_upstream_failure_is_reported_as_a_failure(monkeypatch, upstream):
    cache, recorded = install_fakes(monkeypatch)
    upstream.get(f"/{TILE_PATH}").mock(side_effect=httpx.ConnectTimeout)

    result = await client(upstream).get(TILE_PATH)

    assert result is None
    assert cache.entries == {}
    assert recorded[0].fields["result"] == "error"
    assert recorded[0].fields["error_type"]


async def test_disk_cache_access_stays_off_the_event_loop(monkeypatch, upstream):
    """基礎地図の読み込みでは数十件の要求が同時に来るため、ディスクI/Oがループを塞ぐと
    同時に処理中の他のリクエストが止まる。"""
    cache, _ = install_fakes(monkeypatch)
    upstream.get(f"/{TILE_PATH}").respond(content=b"\x00\x01binary", content_type="application/x-protobuf")

    await client(upstream).get(TILE_PATH)

    assert cache.thread_idents, "読みと書きの両方が記録されていない"
    assert threading.get_ident() not in cache.thread_idents
