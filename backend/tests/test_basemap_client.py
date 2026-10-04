"""`infrastructure/basemap_client.py`——OpenFreeMapの部品をパスで中継し、ディスクに残す。

入口は`BasemapClient.get`。網は respx の経路（`tests/fake_http.py: client_for`）で、ディスクは
本物の`tile_cache`（置き場は`tests/conftest.py`がテストごとの一時ディレクトリへ向ける）で通す。
前の世代がディスクに残した内容は、`tile_cache`へ直接書いて作る（再起動をまたいで残るのはディスクだけ）。

ここで見ないもの:
- HTTPの状態コードへの読み替え（404・502）とレート制限 → `test_basemap_routes.py`
- ディスクの読み書きの失敗 → `test_tile_cache.py`（このクライアントには未キャッシュとして届く）
- 読み書きをイベントループの外で行うこと → 結果に現れない順序の約束で、理由は実装の隣のコメントが持つ
"""

import json
import logging

import httpx
import pytest
import respx

from app.infrastructure import basemap_client
from tests.fake_http import client_for

PROXY = "http://localhost:8000/api/basemap"
UPSTREAM = "https://tiles.openfreemap.org"
STYLE = "styles/liberty"
TILE = "planet/20250101_001001_pt/14/14552/6451.pbf"


def style_json() -> bytes:
    return json.dumps(
        {
            "sprite": f"{UPSTREAM}/sprites/ofm_f384/ofm",
            "metadata": {"attribution": f"OpenFreeMap {UPSTREAM} © OpenMapTiles"},
        }
    ).encode()


def client(router: respx.Router, proxy: str = PROXY) -> basemap_client.BasemapClient:
    return basemap_client.BasemapClient(client_for(router), proxy)


def unreachable() -> respx.Router:
    """どのURLへの問い合わせも落とす（キャッシュから返るはずの場面で、上流へ出ていないことを見る）。"""
    router = respx.Router()
    router.route().mock(side_effect=AssertionError("上流へ問い合わせた"))
    return router


@pytest.fixture
def warnings(caplog, empty_debug_counters):
    caplog.set_level(logging.WARNING)
    return lambda: [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_a_binary_part_is_relayed_untouched_and_served_from_disk_afterwards():
    router = respx.Router()
    router.get(f"{UPSTREAM}/{TILE}").respond(content=b"\x1a\x02tile", headers={"content-type": "application/x-protobuf"})

    first = await client(router).get(TILE)
    later = await client(unreachable()).get(TILE)

    assert first == later == (b"\x1a\x02tile", "application/x-protobuf")


async def test_json_points_its_urls_at_this_server_but_keeps_upstream_names_in_text():
    """MapLibreは相対URLをページのオリジンへ解決するため、上流のURLは自分への絶対URLへ置き換える。"""
    router = respx.Router()
    router.get(f"{UPSTREAM}/{STYLE}").respond(content=style_json(), headers={"content-type": "application/json"})

    content, served_type = await client(router).get(STYLE)

    style = json.loads(content)
    assert served_type == "application/json"
    assert style["sprite"] == f"{PROXY}/sprites/ofm_f384/ofm"
    assert style["metadata"]["attribution"] == f"OpenFreeMap {UPSTREAM} © OpenMapTiles"


async def test_changing_the_public_address_takes_effect_on_cached_json_without_asking_upstream():
    router = respx.Router()
    router.get(f"{UPSTREAM}/{STYLE}").respond(content=style_json(), headers={"content-type": "application/json"})
    await client(router).get(STYLE)

    content, _ = await client(unreachable(), proxy="https://ridecompass.example/api/basemap").get(STYLE)

    assert json.loads(content)["sprite"] == "https://ridecompass.example/api/basemap/sprites/ofm_f384/ofm"


async def test_json_left_under_the_plain_path_by_an_older_version_is_not_served():
    """素のパスに残ったJSONは、当時の配信先が焼き付いた書き換え済みの内容である。"""
    stale = style_json().replace(UPSTREAM.encode(), b"http://old-host/api/basemap")
    basemap_client.tile_cache.set(STYLE, stale, "application/json")
    router = respx.Router()
    router.get(f"{UPSTREAM}/{STYLE}").respond(content=style_json(), headers={"content-type": "application/json"})

    content, _ = await client(router).get(STYLE)
    again, _ = await client(unreachable()).get(STYLE)

    assert json.loads(content)["sprite"] == json.loads(again)["sprite"] == f"{PROXY}/sprites/ofm_f384/ofm"


async def test_a_part_the_upstream_does_not_have_is_reported_as_missing_not_as_a_failure(warnings):
    router = respx.Router()
    router.get(f"{UPSTREAM}/fonts/Noto Sans Bold/65024-65279.pbf").respond(404)

    result = await client(router).get("fonts/Noto Sans Bold/65024-65279.pbf")

    assert result is basemap_client.BASEMAP_NOT_FOUND
    assert warnings() == []


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(503), httpx.ConnectTimeout("timed out")],
    ids=["server-error", "transport-error"],
)
async def test_an_upstream_failure_gives_nothing_and_is_logged(answer, warnings):
    router = respx.Router()
    route = router.get(f"{UPSTREAM}/{TILE}")
    route.side_effect = [answer, httpx.Response(200, content=b"tile")]

    assert await client(router).get(TILE) is None
    assert [r for r in warnings() if "basemap:openfreemap" in r.getMessage()]
    assert await client(router).get(TILE) == (b"tile", "application/octet-stream")
