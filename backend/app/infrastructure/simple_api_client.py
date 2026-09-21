"""シンプルな外部APIクライアント（TTLCacheのみ、再試行を持たない）が共有する
「キャッシュ参照→fetch→エラー処理→キャッシュ書き戻し」の骨格。

TTLCache以外のキャッシュへ持つクライアント（`jma_tile_client.py`・`basemap_client.py`等）は
形が違うため、この骨格には乗らない。
"""

from collections.abc import Awaitable, Callable, Hashable
from typing import TypeVar

import httpx
from cachetools import TTLCache

from app.infrastructure.debug_log import error_type_label, log_external_call

T = TypeVar("T")


class UnexpectedShapeError(ValueError):
    """fetchが返した内容の形が想定と異なる場合に送出する。

    ValueErrorのサブクラスだが、`catch`タプルに含まれるかどうかに関わらず常に
    `error_type="unexpected_shape"`として記録される（except節の順序で先に一致するため）。
    """


async def cached_fetch(
    cache: TTLCache,
    key: Hashable,
    category: str,
    fetch: Callable[[], Awaitable[T]],
    *,
    # 何をNoneへ倒すかは応答の形ごとに違う（外部JSONの想定外の形をAttributeErrorで
    # 踏む経路もある）ため、呼び出し側が指定できるようにする。
    catch: tuple[type[BaseException], ...] = (httpx.HTTPError, ValueError),
    **log_fields: object,
) -> T | None:
    """TTLCacheを引き、ミスした場合のみ`fetch()`を呼ぶ。

    `fetch`が送出した`catch`の例外はNoneへ変換し、`log_external_call`のfieldsへ記録する。
    """
    with log_external_call(category, **log_fields) as fields:
        cached = cache.get(key)
        if cached is not None:
            fields["cache"] = "hit"
            return cached
        fields["cache"] = "miss"
        try:
            data = await fetch()
        except UnexpectedShapeError:
            fields["result"] = "error"
            fields["error_type"] = "unexpected_shape"
            return None
        except catch as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        fields["result"] = "ok"
        cache[key] = data
        return data
