"""simple_api_client.py（改善計画T488: TTLCacheのみのシンプルな外部APIクライアントが
共有する「キャッシュ参照→fetch→エラー処理→キャッシュ書き戻し」の定型文）のテスト。

jma_amedas_client.py・jma_warning_client.py・wbgt_client.py・flood_client.py側の
既存テスト（各クライアント固有の振る舞い）は無変更のまま全件greenであることを別途
確認済み。ここではcached_fetch自体の契約（キャッシュヒット/ミス・エラー分類・
fields記録内容）を直接検証する。
"""

import httpx
import pytest
from cachetools import TTLCache

from app.infrastructure import debug_log
from app.infrastructure.simple_api_client import UnexpectedShapeError, cached_fetch


@pytest.fixture(autouse=True)
def _clean_stats():
    debug_log.reset_stats()
    yield
    debug_log.reset_stats()


async def test_cache_hit_does_not_call_fetch_and_records_cache_hit():
    cache: TTLCache = TTLCache(maxsize=1, ttl=60)
    cache["key"] = "cached-value"
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        return "fresh-value"

    result = await cached_fetch(cache, "key", "test:cache-hit", fetch)

    assert result == "cached-value"
    assert calls == 0
    stats = debug_log.get_stats()["external"]["test:cache-hit"]
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 0
    assert stats["errors"] == 0


async def test_cache_miss_calls_fetch_and_writes_back_to_cache():
    cache: TTLCache = TTLCache(maxsize=1, ttl=60)

    async def fetch():
        return "fresh-value"

    result = await cached_fetch(cache, "key", "test:cache-miss", fetch)

    assert result == "fresh-value"
    assert cache["key"] == "fresh-value"
    stats = debug_log.get_stats()["external"]["test:cache-miss"]
    assert stats["cache_misses"] == 1
    assert stats["errors"] == 0


async def test_default_catch_returns_none_on_http_error_and_does_not_populate_cache():
    cache: TTLCache = TTLCache(maxsize=1, ttl=60)

    async def fetch():
        raise httpx.RequestError("boom")

    result = await cached_fetch(cache, "key", "test:http-error", fetch)

    assert result is None
    assert "key" not in cache
    stats = debug_log.get_stats()["external"]["test:http-error"]
    assert stats["errors"] == 1
    assert stats["error_types"]["RequestError"] == 1


async def test_default_catch_does_not_swallow_attribute_error():
    """AttributeErrorは既定のcatchタプル(httpx.HTTPError, ValueError)に含まれないため、
    呼び出し元まで伝播する（fetch_municipality_codeのような特定の呼び出しだけがcatchへ
    AttributeErrorを明示的に追加する、というjma_warning_client.pyの既存挙動を再現）。"""
    cache: TTLCache = TTLCache(maxsize=1, ttl=60)

    async def fetch():
        raise AttributeError("boom")

    with pytest.raises(AttributeError):
        await cached_fetch(cache, "key", "test:attribute-error", fetch)


async def test_custom_catch_tuple_can_widen_caught_exceptions():
    cache: TTLCache = TTLCache(maxsize=1, ttl=60)

    async def fetch():
        raise AttributeError("boom")

    result = await cached_fetch(cache, "key", "test:widened-catch", fetch, catch=(AttributeError,))

    assert result is None
    stats = debug_log.get_stats()["external"]["test:widened-catch"]
    assert stats["error_types"]["AttributeError"] == 1


async def test_unexpected_shape_error_is_recorded_with_fixed_error_type():
    cache: TTLCache = TTLCache(maxsize=1, ttl=60)

    async def fetch():
        raise UnexpectedShapeError("not a list")

    result = await cached_fetch(cache, "key", "test:unexpected-shape", fetch)

    assert result is None
    assert "key" not in cache
    stats = debug_log.get_stats()["external"]["test:unexpected-shape"]
    assert stats["errors"] == 1
    # UnexpectedShapeErrorはValueErrorのサブクラスだが、常に固定文字列"unexpected_shape"
    # として記録される（error_type_label由来のクラス名"UnexpectedShapeError"にはならない）。
    assert stats["error_types"]["unexpected_shape"] == 1


async def test_log_fields_kwargs_are_forwarded_to_log_external_call():
    """jma_warning_client.pyのoffice_code=引数のような追加fieldsが、そのまま
    log_external_callへ渡ることを確認する（ログ本文への反映、統計自体には現れないため
    例外なく完走することのみ確認）。"""
    cache: TTLCache = TTLCache(maxsize=1, ttl=60)

    async def fetch():
        return "value"

    result = await cached_fetch(cache, "key", "test:log-fields", fetch, office_code="130000")

    assert result == "value"
