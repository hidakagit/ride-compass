"""`infrastructure/http_client.py`——外部APIへの共有HTTPクライアント（`get_http_client`・`close_all_http_clients`）。

共有のクライアントはプロセス大域に溜まるので、テストごとに空の置き場から始め、閉じる口で片付ける。

ここで見ないもの:
- クライアントを通した外部APIの呼び出し → 各クライアントのテスト（例: `test_simple_api_client.py`）
- 起動時のウォームアップとシャットダウンで閉じること → `main.py`のlifespan（結線のみ）
"""

import pytest

from app.infrastructure import http_client


@pytest.fixture(autouse=True)
async def empty_clients(monkeypatch):
    monkeypatch.setattr(http_client, "clients", {})
    yield
    await http_client.close_all_http_clients()


def test_one_client_is_kept_per_timeout():
    short = http_client.get_http_client(10.0)

    assert http_client.get_http_client(10.0) is short
    assert http_client.get_http_client(15.0) is not short


async def test_closing_closes_every_client_and_the_next_request_gets_an_open_one():
    clients = [http_client.get_http_client(10.0), http_client.get_http_client(15.0)]

    await http_client.close_all_http_clients()

    assert all(client.is_closed for client in clients)
    reopened = http_client.get_http_client(10.0)
    assert reopened not in clients
    assert not reopened.is_closed
