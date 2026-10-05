"""`infrastructure/gsi_tile_client.py`——国土地理院のタイルをパスで中継し、ディスクに残す。

入口は`GsiTileClient.get`。網は respx の経路（`tests/fake_http.py: client_for`）で、ディスクは
本物の`tile_cache`（置き場は`tests/conftest.py`がテストごとの一時ディレクトリへ向ける）で通す。
整備区域外の記憶の入れ物は呼び出し側が持つので、テストが渡す（同じ入れ物＝同じプロセス、
新しい入れ物＝再起動の後）。

ここで見ないもの:
- HTTPの状態コードへの読み替え（404・502）・ズームの上限・レート制限 → `test_gsi_tile_routes.py`
- 標高タイルの書式の変換 → `test_gsi_dem_png.py`
- ディスクの読み書きの失敗 → `test_tile_cache.py`（このクライアントには未キャッシュとして届く）
- 読み書きをイベントループの外で行うこと → 結果に現れない順序の約束で、理由は実装の隣のコメントが持つ
"""

import logging

import httpx
import pytest
import respx
from cachetools import LRUCache

from app.infrastructure import gsi_tile_client
from tests.fake_http import client_for

UPSTREAM = "https://cyberjapandata.gsi.go.jp"
RELIEF = "xyz/relief/10/909/403.png"


def client(router: respx.Router, not_found: LRUCache | None = None) -> gsi_tile_client.GsiTileClient:
    return gsi_tile_client.GsiTileClient(client_for(router), LRUCache(maxsize=16) if not_found is None else not_found)


def unreachable() -> respx.Router:
    """どのURLへの問い合わせも落とす（記憶から返るはずの場面で、上流へ出ていないことを見る）。"""
    router = respx.Router()
    router.route().mock(side_effect=AssertionError("上流へ問い合わせた"))
    return router


@pytest.fixture
def warnings(caplog):
    caplog.set_level(logging.WARNING)
    return lambda: [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_a_tile_is_relayed_and_served_from_disk_after_a_restart():
    router = respx.Router()
    router.get(f"{UPSTREAM}/{RELIEF}").respond(content=b"\x89PNG", headers={"content-type": "image/png"})

    first = await client(router).get(RELIEF)
    later = await client(unreachable()).get(RELIEF)

    assert first == later == (b"\x89PNG", "image/png")


async def test_outside_coverage_is_remembered_for_the_process_but_not_across_a_restart(warnings):
    """整備区域は広がりうるので、区域外の記憶はディスクへ残さない。"""
    router = respx.Router()
    router.get(f"{UPSTREAM}/{RELIEF}").side_effect = [httpx.Response(404), httpx.Response(200, content=b"\x89PNG")]
    not_found = LRUCache(maxsize=16)

    first = await client(router, not_found).get(RELIEF)
    same_process = await client(unreachable(), not_found).get(RELIEF)
    after_restart = await client(router).get(RELIEF)

    assert first is same_process is gsi_tile_client.GSI_TILE_NOT_FOUND
    assert after_restart == (b"\x89PNG", "image/png")
    assert warnings() == []


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(503), httpx.ConnectTimeout("timed out")],
    ids=["server-error", "transport-error"],
)
async def test_an_upstream_failure_gives_nothing_is_logged_and_is_not_remembered(answer, warnings):
    router = respx.Router()
    route = router.get(f"{UPSTREAM}/{RELIEF}")
    route.side_effect = [answer, httpx.Response(200, content=b"\x89PNG")]
    not_found = LRUCache(maxsize=16)

    assert await client(router, not_found).get(RELIEF) is None
    assert [r for r in warnings() if "gsi-relief-tile" in r.getMessage()]
    assert await client(router, not_found).get(RELIEF) == (b"\x89PNG", "image/png")
