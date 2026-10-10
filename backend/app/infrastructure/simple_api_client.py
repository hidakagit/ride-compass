"""シンプルな外部APIクライアント（TTLCacheのみ、再試行を持たない）が共有する
「キャッシュ参照→fetch→エラー処理→キャッシュ書き戻し」の骨格。

TTLCache以外のキャッシュへ持つクライアント（`jma_tile_client.py`・`basemap_client.py`等）は
形が違うため、この骨格には乗らない。
"""

from collections.abc import Awaitable, Callable, Hashable
from typing import TypeVar

import httpx
from cachetools import TTLCache

from app.infrastructure.debug_log import log_external_call, mark_failed

T = TypeVar("T")
J = TypeVar("J", dict, list)

#: 「まだ引いていない」を表す番兵。`None`は上流が返す正常な答え（該当なし）であり、
#: 未取得と同じ値にすると該当なしがTTLの間ずっとキャッシュされず、毎回上流を叩く。
_NOT_CACHED = object()


class UnexpectedShapeError(ValueError):
    """fetchが返した内容の形が想定と異なる場合に送出する。

    `catch`の指定に関わらず、常にNoneへ倒して失敗として記録する。
    """


async def get_json(
    client: httpx.AsyncClient, url: str, expected: type[J], shape_error_prefix: str, *, timeout: httpx.Timeout
) -> J:
    """`url`をGETしてJSONを読む。`expected`の型でなければ`UnexpectedShapeError`
    （文は`<shape_error_prefix> <届いた型の名前>`）。"""
    response = await client.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, expected):
        raise UnexpectedShapeError(f"{shape_error_prefix} {type(payload).__name__}")
    return payload


async def cached_fetch(
    category: str,
    fetch: Callable[[], Awaitable[T]],
    *,
    cache: TTLCache | None = None,
    key: Hashable = None,
    # 何をNoneへ倒すかは応答の形ごとに違うため、呼び出し側が指定できるようにする。
    catch: tuple[type[BaseException], ...] = (httpx.HTTPError, ValueError),
    **log_fields: object,
) -> T | None:
    """`fetch()`を呼び、`catch`の例外と`UnexpectedShapeError`をNoneへ倒して記録する。

    `cache`を渡すと`key`で引き、ミスしたときだけ`fetch()`を呼ぶ。**上流が「該当なし」として
    返した`None`もキャッシュする**——未取得と区別しないと、該当なしの問い合わせがTTLの間
    ずっと上流へ流れ続ける。`cache`を渡さない場合は毎回`fetch()`を呼ぶ。
    """
    caught: tuple[type[BaseException], ...] = (UnexpectedShapeError, *catch)
    with log_external_call(category, **log_fields) as fields:
        if cache is not None:
            cached = cache.get(key, _NOT_CACHED)
            if cached is not _NOT_CACHED:
                fields["cache"] = "hit"
                return cached
            fields["cache"] = "miss"
        try:
            data = await fetch()
        except caught as exc:
            mark_failed(fields, exc)
            return None
        fields["result"] = "ok"
        if cache is not None:
            cache[key] = data
        return data
