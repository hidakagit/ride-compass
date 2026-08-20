import httpx
import pytest

from app.domain.route import Coordinates
from app.infrastructure import weather_client as weather_client_module
from app.infrastructure.weather_client import WeatherClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, payload):
        self.call_count = 0
        self._payload = payload
        self.last_params = None

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        self.last_params = params
        return FakeResponse(self._payload)

    async def post(self, url, data=None, timeout=None):
        # get_forecast_many（改善計画T178フォローアップでPOSTへ変更）用。GETのparamsと
        # 同じ辞書がdataとして渡ってくるため、last_paramsへの記録先は共通化する。
        self.call_count += 1
        self.last_params = data
        return FakeResponse(self._payload)


class FailingHttpClient:
    async def get(self, url, params=None, timeout=None):
        raise httpx.RequestError("boom")

    async def post(self, url, data=None, timeout=None):
        raise httpx.RequestError("boom")


class TooManyRequestsResponse:
    status_code = 429
    headers: dict = {}

    def raise_for_status(self):
        raise httpx.HTTPStatusError("429 Too Many Requests", request=None, response=self)

    def json(self):
        raise AssertionError("json() should not be called when raise_for_status() raises")


class RetryThenSucceedHttpClient:
    """1回目・2回目は429、3回目(最終試行)で成功する上流を模する。"""

    def __init__(self, payload):
        self.call_count = 0
        self._payload = payload

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        if self.call_count < 3:
            return TooManyRequestsResponse()
        return FakeResponse(self._payload)


class AlwaysTooManyRequestsHttpClient:
    def __init__(self):
        self.call_count = 0

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        return TooManyRequestsResponse()


class RetryAfterZeroResponse:
    """Retry-After: 0（=即時再試行の指示。RFC 9110上有効な値）を返す429応答を模する。"""

    status_code = 429
    headers = {"Retry-After": "0"}

    def raise_for_status(self):
        raise httpx.HTTPStatusError("429 Too Many Requests", request=None, response=self)

    def json(self):
        raise AssertionError("json() should not be called when raise_for_status() raises")


class RetryAfterZeroThenSucceedHttpClient:
    """1回目はRetry-After: 0付きの429、2回目(最終試行)で成功する上流を模する。"""

    def __init__(self, payload):
        self.call_count = 0
        self._payload = payload

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        if self.call_count < 2:
            return RetryAfterZeroResponse()
        return FakeResponse(self._payload)


class RetryThenSucceedAfterConnectTimeoutHttpClient:
    """1回目はConnectTimeout、2回目(最終試行)で成功する上流を模する。"""

    def __init__(self, payload):
        self.call_count = 0
        self._payload = payload

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        if self.call_count < 2:
            raise httpx.ConnectTimeout("timed out")
        return FakeResponse(self._payload)


class AlwaysConnectTimeoutHttpClient:
    def __init__(self):
        self.call_count = 0

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        raise httpx.ConnectTimeout("timed out")

    async def post(self, url, data=None, timeout=None):
        self.call_count += 1
        raise httpx.ConnectTimeout("timed out")


@pytest.fixture(autouse=True)
def clear_weather_cache():
    weather_client_module._forecast_cache.clear()
    weather_client_module._wind_forecast_cache.clear()
    yield
    weather_client_module._forecast_cache.clear()
    weather_client_module._wind_forecast_cache.clear()


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """再試行の待機（RETRY_BACKOFF_SECONDS基準、MAX_RETRIES=4で最大数秒）を実時間で
    待たずにテストを高速化する。待機時間自体はテスト対象でないため実測不要。"""

    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(weather_client_module.asyncio, "sleep", instant_sleep)


async def test_get_forecast_reuses_cache_within_ttl():
    client = WeatherClient()
    http_client = FakeHttpClient({"current": {}, "hourly": {}})
    point = Coordinates(latitude=35.11, longitude=139.22)

    first = await client.get_forecast(http_client, point)
    second = await client.get_forecast(http_client, point)

    assert first == second
    assert http_client.call_count == 1


async def test_get_forecast_refetches_after_ttl_expires():
    client = WeatherClient()
    http_client = FakeHttpClient({"current": {}, "hourly": {}})
    point = Coordinates(latitude=35.33, longitude=139.44)

    await client.get_forecast(http_client, point)

    # キャッシュの取得時刻を強制的に過去にしてTTL失効をシミュレートする
    key = (
        round(point.latitude, weather_client_module.CACHE_PRECISION),
        round(point.longitude, weather_client_module.CACHE_PRECISION),
    )
    fetched_at, data = weather_client_module._forecast_cache[key]
    weather_client_module._forecast_cache[key] = (
        fetched_at - weather_client_module.CACHE_TTL_SECONDS - 1,
        data,
    )

    await client.get_forecast(http_client, point)

    assert http_client.call_count == 2


