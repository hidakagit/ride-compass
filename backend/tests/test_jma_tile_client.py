"""`infrastructure/jma_tile_client.py`——JMA bosaiのタイル・時刻一覧のプロキシとキャッシュ。

ここで見ないもの:
- Redisへの保存形式・空タイルのフラグ化 → `test_jma_tile_redis_cache.py`
- HTTPの返し分け（404/502）・配信側のレート制限 → `test_jma_tile_routes.py`
- プリウォームの巡回 → `test_jma_tile_prewarm_service.py`

上流HTTPは`tests/fake_tile_http.py`、Redisは`tests/fake_redis.py`のフェイクを通す。
キャッシュと上流の間隔はモジュール大域に持たれるため、テストごとに戻す。
"""

import time

import httpx
import pytest

from app.config import settings
from app.infrastructure import debug_log, jma_tile_client, jma_tile_redis_cache
from app.infrastructure.jma_tile_client import (
    UPSTREAM_HOST,
    JmaTileClient,
    JmaTileNotFoundError,
    is_target_times_path,
)
from app.infrastructure.jma_tile_redis_cache import EMPTY_TILE
from tests.fake_redis import FakeRedis
from tests.fake_tile_http import FakeHttpClient

TILE_PATH = "bosai/jmatile/data/nowc/20260101000000/none/20260101000500/surf/hrpns/6/57/25.png"
TARGET_TIMES_PATH = "bosai/jmatile/data/nowc/targetTimes_N1.json"


@pytest.fixture(autouse=True)
def _reset_module_state():
    jma_tile_client._target_times_cache.clear()
    jma_tile_client._last_fetch_at = None
    yield
    jma_tile_client._target_times_cache.clear()
    jma_tile_client._last_fetch_at = None


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    return fake


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"{UPSTREAM_HOST}/{TILE_PATH}")
    return httpx.HTTPStatusError("upstream", request=request, response=httpx.Response(status_code, request=request))


def test_target_times_are_told_apart_by_the_file_name():
    """取り違えると、同じURLのまま更新される時刻一覧がタイルと同じ寿命で居座り、
    地図が古い時刻を指し続ける。"""
    assert is_target_times_path("bosai/jmatile/data/nowc/targetTimes.json") is True
    assert is_target_times_path(TARGET_TIMES_PATH) is True
    assert is_target_times_path(TILE_PATH) is False
    assert is_target_times_path("bosai/targetTimes.json/6/57/25.png") is False


async def test_fetched_tile_is_shared_with_later_requests(fake_redis):
    """クライアントはリクエストごとに使い捨てるため、別インスタンスから確かめる。"""
    await JmaTileClient(FakeHttpClient(b"tile", "image/png")).fetch(TILE_PATH)
    later = FakeHttpClient(b"unused", "image/png")
    assert await JmaTileClient(later).get_cached(TILE_PATH) == (b"tile", "image/png")
    assert later.requested_urls == []


async def test_fetched_target_times_are_kept_in_process_instead_of_redis(fake_redis):
    await JmaTileClient(FakeHttpClient(b"[]", "application/json")).fetch(TARGET_TIMES_PATH)
    assert fake_redis.store == {}
    later = FakeHttpClient(b"unused", "application/json")
    assert await JmaTileClient(later).get_cached(TARGET_TIMES_PATH) == (b"[]", "application/json")
    assert later.requested_urls == []


async def test_cache_lookup_never_reaches_upstream():
    http = FakeHttpClient(b"tile", "image/png")
    assert await JmaTileClient(http).get_cached(TILE_PATH) is None
    assert http.requested_urls == []


async def test_fetch_asks_the_jma_host_for_the_given_path():
    http = FakeHttpClient(b"tile", "image/png")
    assert await JmaTileClient(http).fetch(TILE_PATH) == (b"tile", "image/png")
    assert http.requested_urls == [f"{UPSTREAM_HOST}/{TILE_PATH}"]


async def test_response_without_a_content_type_falls_back_to_a_generic_one():
    result = await JmaTileClient(FakeHttpClient(b"tile", None)).fetch(TILE_PATH)
    assert result == (b"tile", "application/octet-stream")


@pytest.mark.parametrize("path", [TILE_PATH, TARGET_TIMES_PATH])
async def test_absent_path_is_remembered_so_the_next_request_skips_upstream(path):
    http = FakeHttpClient(b"", "image/png", raises=_status_error(404))
    with pytest.raises(JmaTileNotFoundError):
        await JmaTileClient(http).fetch(path)
    later = FakeHttpClient(b"tile", "image/png")
    assert await JmaTileClient(later).get_cached(path) is EMPTY_TILE
    assert later.requested_urls == []


