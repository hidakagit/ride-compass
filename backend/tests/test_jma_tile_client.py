"""`infrastructure/jma_tile_client.py`——JMA bosaiのプロキシ、2系統のキャッシュ、上流への秒間上限、時刻一覧を行へ解くこと。

ここで見ないもの:
- 共有キャッシュ（Redis）の格納形式・TTL・空タイルの表し方 → `test_jma_tile_redis_cache.py`
- 404と他の失敗をHTTPステータスへ割り当てる判断、利用者側のレート制限 → `api/routers/jma_tile.py`側
- 上流に無いズームを組み立てる補間 → `jma_tile_interpolation.py`側

共有キャッシュと上流HTTPは差し替えて与える。上流はrespxの経路で応答を決める。
上流への秒間上限の待ちは実時間を消費させず、待った長さだけを記録する（時計は`clock`で止める）。
"""

import json
import time

import httpx
import pytest
import respx

from app.domain.jma_tile_specs import JmaFrame, TargetTimesRow
from app.infrastructure import jma_tile_client
from tests.fake_external_log import record_external_calls
from tests.fake_http import client_for

TILE_PATH = "bosai/jmatile/data/nowc/20260101000000/none/20260101000000/surf/hrpns/6/57/25.png"
TARGET_TIMES_PATH = "bosai/jmatile/data/nowc/targetTimes_N1.json"
FEATURES_PATH = (
    "bosai/jmatile/data/nowc/20260101000000/none/20260101000000/surf/slmcs_unify/data.geojson?id=slmcs_unify"
)

#: 差し替え前の共有キャッシュが配っている「描くものが無い」センチネル。
EMPTY_TILE = jma_tile_client.jma_tile_redis_cache.EMPTY_TILE


class FakeRedisCache:
    """`jma_tile_redis_cache`の差し替え。タイル本体の保存先。"""

    EMPTY_TILE = EMPTY_TILE

    def __init__(self, seed: dict | None = None):
        self.entries = dict(seed or {})

    async def get(self, path):
        return self.entries.get(path)

    async def set(self, path, content, content_type):
        self.entries[path] = (content, content_type)

    async def set_empty(self, path):
        self.entries[path] = EMPTY_TILE


class RecordingSleep:
    """`asyncio`の差し替え。待つ代わりに待った長さを憶える。"""

    def __init__(self):
        self.slept: list[float] = []

    async def sleep(self, seconds):
        self.slept.append(seconds)


@pytest.fixture(autouse=True)
def reset_module_state():
    """プロセス内に残る時刻一覧キャッシュと直前フェッチ時刻を、テストごとに空へ戻す。"""
    jma_tile_client._target_times_cache.clear()
    jma_tile_client._last_fetch_at = None
    yield
    jma_tile_client._target_times_cache.clear()
    jma_tile_client._last_fetch_at = None


@pytest.fixture
def sleeps(monkeypatch):
    recorder = RecordingSleep()
    monkeypatch.setattr(jma_tile_client, "asyncio", recorder)
    return recorder


def install_fakes(monkeypatch, redis=None):
    """共有キャッシュと`log_external_call`を差し替え、記録先を返す。"""
    redis = redis or FakeRedisCache()
    monkeypatch.setattr(jma_tile_client, "jma_tile_redis_cache", redis)
    return redis, record_external_calls(monkeypatch, jma_tile_client)


@pytest.fixture
def upstream():
    """JMA bosaiの代役。応答はテストごとに経路を足して決め、経路が無ければ引いた時点で失敗する。"""
    return respx.Router(base_url=jma_tile_client.UPSTREAM_HOST)


def make_client(upstream):
    return jma_tile_client.JmaTileClient(client_for(upstream))


def requested_urls(upstream):
    return [str(call.request.url) for call in upstream.calls]


# --- 時刻一覧かタイル本体かの見分け ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "bosai/jmatile/data/nowc/targetTimes.json",
        "bosai/jmatile/data/nowc/targetTimes_N1.json",
        "bosai/jmatile/data/nowc/targetTimes_N3.json",
    ],
)
def test_time_listing_is_recognised_whatever_series_it_belongs_to(path):
    """時刻一覧だけが同じURLのまま中身を更新するため、見分けを誤ると古い時刻を配り続ける。"""
    assert jma_tile_client.is_target_times_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        TILE_PATH,
        "bosai/jmatile/data/nowc/targetTimes.json/6/57/25.png",
        "bosai/jmatile/data/nowc/notatargetTimes.json.png",
        "bosai/jmatile/data/targetTimes/nowc.json",
    ],
)
def test_anything_that_is_not_the_listing_file_itself_is_treated_as_a_tile(path):
    assert jma_tile_client.is_target_times_path(path) is False


