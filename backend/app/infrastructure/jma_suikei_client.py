"""気象庁の推計気象分布（天気）の、地点の画素の色を取る。

時刻一覧とタイルは`JmaTileClient`を通す——地図の気象庁タイルと同じキャッシュ（時刻一覧はプロセス内、タイルは
Redis）と、気象庁への秒間上限がそのまま効く。タイル1枚は経度0.7度ぶん（約60km）四方を覆い、近くの利用者で共有される。
"""

import io
import logging
from typing import cast

from PIL import Image

from app.domain.jma_suikei import (
    SUIKEI_TARGET_TIMES_PATH,
    SUIKEI_WEATHER_ELEMENT,
    suikei_pixel,
    suikei_weather_tile_path,
)
from app.domain.jma_tile_specs import read_target_times
from app.infrastructure.jma_tile_client import JmaTileClient, get_target_times
from app.infrastructure.jma_tile_redis_cache import EmptyTile

logger = logging.getLogger("ridecompass.jma_suikei_client")

_TRANSPARENT = (0, 0, 0, 0)


async def fetch_weather_color(client: JmaTileClient, latitude: float, longitude: float) -> tuple[int, int, int, int] | None:
    """最新の天気のタイルの、地点の画素の色（RGBA）。描くものが無いタイルは透明。取れなければNone。"""
    rows = await get_target_times(client, SUIKEI_TARGET_TIMES_PATH)
    frames = [] if rows is None else read_target_times("latest", rows, SUIKEI_WEATHER_ELEMENT)
    if not frames:
        logger.warning("推計気象分布（天気）の時刻一覧を読めませんでした path=%s", SUIKEI_TARGET_TIMES_PATH)
        return None
    pixel = suikei_pixel(latitude, longitude)
    raw = await client.get(suikei_weather_tile_path(frames[0], pixel))
    if raw is None:
        return None
    if isinstance(raw, EmptyTile):
        return _TRANSPARENT
    content, _content_type = raw
    try:
        with Image.open(io.BytesIO(content)) as image:
            red, green, blue, alpha = cast(tuple[int, int, int, int], image.convert("RGBA").getpixel((pixel.column, pixel.row)))
    except Exception as exc:  # noqa: BLE001 壊れた画像は「空が分からない」に倒し、応答の残りは返す
        logger.warning("推計気象分布（天気）のタイルを読めませんでした tile=%s error=%r", pixel, exc)
        return None
    return red, green, blue, alpha
