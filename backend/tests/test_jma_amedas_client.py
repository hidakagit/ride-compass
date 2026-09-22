"""`infrastructure/jma_amedas_client.py`——観測所マスタ・最新観測時刻・観測値を引く。

ここで見ないもの:
- TTLキャッシュの引き当てと、失敗をNoneへ倒す骨格 → `test_simple_api_client.py`
- [度, 分]から10進度への変換・最寄り観測所の選択・観測値の読み替え
  → `test_jma_amedas_service.py`
"""

import pytest

from app.infrastructure import jma_amedas_client
from tests.fake_api_http import FailingHttpClient, FakeHttpClient, FakeResponse


class PerUrlHttpClient:
    """要求URLごとに違う応答を返す上流。

    共有フェイク（`tests/fake_api_http.py`）は同じペイロードを返し続けるため、
    「要求した時刻がURLへ載っているか」をこれでしか見られない。登録の無いURLを
    要求されたらKeyErrorで落ちる（どのURLを引いたかが失敗時に出る）。
    """

    def __init__(self, payloads: dict):
        self._payloads = payloads

    async def get(self, url, params=None, timeout=None):
        return FakeResponse(self._payloads[url])


@pytest.fixture(autouse=True)
def _clear_caches():
    jma_amedas_client._station_table_cache.clear()
    jma_amedas_client._latest_time_cache.clear()
    yield
    jma_amedas_client._station_table_cache.clear()
    jma_amedas_client._latest_time_cache.clear()


async def test_station_table_passes_through_degree_minute_arrays():
    client = FakeHttpClient({"44132": {"lat": [35, 41.4], "lon": [139, 45.6], "kjName": "東京"}})

    table = await jma_amedas_client.fetch_station_table(client)

    assert table == {"44132": {"lat": [35, 41.4], "lon": [139, 45.6], "kjName": "東京"}}


async def test_latest_observation_time_drops_surrounding_whitespace():
    """改行が残ったままだと観測値のURLが組み立てられず、観測値が1つも出なくなる。"""
    client = FakeHttpClient(text=" 2026-08-29T17:00:00+09:00\n")

    assert await jma_amedas_client.fetch_latest_observation_time(client) == "2026-08-29T17:00:00+09:00"


async def test_blank_latest_observation_time_yields_none():
    """空文字を時刻として返すと、呼び出し元が空のURLを引きに行く。"""
    client = FakeHttpClient(text="   \n")

    assert await jma_amedas_client.fetch_latest_observation_time(client) is None


async def test_observation_map_requests_the_given_timestamp():
    """要求した時刻がURLへ載らないと、いつまでも同じ（古い）観測値が返る。"""
    template = jma_amedas_client.AMEDAS_OBSERVATION_URL_TEMPLATE
    client = PerUrlHttpClient(
        {
            template.format(timestamp="20260829170000"): {"44132": {"temp": [30.1, 0]}},
            template.format(timestamp="20260829171000"): {"44132": {"temp": [29.8, 0]}},
        }
    )

    first = await jma_amedas_client.fetch_observation_map(client, "20260829170000")
    second = await jma_amedas_client.fetch_observation_map(client, "20260829171000")

    assert first == {"44132": {"temp": [30.1, 0]}}
    assert second == {"44132": {"temp": [29.8, 0]}}


async def test_observation_map_yields_none_when_upstream_fails():
    """例外を外へ出すと、観測値が欠けただけで天候の応答全体が失敗する。"""
    assert await jma_amedas_client.fetch_observation_map(FailingHttpClient(), "20260829170000") is None