# --- 上流への秒間上限 -----------------------------------------------------------------


async def test_the_first_upstream_request_is_not_held_back(sleeps):
    await jma_tile_client._wait_for_upstream_rate_limit()

    assert sleeps.slept == []
    assert jma_tile_client._last_fetch_at is not None


async def test_back_to_back_upstream_requests_are_spaced_by_the_configured_rate(sleeps, monkeypatch, clock):
    """利用者が何人いてもJMAへの問い合わせが秒間上限を超えないようにする。"""
    monkeypatch.setattr(jma_tile_client.settings, "jma_tile_upstream_max_requests_per_second", 4.0)
    jma_tile_client._last_fetch_at = time.monotonic()

    await jma_tile_client._wait_for_upstream_rate_limit()

    assert sleeps.slept == [0.25]


async def test_an_upstream_request_after_the_interval_is_not_held_back(sleeps, monkeypatch):
    monkeypatch.setattr(jma_tile_client.settings, "jma_tile_upstream_max_requests_per_second", 4.0)
    jma_tile_client._last_fetch_at = time.monotonic() - 10.0

    await jma_tile_client._wait_for_upstream_rate_limit()

    assert sleeps.slept == []


# --- キャッシュだけを見る呼び出し -----------------------------------------------------


async def test_a_cached_time_listing_comes_from_this_process(monkeypatch, upstream):
    """時刻一覧は短い周期で入れ替わるため、共有キャッシュではなくプロセス内に置く。"""
    redis, recorded = install_fakes(monkeypatch)
    jma_tile_client._target_times_cache[TARGET_TIMES_PATH] = (b"{}", "application/json")

    result = await make_client(upstream).get_cached(TARGET_TIMES_PATH)

    assert result == (b"{}", "application/json")
    assert redis.entries == {}
    assert not upstream.calls
    assert recorded[0].fields["cache"] == "hit"
    assert recorded[0].fields["result"] == "ok"


async def test_a_cached_tile_comes_from_the_shared_cache(monkeypatch, upstream):
    redis, recorded = install_fakes(monkeypatch, FakeRedisCache({TILE_PATH: (b"png", "image/png")}))

    result = await make_client(upstream).get_cached(TILE_PATH)

    assert result == (b"png", "image/png")
    assert not upstream.calls
    assert recorded[0].fields["cache"] == "hit"


async def test_a_cache_lookup_never_reaches_upstream_when_nothing_is_stored(monkeypatch, upstream, sleeps):
    """キャッシュ参照だけの呼び出しは、上流への秒間上限を一切消費しない。"""
    redis, recorded = install_fakes(monkeypatch)

    result = await make_client(upstream).get_cached(TILE_PATH)

    assert result is None
    assert not upstream.calls
    assert sleeps.slept == []
    assert recorded[0].fields["cache"] == "miss"
    assert recorded[0].fields["result"] == "ok"


# --- 上流フェッチ ---------------------------------------------------------------------


async def test_a_fetched_tile_is_kept_in_the_shared_cache(monkeypatch, upstream, sleeps):
    redis, recorded = install_fakes(monkeypatch)
    upstream.route().respond(content=b"png", content_type="image/png")

    result = await make_client(upstream).fetch(TILE_PATH)

    assert result == (b"png", "image/png")
    assert requested_urls(upstream) == [f"{jma_tile_client.UPSTREAM_HOST}/{TILE_PATH}"]
    assert redis.entries == {TILE_PATH: (b"png", "image/png")}
    assert recorded[0].fields["cache"] == "miss"
    assert recorded[0].fields["result"] == "ok"
    assert recorded[0].fields["status"] == 200