async def test_get_forecast_returns_none_on_request_error():
    client = WeatherClient()
    point = Coordinates(latitude=35.55, longitude=139.66)

    result = await client.get_forecast(FailingHttpClient(), point)

    assert result is None


async def test_get_forecast_retries_on_429_and_recovers():
    client = WeatherClient()
    http_client = RetryThenSucceedHttpClient({"current": {}, "hourly": {}})
    point = Coordinates(latitude=35.77, longitude=139.88)

    result = await client.get_forecast(http_client, point)

    assert result == {"current": {}, "hourly": {}}
    assert http_client.call_count == 3


async def test_get_forecast_returns_none_after_exhausting_429_retries():
    client = WeatherClient()
    http_client = AlwaysTooManyRequestsHttpClient()
    point = Coordinates(latitude=35.88, longitude=139.99)

    result = await client.get_forecast(http_client, point)

    assert result is None
    # 初回 + MAX_RETRIES回の再試行 = 呼び出し合計
    assert http_client.call_count == weather_client_module.MAX_RETRIES + 1


async def test_get_forecast_stops_retrying_once_budget_exhausted(monkeypatch):
    """RETRY_BUDGET_SECONDSを使い切ったら、MAX_RETRIESに達していなくても再試行を打ち切る
    （Open-Meteoが429を出し続ける間、フロントのfetchタイムアウトを超えて待ち続けないため）。"""
    monkeypatch.setattr(weather_client_module, "RETRY_BUDGET_SECONDS", 0.0)
    client = WeatherClient()
    http_client = AlwaysTooManyRequestsHttpClient()
    point = Coordinates(latitude=35.91, longitude=139.92)

    result = await client.get_forecast(http_client, point)

    assert result is None
    assert http_client.call_count == 1  # 初回のみ。予算0のため再試行が1回も発生しない


async def test_get_forecast_honors_retry_after_zero_header(monkeypatch):
    """Retry-After: 0はPythonのor演算子だと「未指定」に誤判定され指数バックオフへ
    フォールバックしうるバグの回帰テスト。0は「即時再試行」の明示指示として尊重され、
    待機秒数が0になる（ジッターを掛けても0×係数=0のまま）ことを確認する。"""
    waits: list[float] = []

    async def recording_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(weather_client_module.asyncio, "sleep", recording_sleep)

    client = WeatherClient()
    http_client = RetryAfterZeroThenSucceedHttpClient({"current": {}, "hourly": {}})
    point = Coordinates(latitude=35.93, longitude=139.94)

    result = await client.get_forecast(http_client, point)

    assert result == {"current": {}, "hourly": {}}
    assert waits == [0.0]


async def test_get_forecast_retries_on_connect_timeout_and_recovers():
    client = WeatherClient()
    http_client = RetryThenSucceedAfterConnectTimeoutHttpClient({"current": {}, "hourly": {}})
    point = Coordinates(latitude=35.99, longitude=139.11)

    result = await client.get_forecast(http_client, point)

    assert result == {"current": {}, "hourly": {}}
    assert http_client.call_count == 2


async def test_get_forecast_returns_none_after_exhausting_connect_timeout_retries():
    client = WeatherClient()
    http_client = AlwaysConnectTimeoutHttpClient()
    point = Coordinates(latitude=35.22, longitude=139.33)

    result = await client.get_forecast(http_client, point)

    assert result is None
    assert http_client.call_count == weather_client_module.MAX_RETRIES + 1


async def test_get_forecast_uses_stale_cache_when_refetch_fails():
    client = WeatherClient()
    point = Coordinates(latitude=35.44, longitude=139.55)
    await client.get_forecast(FakeHttpClient({"current": {}, "hourly": {}, "tag": "original"}), point)

    key = WeatherClient.cache_key(point)
    fetched_at, data = weather_client_module._forecast_cache[key]
    weather_client_module._forecast_cache[key] = (fetched_at - weather_client_module.CACHE_TTL_SECONDS - 1, data)

    result = await client.get_forecast(AlwaysConnectTimeoutHttpClient(), point)

    assert result == {"current": {}, "hourly": {}, "tag": "original"}


async def test_get_forecast_returns_none_when_stale_cache_exceeds_fallback_window():
    client = WeatherClient()
    point = Coordinates(latitude=35.46, longitude=139.57)
    await client.get_forecast(FakeHttpClient({"current": {}, "hourly": {}}), point)

    key = WeatherClient.cache_key(point)
    fetched_at, data = weather_client_module._forecast_cache[key]
    weather_client_module._forecast_cache[key] = (
        fetched_at - weather_client_module.STALE_FALLBACK_MAX_AGE_SECONDS - 1,
        data,
    )

    result = await client.get_forecast(AlwaysConnectTimeoutHttpClient(), point)

    assert result is None


