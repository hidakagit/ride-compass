"""`infrastructure/http_client.py`——timeoutごとに1本だけ持つHTTPクライアントの引き出し。

ここで見ないもの:

- どの呼び出しがどのtimeoutを要求するか → `app/api/dependencies.py`側の話
- 終了時に誰がいつ閉じるか（lifespanの順序） → `test_main_lifespan.py`
- 受け取ったクライアントで何をするか → 各クライアントのテスト

**通信はしない。** 確かめるのは引き出しの出し入れだけで、httpx自身の振る舞いは対象外。
引き出しはプロセス大域のため、各テストの前後で空にする。
"""

import httpx
import pytest

from app.infrastructure.http_client import close_all_http_clients, get_http_client

TIMEOUT_A = 7.5
TIMEOUT_B = 15.0


@pytest.fixture(autouse=True)
async def _empty_drawer():
    await close_all_http_clients()
    yield
    await close_all_http_clients()


async def test_asking_twice_for_the_same_timeout_gets_the_same_client():
    """要求のたびに作ると、SSLコンテキストの構築がイベントループを同期的に止める。"""
    assert get_http_client(TIMEOUT_A) is get_http_client(TIMEOUT_A)


async def test_each_timeout_gets_a_client_of_its_own():
    assert get_http_client(TIMEOUT_A) is not get_http_client(TIMEOUT_B)


async def test_the_client_waits_as_long_as_it_was_asked_to():
    """別のtimeoutの引き出しから配ると、短い締め切りを要求した呼び出しが長く待たされる。"""
    assert get_http_client(TIMEOUT_A).timeout == httpx.Timeout(TIMEOUT_A)


async def test_closing_shuts_every_client_that_was_handed_out():
    """開いたまま残すと、プロセスが終わるまで接続が残る。"""
    clients = [get_http_client(TIMEOUT_A), get_http_client(TIMEOUT_B)]

    await close_all_http_clients()

    assert [client.is_closed for client in clients] == [True, True]


async def test_a_request_after_closing_gets_a_fresh_client():
    """閉じたクライアントを配り続けると、以降のリクエストがすべて失敗する。"""
    closed = get_http_client(TIMEOUT_A)

    await close_all_http_clients()

    assert get_http_client(TIMEOUT_A) is not closed