async def test_a_fetched_time_listing_is_kept_in_this_process(monkeypatch, upstream, sleeps):
    redis, _ = install_fakes(monkeypatch)
    upstream.route().respond(content=b"[]", content_type="application/json")

    result = await make_client(upstream).fetch(TARGET_TIMES_PATH)

    assert result == (b"[]", "application/json")
    assert jma_tile_client._target_times_cache[TARGET_TIMES_PATH] == (b"[]", "application/json")
    assert redis.entries == {}


async def test_a_fetch_without_a_content_type_header_falls_back_to_a_generic_one(monkeypatch, upstream, sleeps):
    redis, _ = install_fakes(monkeypatch)
    upstream.route().respond(content=b"png")

    result = await make_client(upstream).fetch(TILE_PATH)

    assert result == (b"png", "application/octet-stream")
    assert redis.entries == {TILE_PATH: (b"png", "application/octet-stream")}


async def test_every_upstream_fetch_waits_out_the_rate_limit_first(monkeypatch, upstream, sleeps):
    install_fakes(monkeypatch)
    jma_tile_client._last_fetch_at = time.monotonic()
    upstream.route().respond(content=b"png", content_type="image/png")

    await make_client(upstream).fetch(TILE_PATH)

    assert len(sleeps.slept) == 1


async def test_a_missing_tile_is_raised_apart_from_other_failures_and_remembered_as_empty(monkeypatch, upstream, sleeps):
    """疎な格子では在否の穴が平常運転の一部なので、エラー集計へ載せず、次回は問い合わせない。"""
    redis, recorded = install_fakes(monkeypatch)
    upstream.route().respond(404)

    with pytest.raises(jma_tile_client.JmaTileNotFoundError):
        await make_client(upstream).fetch(TILE_PATH)

    assert redis.entries == {TILE_PATH: EMPTY_TILE}
    assert recorded[0].fields["result"] == "ok"
    assert recorded[0].fields["status"] == 404


async def test_features_not_yet_delivered_are_raised_but_not_remembered(monkeypatch, upstream, sleeps):
    """配信元はコマの地物を配信するまで404を返す。覚えると、配信された後もその間は「無い」を返し続ける。"""
    redis, recorded = install_fakes(monkeypatch)
    upstream.route().respond(404)

    with pytest.raises(jma_tile_client.JmaTileNotFoundError):
        await make_client(upstream).fetch(FEATURES_PATH)

    assert redis.entries == {}
    assert recorded[0].fields["result"] == "ok"


async def test_a_missing_time_listing_is_remembered_as_empty_in_this_process(monkeypatch, upstream, sleeps):
    redis, _ = install_fakes(monkeypatch)
    upstream.route().respond(404)

    with pytest.raises(jma_tile_client.JmaTileNotFoundError):
        await make_client(upstream).fetch(TARGET_TIMES_PATH)

    assert jma_tile_client._target_times_cache[TARGET_TIMES_PATH] is EMPTY_TILE
    assert redis.entries == {}


async def test_an_upstream_server_error_is_reported_as_a_failure(monkeypatch, upstream, sleeps):
    """404以外のステータスは取得失敗で、空だと憶えない（次回また取りに行く）。"""
    redis, recorded = install_fakes(monkeypatch)
    upstream.route().respond(503)

    result = await make_client(upstream).fetch(TILE_PATH)

    assert result is None
    assert redis.entries == {}
    assert recorded[0].fields["result"] == "error"
    assert recorded[0].fields["error_type"]


async def test_an_upstream_transport_failure_is_reported_as_a_failure(monkeypatch, upstream, sleeps):
    redis, recorded = install_fakes(monkeypatch)
    upstream.route().mock(side_effect=httpx.ConnectTimeout)

    result = await make_client(upstream).fetch(TILE_PATH)

    assert result is None
    assert redis.entries == {}
    assert recorded[0].fields["result"] == "error"
    assert recorded[0].fields["error_type"]


# --- 上流を経ずに作ったタイルの書き戻し -----------------------------------------------


async def test_a_locally_built_tile_is_stored_where_fetched_tiles_go(monkeypatch, upstream, sleeps):
    """上流に実体が無いズームを組み立てた結果も、次回からそのまま配れるようにする。"""
    redis, _ = install_fakes(monkeypatch)

    await make_client(upstream).store(TILE_PATH, b"built", "image/png")

    assert redis.entries == {TILE_PATH: (b"built", "image/png")}
    assert not upstream.calls
    assert sleeps.slept == []