@pytest.mark.parametrize("raises", [_status_error(500), httpx.ConnectError("no route")])
async def test_upstream_failure_yields_nothing_and_is_not_remembered(raises):
    assert await JmaTileClient(FakeHttpClient(b"", "image/png", raises=raises)).fetch(TILE_PATH) is None
    later = FakeHttpClient(b"tile", "image/png")
    assert await JmaTileClient(later).get_cached(TILE_PATH) is None


@pytest.mark.parametrize("path", [TILE_PATH, TARGET_TIMES_PATH])
async def test_locally_built_tiles_can_be_stored_without_fetching(path):
    http = FakeHttpClient(b"unused", "image/png")
    client = JmaTileClient(http)
    await client.store(path, b"built here", "image/png")
    assert await client.get_cached(path) == (b"built here", "image/png")
    assert http.requested_urls == []


async def test_get_prefers_the_cache_over_upstream():
    http = FakeHttpClient(b"from upstream", "image/png")
    client = JmaTileClient(http)
    await client.store(TILE_PATH, b"cached", "image/png")
    assert await client.get(TILE_PATH) == (b"cached", "image/png")
    assert http.requested_urls == []


async def test_get_fetches_when_the_cache_misses():
    http = FakeHttpClient(b"from upstream", "image/png")
    assert await JmaTileClient(http).get(TILE_PATH) == (b"from upstream", "image/png")
    assert http.requested_urls == [f"{UPSTREAM_HOST}/{TILE_PATH}"]


async def test_get_reports_an_absent_tile_as_empty_and_a_failure_as_nothing():
    absent = FakeHttpClient(b"", "image/png", raises=_status_error(404))
    assert await JmaTileClient(absent).get(TILE_PATH) is EMPTY_TILE
    failing = FakeHttpClient(b"", "image/png", raises=_status_error(503))
    assert await JmaTileClient(failing).get("other/path/6/57/25.png") is None


async def test_absent_tile_is_not_counted_as_an_upstream_error():
    debug_log.reset_stats()
    await JmaTileClient(FakeHttpClient(b"", "image/png", raises=_status_error(404))).get(TILE_PATH)
    assert debug_log.get_stats()["external"]["weather:jma-tile"]["errors"] == 0
    await JmaTileClient(FakeHttpClient(b"", "image/png", raises=_status_error(500))).get("other/6/57/25.png")
    assert debug_log.get_stats()["external"]["weather:jma-tile"]["errors"] == 1


async def test_cache_hits_and_misses_are_counted_apart():
    debug_log.reset_stats()
    client = JmaTileClient(FakeHttpClient(b"unused", "image/png"))
    await client.get_cached(TILE_PATH)
    await client.store(TILE_PATH, b"tile", "image/png")
    await client.get_cached(TILE_PATH)
    stats = debug_log.get_stats()["external"]["weather:jma-tile"]
    assert (stats["cache_hits"], stats["cache_misses"]) == (1, 1)


async def test_consecutive_fetches_are_spaced_by_the_upstream_interval(monkeypatch):
    monkeypatch.setattr(settings, "jma_tile_upstream_max_requests_per_second", 10.0)
    client = JmaTileClient(FakeHttpClient(b"tile", "image/png"))
    await client.fetch(TILE_PATH)
    started = time.monotonic()
    await client.fetch(TILE_PATH)
    assert time.monotonic() - started >= 0.09


async def test_fetch_does_not_wait_when_the_interval_has_already_passed(monkeypatch):
    monkeypatch.setattr(settings, "jma_tile_upstream_max_requests_per_second", 2.0)
    jma_tile_client._last_fetch_at = time.monotonic() - 10.0
    started = time.monotonic()
    await JmaTileClient(FakeHttpClient(b"tile", "image/png")).fetch(TILE_PATH)
    assert time.monotonic() - started < 0.4


async def test_cache_hits_are_not_held_back_by_the_upstream_interval(monkeypatch):
    monkeypatch.setattr(settings, "jma_tile_upstream_max_requests_per_second", 1.0)
    client = JmaTileClient(FakeHttpClient(b"unused", "image/png"))
    await client.store(TILE_PATH, b"cached", "image/png")
    jma_tile_client._last_fetch_at = time.monotonic()
    started = time.monotonic()
    assert await client.get_cached(TILE_PATH) == (b"cached", "image/png")
    assert time.monotonic() - started < 0.5
