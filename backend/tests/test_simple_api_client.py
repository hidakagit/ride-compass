"""`infrastructure/simple_api_client.py`——TTLCacheを1枚はさんで外部APIを1回だけ引く骨格。

ここで見ないもの:

- URLの組み立て・応答のパース → `test_flood_client.py`等、この骨格に乗る各クライアント
- 統計の集計とWARNINGの抑制そのもの → `test_debug_log.py`
- ディスク・Redisを挟む取り寄せ → `test_gsi_tile_client.py`・`test_jma_tile_client.py`

**上流は呼ばない。** `fetch`は呼び出し側が渡す関数なので、値を返す／例外を送出する関数を
直接与える。記録された結果は`/api/debug/stats`が読む集計（`debug_log.get_stats`）を通して
確かめる——呼び出し元が読むのはそこで、`fields`そのものではない。
"""

import httpx
import pytest
from cachetools import TTLCache

from app.infrastructure import debug_log
from app.infrastructure.simple_api_client import UnexpectedShapeError, cached_fetch

CATEGORY_A = "category_a"
KEY_A = "key_a"
VALUE_A = {"value": "a"}
VALUE_B = {"value": "b"}


@pytest.fixture(autouse=True)
def _fresh_stats():
    debug_log.reset_stats()
    yield
    debug_log.reset_stats()


class _Fetch:
    """呼ばれるたびに、与えられた結果を順に出す`fetch`（例外は送出する）。

    最後の結果は以後も出し続ける。キャッシュが効いているかは`calls`で見る。
    """

    def __init__(self, *outcomes: object):
        self._outcomes = list(outcomes) or [None]
        self.calls = 0

    async def __call__(self) -> object:
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _cache() -> TTLCache:
    return TTLCache(maxsize=8, ttl=60)


def _stats() -> dict:
    return debug_log.get_stats()["external"][CATEGORY_A]


class TestGoingUpstream:
    async def test_a_first_look_asks_upstream_and_returns_what_came_back(self):
        fetch = _Fetch(VALUE_A)

        result = await cached_fetch(CATEGORY_A, fetch, cache=_cache(), key=KEY_A)

        assert result == VALUE_A
        assert fetch.calls == 1
        assert _stats()["cache_misses"] == 1

    async def test_a_second_look_is_answered_without_asking_upstream(self):
        """毎回引きに行くと、レート制限のある配信元から締め出される。"""
        cache = _cache()
        fetch = _Fetch(VALUE_A, VALUE_B)

        first = await cached_fetch(CATEGORY_A, fetch, cache=cache, key=KEY_A)
        second = await cached_fetch(CATEGORY_A, fetch, cache=cache, key=KEY_A)

        assert (first, second) == (VALUE_A, VALUE_A)
        assert fetch.calls == 1
        assert _stats()["cache_hits"] == 1

    async def test_an_answer_of_nothing_is_remembered_like_any_other(self):
        """該当なしを覚えないと、市区町村の定まらない出発地点が毎リクエスト上流を叩く。"""
        cache = _cache()
        fetch = _Fetch(None)

        await cached_fetch(CATEGORY_A, fetch, cache=cache, key=KEY_A)
        await cached_fetch(CATEGORY_A, fetch, cache=cache, key=KEY_A)

        assert fetch.calls == 1


class TestWhenTheUpstreamFails:
    async def test_a_failure_the_caller_listed_becomes_no_value(self):
        """例外をそのまま通すと、天候のような補助的なデータ1本の不調でリクエストが500になる。"""
        result = await cached_fetch(
            CATEGORY_A, _Fetch(httpx.RequestError("boom")), cache=_cache(), key=KEY_A
        )

        assert result is None
        assert _stats()["errors"] == 1

    async def test_a_failure_is_not_remembered(self):
        """失敗をキャッシュすると、上流が復旧してもTTLの間は壊れたままになる。"""
        cache = _cache()
        fetch = _Fetch(httpx.RequestError("boom"), VALUE_A)

        failed = await cached_fetch(CATEGORY_A, fetch, cache=cache, key=KEY_A)
        recovered = await cached_fetch(CATEGORY_A, fetch, cache=cache, key=KEY_A)

        assert (failed, recovered) == (None, VALUE_A)

    async def test_a_failure_the_caller_did_not_list_reaches_the_caller(self):
        """何でもNoneへ倒すと、呼び出し側が「データが無い」と「壊れている」を区別できない。"""
        with pytest.raises(RuntimeError):
            await cached_fetch(
                CATEGORY_A, _Fetch(RuntimeError("boom")), cache=_cache(), key=KEY_A, catch=(KeyError,)
            )

    async def test_the_details_the_caller_passed_in_are_in_the_warning(self, caplog):
        """どの地点・どのパスの取得が落ちたのかが無いと、運用側は再現できない。"""
        await cached_fetch(
            CATEGORY_A, _Fetch(httpx.RequestError("boom")), cache=_cache(), key=KEY_A, point="point_a"
        )

        assert "point_a" in caplog.text


class TestAnAnswerOfTheWrongShape:
    async def test_it_becomes_no_value_even_when_the_caller_did_not_list_it(self):
        """形の検査は`fetch`の中で行うため、`catch`を絞った呼び出し側でも握る先が要る。"""
        result = await cached_fetch(
            CATEGORY_A,
            _Fetch(UnexpectedShapeError("shape")),
            cache=_cache(),
            key=KEY_A,
            catch=(httpx.HTTPError,),
        )

        assert result is None

    async def test_it_is_counted_under_a_label_of_its_own(self):
        """通信の失敗と同じ札にすると、上流の形が変わったことに集計だけでは気づけない。"""
        await cached_fetch(
            CATEGORY_A, _Fetch(UnexpectedShapeError("shape")), cache=_cache(), key=KEY_A
        )

        assert _stats()["error_types"] == {"unexpected_shape": 1}
