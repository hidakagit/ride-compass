"""シンプルな外部APIクライアント（TTLCacheのみ、再試行を持たない）が共有する
「キャッシュ参照→fetch→形の検査→エラー処理→キャッシュ書き戻し」の骨格。

TTLCache以外のキャッシュへ持つクライアント（`jma_tile_client.py`・`basemap_client.py`等）は
形が違うため、この骨格には乗らない。
"""

from collections.abc import Awaitable, Callable, Hashable
from typing import TypeVar

import httpx
from cachetools import TTLCache

from app.infrastructure.debug_log import error_type_label, log_external_call

T = TypeVar("T")

#: 「まだ引いていない」を表す番兵。`None`は上流が返す正常な答え（該当なし）であり、
#: 未取得と同じ値にすると該当なしがTTLの間ずっとキャッシュされず、毎回上流を叩く。
_NOT_CACHED = object()


class UnexpectedShapeError(ValueError):
    """fetchが返した内容の形が想定と異なる場合に送出する。

    ValueErrorのサブクラスだが、`catch`タプルに含まれるかどうかに関わらず常に
    `error_type="unexpected_shape"`として記録される（except節の順序で先に一致するため）。
    """


async def cached_fetch(
    category: str,
    fetch: Callable[[], Awaitable[T]],
    *,
    cache: TTLCache | None = None,
    key: Hashable = None,
    expect: type | tuple[type, ...] | None = None,
    # 何をNoneへ倒すかは応答の形ごとに違うため、呼び出し側が指定できるようにする。
    catch: tuple[type[BaseException], ...] = (httpx.HTTPError, ValueError),
    **log_fields: object,
) -> T | None:
    """`fetch()`を呼び、`catch`の例外と想定外の形をNoneへ倒して記録する。

    `cache`を渡すと`key`で引き、ミスしたときだけ`fetch()`を呼ぶ。**上流が「該当なし」として
    返した`None`もキャッシュする**——未取得と区別しないと、該当なしの問い合わせがTTLの間
    ずっと上流へ流れ続ける。`cache`を渡さない場合は毎回`fetch()`を呼ぶ。

    `expect`を渡すと、`fetch()`の戻り値がその型でなければ`UnexpectedShapeError`として扱う。
    形の検査を呼び出し側が各自で書くと、同じ判定が上流の数だけ並ぶ。
    """
    with log_external_call(category, **log_fields) as fields:
        if cache is not None:
            cached = cache.get(key, _NOT_CACHED)
            if cached is not _NOT_CACHED:
                fields["cache"] = "hit"
                return cached
            fields["cache"] = "miss"
        try:
            data = await fetch()
            if expect is not None and not isinstance(data, expect):
                raise UnexpectedShapeError(f"{category}: expected {expect}, got {type(data).__name__}")
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
        if cache is not None:
            cache[key] = data
        return data
