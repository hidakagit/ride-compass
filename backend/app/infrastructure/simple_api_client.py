"""シンプルな外部APIクライアント（TTLCacheのみ、tenacity再試行を持たない）が共有する
「キャッシュ参照→fetch→エラー処理→キャッシュ書き戻し」の定型文。

`jma_amedas_client.py`・`jma_warning_client.py`・`wbgt_client.py`・`flood_client.py`に
一字一句同じ形でほぼ複製されていた8〜10行の骨格をここへ集約する。`weather_client.py`
（tenacity再試行・2段キャッシュを持つ特殊経路）・`jma_tile_client.py`/`elevation_client.py`/
`basemap_client.py`（TTLCache以外のキャッシュバックエンドを使うため定型文の形が異なる）は
対象外のまま各自の実装を維持する。
"""

from collections.abc import Awaitable, Callable, Hashable
from typing import TypeVar

import httpx
from cachetools import TTLCache

from app.infrastructure.debug_log import error_type_label, log_external_call

T = TypeVar("T")


class UnexpectedShapeError(ValueError):
    """fetchが返した内容の形が想定と異なる場合に送出する。cached_fetchはこれを
    error_type="unexpected_shape"（既存コードのリテラル文字列と同じ）として記録する。
    ValueErrorのサブクラスだが、catchタプルに含まれるかどうかに関わらず常にこの専用の
    error_typeへ変換される（except節の順序で先に一致するため）。"""


async def cached_fetch(
    cache: TTLCache,
    key: Hashable,
    category: str,
    fetch: Callable[[], Awaitable[T]],
    *,
    # 呼び出し元ごとに元々の except節が異なっていた（例: 度数からの逆ジオコーディングだけ
    # AttributeErrorも捕捉、latest_observation_timeはhttpx.HTTPErrorのみ）ため、既存の
    # 挙動を変えないよう呼び出し側が指定できるようにする。
    catch: tuple[type[BaseException], ...] = (httpx.HTTPError, ValueError),
    **log_fields: object,
) -> T | None:
    """TTLCacheを引き、ミスした場合のみ`fetch()`を呼ぶ。`fetch`が送出した例外は
    Noneへ変換し`log_external_call`のfieldsへ記録する（各クライアントの既存の
    fields記録内容・戻り値の型を変えない）。"""
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