async def test_get_forecast_many_uses_stale_cache_for_point_that_fails_refetch():
    client = WeatherClient()
    point = Coordinates(latitude=35.48, longitude=139.59)
    await client.get_forecast_many(FakeHttpClient([{"current": {}, "hourly": {}, "tag": "stale"}]), [point])

    key = WeatherClient.cache_key(point)
    fetched_at, data = weather_client_module._wind_forecast_cache[key]
    weather_client_module._wind_forecast_cache[key] = (
        fetched_at - weather_client_module.CACHE_TTL_SECONDS - 1,
        data,
    )

    results = await client.get_forecast_many(AlwaysConnectTimeoutHttpClient(), [point])

    assert results[key]["tag"] == "stale"


async def test_get_forecast_many_batches_uncached_points_into_one_request():
    client = WeatherClient()
    payload = [{"current": {}, "hourly": {}, "tag": "a"}, {"current": {}, "hourly": {}, "tag": "b"}]
    http_client = FakeHttpClient(payload)
    points = [Coordinates(latitude=35.10, longitude=139.10), Coordinates(latitude=35.20, longitude=139.20)]

    results = await client.get_forecast_many(http_client, points)

    assert http_client.call_count == 1
    assert http_client.last_params["latitude"] == "35.1,35.2"
    assert http_client.last_params["longitude"] == "139.1,139.2"
    assert results[WeatherClient.cache_key(points[0])]["tag"] == "a"
    assert results[WeatherClient.cache_key(points[1])]["tag"] == "b"


async def test_get_forecast_many_dedupes_points_rounding_to_same_cache_key():
    client = WeatherClient()
    http_client = FakeHttpClient([{"current": {}, "hourly": {}}])
    p1 = Coordinates(latitude=35.101, longitude=139.101)
    p2 = Coordinates(latitude=35.104, longitude=139.104)  # 丸め精度2桁で同じキーになる

    results = await client.get_forecast_many(http_client, [p1, p2])

    assert http_client.call_count == 1
    assert http_client.last_params["latitude"] == "35.1"
    assert len(results) == 1


async def test_get_forecast_many_skips_already_cached_points():
    client = WeatherClient()
    cached_point = Coordinates(latitude=35.30, longitude=139.30)
    await client.get_forecast_many(
        FakeHttpClient([{"current": {}, "hourly": {}, "tag": "cached"}]), [cached_point]
    )

    fresh_point = Coordinates(latitude=35.40, longitude=139.40)
    http_client = FakeHttpClient([{"current": {}, "hourly": {}, "tag": "fresh"}])

    results = await client.get_forecast_many(http_client, [cached_point, fresh_point])

    assert http_client.call_count == 1
    assert http_client.last_params["latitude"] == "35.4"
    assert results[WeatherClient.cache_key(cached_point)]["tag"] == "cached"
    assert results[WeatherClient.cache_key(fresh_point)]["tag"] == "fresh"


async def test_get_forecast_and_get_forecast_many_do_not_share_cache():
    """get_forecast（単一地点、全変数）とget_forecast_many（複数地点、風のみ）は
    キャッシュを分離している（weather_client.py _wind_forecast_cache参照）。
    片方の応答（変数セットが異なる）がもう片方のキャッシュヒットとして誤って
    読まれないことの回帰テスト。"""
    client = WeatherClient()
    point = Coordinates(latitude=35.31, longitude=139.31)
    await client.get_forecast(FakeHttpClient({"current": {}, "hourly": {}, "tag": "full"}), point)

    http_client = FakeHttpClient([{"current": {}, "hourly": {}, "tag": "wind-only"}])
    await client.get_forecast_many(http_client, [point])

    assert http_client.call_count == 1  # get_forecastのキャッシュはヒットせず再取得された


async def test_get_forecast_many_returns_none_for_all_on_failure():
    client = WeatherClient()
    points = [Coordinates(latitude=35.50, longitude=139.50), Coordinates(latitude=35.60, longitude=139.60)]

    results = await client.get_forecast_many(FailingHttpClient(), points)

    assert len(results) == 2
    assert all(value is None for value in results.values())


async def test_get_forecast_many_single_uncached_point_handles_object_response():
    client = WeatherClient()
    # Open-Meteoは地点が1件のみのリクエストだと配列ではなくobjectを返す
    http_client = FakeHttpClient({"current": {}, "hourly": {}})
    point = Coordinates(latitude=35.71, longitude=139.71)

    results = await client.get_forecast_many(http_client, [point])

    assert results[WeatherClient.cache_key(point)] == {"current": {}, "hourly": {}}
