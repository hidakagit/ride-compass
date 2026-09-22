"""`infrastructure/simple_api_client.py`——「キャッシュ参照→fetch→形の検査→エラー処理→
キャッシュ書き戻し」の骨格。

ここで見ないもの:
- 上流ごとのURL・要求パラメータ・応答の読み方 → 各クライアントのテスト
  （`test_jma_warning_client.py`・`test_wbgt_client.py`）
- ログの出力先・`/api/debug/stats`の集計・例外ラベルの作り方 → `debug_log`側。ここでは
  **`fields`へ何を書くか**だけを見るため、`log_external_call`を差し替えて受け取る
"""

import httpx
import pytest
from cachetools import TTLCache

from app.infrastructure import simple_api_client
from tests.fake_external_log import record_external_calls


def _counting_fetch(value):
    """呼ばれた回数を数えるfetch。キャッシュが効いたかは呼び出し回数でしか分からない。"""
    calls: list[int] = []

    async def fetch():
        calls.append(1)
        return value

    return fetch, calls


async def test_without_cache_calls_fetch_every_time():
    fetch, calls = _counting_fetch({"a": 1})

    assert await simple_api_client.cached_fetch("cat", fetch) == {"a": 1}
    assert await simple_api_client.cached_fetch("cat", fetch) == {"a": 1}

    assert len(calls) == 2


async def test_cache_miss_calls_fetch_and_stores_result(monkeypatch):
    recorded = record_external_calls(monkeypatch, simple_api_client)
    cache: TTLCache = TTLCache(maxsize=4, ttl=60)
    fetch, calls = _counting_fetch("v")

    assert await simple_api_client.cached_fetch("cat", fetch, cache=cache, key="k", site="x") == "v"

    assert cache["k"] == "v"
    assert len(calls) == 1
    assert recorded[0].category == "cat"
    fields = recorded[0].fields
    assert fields["site"] == "x"
    assert fields["cache"] == "miss"
    assert fields["result"] == "ok"


async def test_cache_hit_skips_fetch(monkeypatch):
    recorded = record_external_calls(monkeypatch, simple_api_client)
    cache: TTLCache = TTLCache(maxsize=4, ttl=60)
    cache["k"] = "stored"
    fetch, calls = _counting_fetch("fresh")

    assert await simple_api_client.cached_fetch("cat", fetch, cache=cache, key="k") == "stored"

    assert calls == []
    assert recorded[0].fields["cache"] == "hit"


async def test_none_from_upstream_is_cached():
    """上流の「該当なし」もキャッシュする。未取得と同じ値にすると、該当なしの問い合わせが
    TTLの間ずっと上流へ流れ続ける。"""
    cache: TTLCache = TTLCache(maxsize=4, ttl=60)
    fetch, calls = _counting_fetch(None)

    assert await simple_api_client.cached_fetch("cat", fetch, cache=cache, key="k") is None
    assert await simple_api_client.cached_fetch("cat", fetch, cache=cache, key="k") is None

    assert len(calls) == 1


async def test_expect_passes_matching_type():
    fetch, _ = _counting_fetch([1])

    assert await simple_api_client.cached_fetch("cat", fetch, expect=list) == [1]


async def test_unexpected_shape_returns_none(monkeypatch):
    recorded = record_external_calls(monkeypatch, simple_api_client)
    fetch, _ = _counting_fetch([1, 2])

    assert await simple_api_client.cached_fetch("cat", fetch, expect=dict) is None

    fields = recorded[0].fields
    assert fields["result"] == "error"
    assert fields["error_type"] == "unexpected_shape"


async def test_unexpected_shape_is_swallowed_even_when_catch_is_empty():
    """形の検査は`catch`の指定に関わらず常にNoneへ倒れる（except節の順序）。"""
    fetch, _ = _counting_fetch("s")

    assert await simple_api_client.cached_fetch("cat", fetch, expect=dict, catch=()) is None


async def test_caught_exception_returns_none_and_is_not_cached(monkeypatch):
    recorded = record_external_calls(monkeypatch, simple_api_client)
    cache: TTLCache = TTLCache(maxsize=4, ttl=60)
    calls: list[int] = []

    async def fetch():
        calls.append(1)
        raise ValueError("bad json")

    assert await simple_api_client.cached_fetch("cat", fetch, cache=cache, key="k") is None
    assert "k" not in cache
    assert await simple_api_client.cached_fetch("cat", fetch, cache=cache, key="k") is None
    assert len(calls) == 2

    fields = recorded[0].fields
    assert fields["result"] == "error"
    assert fields["error_type"] == "ValueError"
    assert "bad json" in fields["error"]


async def test_exception_outside_catch_propagates():
    async def fetch():
        raise httpx.ConnectError("boom")

    with pytest.raises(httpx.ConnectError):
        await simple_api_client.cached_fetch("cat", fetch, catch=(KeyError,))
