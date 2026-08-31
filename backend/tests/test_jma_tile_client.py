import pytest

from app.infrastructure import jma_tile_client, jma_tile_redis_cache
from app.infrastructure.jma_tile_client import JmaTileClient


class FakeRedis:
    """jma_tile_redis_cache.pyが使うコマンド（get/set）だけを実装したフェイク
    （test_weather_client_cache.py: FakeRedisと同じパターン）。"""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


@pytest.fixture(autouse=True)
def use_fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    # targetTimes.json用のプロセス内TTLキャッシュはテスト間で共有されるモジュール変数のため、
    # 各テストの独立性のため空にしてから始める。
    jma_tile_client._target_times_cache.clear()
    yield


@pytest.fixture(autouse=True)
def no_real_upstream_rate_limit_wait(monkeypatch):
    """改善計画T514: fetch()が実フェッチ前に待つレート制限（_wait_for_upstream_rate_limit、
    モジュールレベルの_last_fetch_atで前回時刻を記録）は、テスト間で状態が漏れる
    （前のテストの最終フェッチ時刻が残ったまま次のテストの初回フェッチが待たされる）ため
    毎回リセットし、asyncio.sleepも実待機せず即座に返すようにする（待機時間自体は多くの
    テストの対象ではないため、実測不要。ペーシングそのものを検証するテスト
    [test_fetch_paces_requests_to_the_configured_upstream_rate]だけがこのフィクスチャの
    sleepパッチを上書きする）。"""
    monkeypatch.setattr(jma_tile_client, "_last_fetch_at", None)

    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(jma_tile_client.asyncio, "sleep", instant_sleep)
    yield


class FakeResponse:
    def __init__(self, content: bytes, content_type: str):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        pass


class FakeHttpClient:
    def __init__(self, content: bytes, content_type: str, raises=None):
        self._content = content
        self._content_type = content_type
        self._raises = raises
        self.requested_urls = []

    async def get(self, url):
        self.requested_urls.append(url)
        if self._raises:
            raise self._raises
        return FakeResponse(self._content, self._content_type)


async def test_get_passes_through_binary_tile_unmodified():
    http_client = FakeHttpClient(b"\x89PNG...", "image/png")
    client = JmaTileClient(http_client)

    content, content_type = await client.get(
        "bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
    )

    assert content == b"\x89PNG..."
    assert content_type == "image/png"


async def test_get_caches_tile_and_skips_second_upstream_request():
    http_client = FakeHttpClient(b"cached-bytes", "image/png")
    client = JmaTileClient(http_client)
    path = "bosai/jmatile/data/nowc/20260829170000/none/20260829170500/surf/hrpns/10/909/402.png"

    await client.get(path)
    await client.get(path)

    assert len(http_client.requested_urls) == 1


async def test_get_caches_target_times_separately_from_redis_tile_cache():
    """targetTimes.jsonはRedis cache-aside（jma_tile_redis_cache.py）ではなく、短TTLの
    プロセス内キャッシュに乗ることを確認する（更新頻度が高いデータをTTL20分のタイル
    キャッシュへ乗せると、更新後も古い内容をより長く返し続けてしまうため）。"""
    http_client = FakeHttpClient(b'{"basetime":"1"}', "application/json")
    client = JmaTileClient(http_client)
    path = "bosai/jmatile/data/risk/targetTimes.json"

    await client.get(path)

    assert await jma_tile_redis_cache.get(path) is None
    assert jma_tile_client._target_times_cache.get(path) is not None


async def test_get_caches_target_times_and_skips_second_upstream_request():
    http_client = FakeHttpClient(b'{"basetime":"1"}', "application/json")
    client = JmaTileClient(http_client)
    path = "bosai/jmatile/data/rasrf/targetTimes.json"

    await client.get(path)
    await client.get(path)

    assert len(http_client.requested_urls) == 1


async def test_get_returns_none_on_upstream_failure():
    import httpx

    http_client = FakeHttpClient(
        b"", "text/plain", raises=httpx.ConnectError("boom", request=httpx.Request("GET", "http://x"))
    )
    client = JmaTileClient(http_client)

    result = await client.get("bosai/jmatile/data/risk/targetTimes.json")

    assert result is None


async def test_get_cached_returns_none_without_touching_upstream():
    http_client = FakeHttpClient(b"tile-bytes", "image/png")
    client = JmaTileClient(http_client)
    path = "bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"

    result = await client.get_cached(path)

    assert result is None
    assert http_client.requested_urls == []


async def test_get_cached_hits_after_fetch_writes_cache():
    http_client = FakeHttpClient(b"tile-bytes", "image/png")
    client = JmaTileClient(http_client)
    path = "bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"

    await client.fetch(path)
    cached = await client.get_cached(path)

    assert cached == (b"tile-bytes", "image/png")
    assert len(http_client.requested_urls) == 1


async def test_fetch_always_hits_upstream_even_if_cached():
    """fetch()はキャッシュを参照せず必ず外部フェッチする（呼び出し元がレート制限を
    適用済みの前提で使うメソッドのため）。"""
    http_client = FakeHttpClient(b"tile-bytes", "image/png")
    client = JmaTileClient(http_client)
    path = "bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"

    await client.fetch(path)
    await client.fetch(path)

    assert len(http_client.requested_urls) == 2


async def test_fetch_paces_requests_to_the_configured_upstream_rate(monkeypatch):
    """改善計画T514: 実フェッチの間隔がsettings.jma_tile_upstream_max_requests_per_second
    を守るよう待機することを検証する。実時間を待たず、time.monotonic/asyncio.sleepを
    差し替えて呼び出し引数だけを見る（no_real_upstream_rate_limit_waitフィクスチャの
    instant_sleepパッチをこのテストの中でだけ上書きする）。"""
    fake_now = [1000.0]

    def fake_monotonic():
        return fake_now[0]

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        fake_now[0] += seconds

    monkeypatch.setattr(jma_tile_client.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(jma_tile_client.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(jma_tile_client.settings, "jma_tile_upstream_max_requests_per_second", 5.0)

    http_client = FakeHttpClient(b"tile-bytes", "image/png")
    client = JmaTileClient(http_client)

    await client.fetch("bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png")
    assert sleep_calls == []  # 初回（直前フェッチが無い）は待たない

    await client.fetch("bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/806.png")
    assert sleep_calls == [pytest.approx(0.2)]  # 秒5回=0.2秒間隔を守るぶんだけ待つ
