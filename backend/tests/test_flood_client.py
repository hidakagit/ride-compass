"""`infrastructure/flood_client.py`——指定河川洪水予報の電文一覧を引く。

ここで見ないもの:
- TTLキャッシュの引き当てと、失敗をNoneへ倒す骨格 → `test_simple_api_client.py`
- 電文の解釈（発表か解除か・対象河川） → `test_flood_forecast_domain.py`
"""

import pytest

from app.infrastructure import flood_client
from tests.fake_api_http import FakeHttpClient


@pytest.fixture(autouse=True)
def _clear_cache():
    flood_client._flood_cache.clear()
    yield
    flood_client._flood_cache.clear()


async def test_documents_pass_through_without_reshaping():
    client = FakeHttpClient([{"river": "a"}, {"river": "b"}])

    assert await flood_client.fetch_flood_documents(client) == [{"river": "a"}, {"river": "b"}]


async def test_non_list_response_yields_none():
    """配列でない応答をそのまま通すと、電文を1件ずつ読む呼び出し元が落ちる。"""
    client = FakeHttpClient({"message": "maintenance"})

    assert await flood_client.fetch_flood_documents(client) is None
