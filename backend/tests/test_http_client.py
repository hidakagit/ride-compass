"""http_client.pyの単体テスト（改善計画T331）。

get_http_clientの唯一の要件（timeoutの値ごとにクライアントを1つだけ生成してキャッシュ
する。同じtimeout値なら同じインスタンスを返す、異なるtimeout値なら別インスタンスを
返す）を検証する。
"""

import httpx

from app.infrastructure import http_client


def _clear_clients():
    # モジュールグローバルのキャッシュ（_clients）のため、他のテストへ漏れないよう
    # 前後でクリアする（graph_material_cacheの既存テストと同じ考え方）。
    http_client._clients.clear()


class TestGetHttpClient:
    def setup_method(self):
        _clear_clients()

    def teardown_method(self):
        _clear_clients()

    def test_same_timeout_returns_same_instance(self):
        client1 = http_client.get_http_client(5.0)
        client2 = http_client.get_http_client(5.0)
        assert client1 is client2

    def test_different_timeout_returns_different_instance(self):
        client1 = http_client.get_http_client(5.0)
        client2 = http_client.get_http_client(10.0)
        assert client1 is not client2

    def test_returns_async_client_instance(self):
        client = http_client.get_http_client(5.0)
        assert isinstance(client, httpx.AsyncClient)

    def test_client_timeout_matches_requested_value(self):
        client = http_client.get_http_client(7.5)
        assert client.timeout == httpx.Timeout(7.5)

    def test_repeated_calls_do_not_grow_cache_for_same_timeout(self):
        for _ in range(5):
            http_client.get_http_client(3.0)
        assert len(http_client._clients) == 1

    def test_multiple_distinct_timeouts_are_all_cached(self):
        http_client.get_http_client(1.0)
        http_client.get_http_client(2.0)
        http_client.get_http_client(3.0)
        assert len(http_client._clients) == 3
