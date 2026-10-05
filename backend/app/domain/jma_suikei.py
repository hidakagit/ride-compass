"""気象庁の推計気象分布（天気）を地点の空（晴れ・くもり）として読むための、配信の形と色の読み方。

推計気象分布（天気）は、ひまわりの雲の観測・解析雨量・推計気象分布（気温）から約1km四方ごとに天気を決めた
実況で、配信元は天気の区分ごとに決まった色で塗ったタイルを配る。区分と色は公式の画面
（`bosai/suikei/`）の設定ファイル`table/suikei.properties__<hash>.xml`の要素`wthr`と、その凡例
`images/legend_jp_normal_wm.svg`から写す。

地図に重ねる気象庁タイル（`jma_tile_specs.py: JMA_ELEMENTS`）とは別に持つ——このタイルは512画素で、
パスのズームが`z`のとき`x`・`y`は1辺`2**(z-1)`枚の並びで数える（256画素の`JMA_ELEMENTS`のタイルとは
同じズームでも座標が合わない）。
"""

import logging
from typing import Literal, NamedTuple

from app.domain.jma_tile_specs import JmaFrame
from app.domain.region import tile_position

logger = logging.getLogger("ridecompass.jma_suikei")

#: 時刻一覧に載る天気の要素id。
SUIKEI_WEATHER_ELEMENT = "wthr"
_ROOT = "bosai/jmatile/data/suikeikishou"
SUIKEI_TARGET_TIMES_PATH = f"{_ROOT}/targetTimes.json"
# 設定ファイルの`maxNativeZoom`（画像が実在する最大ズーム）。`zoomUse="even"`とも合う。
_ZOOM = 10
_TILE_SIZE = 512

Sky = Literal["clear", "cloudy"]

# 雨・雪の区分も空はくもりに数える。降っているかは観測所の実測が決め（`domain/weather.py: derive_observed_weather_code`）、
# ここから読むのは降っていないときの空だけなので、観測所で降っていないのに雨と出た所はくもりとして出す。
_SKY_BY_COLOR: dict[tuple[int, int, int], Sky] = {
    (255, 170, 0): "clear",  # 晴れ
    (170, 170, 170): "cloudy",  # くもり
    (0, 65, 255): "cloudy",  # 雨
    (160, 210, 255): "cloudy",  # 雨または雪
    (242, 242, 255): "cloudy",  # 雪
}


class SuikeiPixel(NamedTuple):
    """地点を含むタイルと、その中の画素。"""

    x: int
    y: int
    column: int
    row: int


def suikei_pixel(latitude: float, longitude: float) -> SuikeiPixel:
    """地点を含む天気のタイルと画素（Webメルカトル）。"""
    tile_x, tile_y = tile_position(longitude, latitude, _ZOOM - 1)
    x = int(tile_x * _TILE_SIZE)
    y = int(tile_y * _TILE_SIZE)
    return SuikeiPixel(x // _TILE_SIZE, y // _TILE_SIZE, x % _TILE_SIZE, y % _TILE_SIZE)


def suikei_weather_tile_path(frame: JmaFrame, pixel: SuikeiPixel) -> str:
    """天気のタイルの、配信元のパス。"""
    return (
        f"{_ROOT}/{frame.basetime}/{frame.member}/{frame.validtime}/surf/{SUIKEI_WEATHER_ELEMENT}"
        f"/{_ZOOM}/{pixel.x}/{pixel.y}.png"
    )


def sky_from_color(red: int, green: int, blue: int, alpha: int) -> Sky | None:
    """画素の色を空の区分へ。透明（推計の範囲の外・欠測）はNone。

    凡例に無い色もNoneにしてWARNINGを出す——配信元が配色を変えた印で、晴れ・くもりを取り違えて出すより出さない。"""
    if alpha == 0:
        return None
    sky = _SKY_BY_COLOR.get((red, green, blue))
    if sky is None:
        logger.warning(
            "推計気象分布（天気）の凡例に無い色です rgb=(%d, %d, %d)（domain/jma_suikei.py: _SKY_BY_COLOR）",
            red, green, blue,
        )
    return sky
