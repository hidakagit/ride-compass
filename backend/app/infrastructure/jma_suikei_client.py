"""気象庁の推計気象分布（天気）の、地点の天気の区分を取る。

推計気象分布（天気）は、ひまわりの雲の観測・解析雨量・推計気象分布（気温）から約1km四方ごとに天気を決めた
実況で、配信元は天気の区分ごとに決まった色で塗ったタイルを配る。区分と色は公式の画面
（`bosai/suikei/`）の設定ファイル`table/suikei.properties__<hash>.xml`の要素`wthr`と、その凡例
`images/legend_jp_normal_wm.svg`から写す。

地図に重ねる気象庁タイル（`domain/jma_tile_specs.py: JMA_ELEMENTS`）とは別に持つ——このタイルは512画素で、
パスのズームが`z`のとき`x`・`y`は1辺`2**(z-1)`枚の並びで数える（256画素の`JMA_ELEMENTS`のタイルとは
同じズームでも座標が合わない）。

時刻一覧とタイルは`JmaTileClient`を通す——地図の気象庁タイルと同じキャッシュ（時刻一覧はプロセス内、タイルは
Redis）と、気象庁への秒間上限がそのまま効く。タイル1枚は経度0.7度ぶん（約60km）四方を覆い、近くの利用者で共有される。
"""

import io
import logging
from typing import NamedTuple, cast

from PIL import Image

from app.domain.jma_tile_specs import JmaFrame, read_target_times
from app.domain.region import tile_position
from app.domain.weather import SuikeiWeather
from app.infrastructure.jma_tile_client import JmaTileClient, get_target_times
from app.infrastructure.jma_tile_redis_cache import EmptyTile

logger = logging.getLogger("ridecompass.jma_suikei_client")

#: 時刻一覧に載る天気の要素id。
_WEATHER_ELEMENT = "wthr"
_ROOT = "bosai/jmatile/data/suikeikishou"
_TARGET_TIMES_PATH = f"{_ROOT}/targetTimes.json"
# 設定ファイルの`maxNativeZoom`（画像が実在する最大ズーム）。`zoomUse="even"`とも合う。
_ZOOM = 10
_TILE_SIZE = 512

_WEATHER_BY_COLOR: dict[tuple[int, int, int], SuikeiWeather] = {
    (255, 170, 0): "clear",
    (170, 170, 170): "cloudy",
    (0, 65, 255): "rain",
    (160, 210, 255): "rain_or_snow",
    (242, 242, 255): "snow",
}


class _Pixel(NamedTuple):
    """地点を含むタイルと、その中の画素。"""

    x: int
    y: int
    column: int
    row: int


def _pixel(latitude: float, longitude: float) -> _Pixel:
    """地点を含む天気のタイルと画素（Webメルカトル）。"""
    tile_x, tile_y = tile_position(longitude, latitude, _ZOOM - 1)
    x = int(tile_x * _TILE_SIZE)
    y = int(tile_y * _TILE_SIZE)
    return _Pixel(x // _TILE_SIZE, y // _TILE_SIZE, x % _TILE_SIZE, y % _TILE_SIZE)


def _tile_path(frame: JmaFrame, pixel: _Pixel) -> str:
    """天気のタイルの、配信元のパス。"""
    return (
        f"{_ROOT}/{frame.basetime}/{frame.member}/{frame.validtime}/surf/{_WEATHER_ELEMENT}"
        f"/{_ZOOM}/{pixel.x}/{pixel.y}.png"
    )


def _weather_from_color(red: int, green: int, blue: int, alpha: int) -> SuikeiWeather | None:
    """画素の色を天気の区分へ。透明（推計の範囲の外・欠測）はNone。

    凡例に無い色もNoneにしてWARNINGを出す——配信元が配色を変えた印で、区分を取り違えて出すより出さない。"""
    if alpha == 0:
        return None
    weather = _WEATHER_BY_COLOR.get((red, green, blue))
    if weather is None:
        logger.warning(
            "推計気象分布（天気）の凡例に無い色です rgb=(%d, %d, %d)（infrastructure/jma_suikei_client.py: _WEATHER_BY_COLOR）",
            red, green, blue,
        )
    return weather


async def fetch_weather(client: JmaTileClient, latitude: float, longitude: float) -> SuikeiWeather | None:
    """最新の天気のタイルの、地点の天気の区分。取れない・透明・凡例に無い色ならNone。"""
    rows = await get_target_times(client, _TARGET_TIMES_PATH)
    frames = [] if rows is None else read_target_times("latest", rows, _WEATHER_ELEMENT)
    if not frames:
        logger.warning("推計気象分布（天気）の時刻一覧を読めませんでした path=%s", _TARGET_TIMES_PATH)
        return None
    pixel = _pixel(latitude, longitude)
    raw = await client.get(_tile_path(frames[0], pixel))
    if raw is None or isinstance(raw, EmptyTile):
        return None
    content, _content_type = raw
    try:
        with Image.open(io.BytesIO(content)) as image:
            red, green, blue, alpha = cast(tuple[int, int, int, int], image.convert("RGBA").getpixel((pixel.column, pixel.row)))
    except Exception as exc:  # noqa: BLE001 壊れた画像は「空が分からない」に倒し、応答の残りは返す
        logger.warning("推計気象分布（天気）のタイルを読めませんでした tile=%s error=%r", pixel, exc)
        return None
    return _weather_from_color(red, green, blue, alpha)
