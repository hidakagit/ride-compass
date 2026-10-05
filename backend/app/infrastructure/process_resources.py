"""プロセスで持ち回る外側との接続と資源を、プロセスの終わりにまとめて閉じる。

main.pyのlifespanシャットダウン段から呼ぶ。どれも閉じたあとの次の取得で作り直す。
"""

from app.infrastructure import landcover_raster, tile_cache, tile_persistent_cache
from app.infrastructure.database import dispose_engines
from app.infrastructure.http_client import close_all_http_clients
from app.infrastructure.redis_client import close_redis_clients


async def close_process_resources() -> None:
    await close_all_http_clients()
    await close_redis_clients()
    await dispose_engines()
    landcover_raster.close_sources()
    tile_cache.close()
    tile_persistent_cache.close()
