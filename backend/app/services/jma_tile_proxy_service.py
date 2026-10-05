"""気象庁タイルの中継の段取り（キャッシュ → 親タイルからの補間 → 上流）。"""

from collections.abc import Callable

from app.infrastructure.jma_tile_client import EmptyTile, JmaTileClient
from app.services.jma_tile_interpolation_service import interpolated_tile


async def proxied_tile(
    jma_tile_client: JmaTileClient, path: str, before_upstream: Callable[[], None]
) -> tuple[bytes, str] | EmptyTile | None:
    """`path`の内容とContent-Type。

    キャッシュに無いときだけ、補間・上流へ出る前に`before_upstream`を1回呼ぶ（呼び出し側の歯止め。
    送出すればそこで止まる）。配信元が実データを持たないズームは親タイルから補間し、元のパスの鍵で
    キャッシュへ書き戻す。描くものが無いと確認済みなら`EmptyTile`、上流の障害はNone。上流に無い
    （`JmaTileNotFoundError`）はそのまま送出する。
    """
    cached = await jma_tile_client.get_cached(path)
    if cached is not None:
        return cached
    before_upstream()
    interpolated = await interpolated_tile(jma_tile_client, path)
    if interpolated is not None:
        content, content_type = interpolated
        await jma_tile_client.store(path, content, content_type)
        return interpolated
    return await jma_tile_client.fetch(path)