async def test_a_locally_built_time_listing_is_stored_in_this_process(monkeypatch, upstream, sleeps):
    redis, _ = install_fakes(monkeypatch)

    await make_client(upstream).store(TARGET_TIMES_PATH, b"[]", "application/json")

    assert jma_tile_client._target_times_cache[TARGET_TIMES_PATH] == (b"[]", "application/json")
    assert redis.entries == {}


# --- キャッシュ参照とフェッチをまとめた呼び出し ---------------------------------------


async def test_a_cached_tile_is_returned_without_a_fetch(monkeypatch, upstream, sleeps):
    redis, _ = install_fakes(monkeypatch, FakeRedisCache({TILE_PATH: (b"png", "image/png")}))
    upstream.route().respond(content=b"other", content_type="image/png")

    result = await make_client(upstream).get(TILE_PATH)

    assert result == (b"png", "image/png")
    assert not upstream.calls
    assert sleeps.slept == []


async def test_an_uncached_tile_falls_through_to_a_fetch(monkeypatch, upstream, sleeps):
    redis, _ = install_fakes(monkeypatch)
    upstream.route().respond(content=b"png", content_type="image/png")

    result = await make_client(upstream).get(TILE_PATH)

    assert result == (b"png", "image/png")
    assert requested_urls(upstream) == [f"{jma_tile_client.UPSTREAM_HOST}/{TILE_PATH}"]


async def test_a_missing_tile_counts_as_nothing_to_draw_rather_than_a_failure(monkeypatch, upstream, sleeps):
    """平常時は取得のほとんどが空のため、空を失敗として数えると本物の障害が埋もれる。"""
    redis, _ = install_fakes(monkeypatch)
    upstream.route().respond(404)

    result = await make_client(upstream).get(TILE_PATH)

    assert isinstance(result, jma_tile_client.EmptyTile)


async def test_a_failed_fetch_stays_a_failure(monkeypatch, upstream, sleeps):
    redis, _ = install_fakes(monkeypatch)
    upstream.route().mock(side_effect=httpx.ConnectTimeout)

    result = await make_client(upstream).get(TILE_PATH)

    assert result is None


# --- 時刻一覧を行へ解く ---------------------------------------------------------------


async def _target_time_rows(monkeypatch, content: bytes):
    install_fakes(monkeypatch)
    upstream = respx.Router()
    upstream.route().respond(content=content, content_type="application/json")
    return await jma_tile_client.get_target_times(make_client(upstream), TARGET_TIMES_PATH)


async def test_a_time_listing_row_becomes_a_frame_and_the_elements_it_has_tiles_for(monkeypatch, sleeps):
    # 行の形は2026-09-27に取得した時刻一覧のまま（降水短時間予報は`member`を持ち、ナウキャストは持たない）。
    content = json.dumps([
        {"basetime": "20260926220000", "validtime": "20260927130000", "member": "none",
         "elements": ["rasrf", "rasrf_point", "rasrf_nd"]},
        {"basetime": "20260926224000", "validtime": "20260926224000", "elements": ["hrpns", "hrpns_nd"]},
    ]).encode()

    rows = await _target_time_rows(monkeypatch, content)

    assert rows == [
        TargetTimesRow(JmaFrame("20260926220000", "none", "20260927130000"), ("rasrf", "rasrf_point", "rasrf_nd")),
        TargetTimesRow(JmaFrame("20260926224000", "none", "20260926224000"), ("hrpns", "hrpns_nd")),
    ]


async def test_rows_without_the_frame_times_are_skipped(monkeypatch, sleeps):
    content = json.dumps([
        {"basetime": "20260926224000", "elements": ["hrpns"]},
        "broken",
        {"basetime": "20260926224000", "validtime": "20260926224000"},
    ]).encode()

    rows = await _target_time_rows(monkeypatch, content)

    assert rows == [TargetTimesRow(JmaFrame("20260926224000", "none", "20260926224000"), ())]


@pytest.mark.parametrize("content", [b"<html>maintenance</html>", b'{"basetime": "20260926224000"}'])
async def test_a_time_listing_that_is_not_a_json_array_reads_as_nothing(monkeypatch, sleeps, content):
    assert await _target_time_rows(monkeypatch, content) is None
