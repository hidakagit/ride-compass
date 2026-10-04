"""気象庁の降水のタイルの色を、アプリの降水の段の色へ塗り替える。

配信元は降水の強さの段ごとに決まった色で塗ったパレット形式のPNGを配り、段の区切りはアプリの降水の段
（`domain/weather_display.py: PRECIPITATION_COLOR_STOPS`）と同じなので、パレットの色を1対1で替えれば、地図の色と
凡例（同じ段から組み立てる）が一致する。画素は書き換えずパレットだけを替え、パレット形式のまま配る。
"""

import io

from PIL import Image, ImageColor

from app.domain.jma_tile_specs import jma_tile_spec, read_jma_tile_path
from app.domain.weather_display import JMA_PRECIPITATION_TILE_COLORS, PRECIPITATION_COLOR_STOPS
from app.infrastructure.cache_identity import shape_digest
from app.infrastructure.debug_log import log_throttled_warning

_PRECIPITATION_COLORS: dict[tuple[int, ...], tuple[int, ...]] = {
    ImageColor.getrgb(jma): ImageColor.getrgb(stop.color)
    for jma, stop in zip(JMA_PRECIPITATION_TILE_COLORS, PRECIPITATION_COLOR_STOPS, strict=True)
}

#: 塗り替えの版。タイル本体のキャッシュの鍵に入れ、色の対応を変えたら前の色で保存したタイルを読まない。
RECOLOR_VERSION = shape_digest(sorted(_PRECIPITATION_COLORS.items()))


def recolored(path: str, content: bytes) -> bytes:
    """宣言が降水の段の色を持つ要素のタイルなら、色を塗り替えたPNGを返す。それ以外はそのまま返す。

    パレット形式でない画像（配信元が空のタイルに返すRGBA）は塗る画素を持たないので、そのまま返す。
    降水の段に無い色の画素は塗り替えずに残し、WARNINGを出す——配信元が配色を変えた印。
    読めない画像もWARNINGを出してそのまま返す——プリウォームは1枚の例外で1周の取得を止める。"""
    tile = read_jma_tile_path(path)
    if tile is None or not jma_tile_spec(tile.element_id).precipitation_colors:
        return content
    try:
        return _recolor_palette(path, content)
    except Exception as exc:  # noqa: BLE001 壊れた画像・未知の形式で取得そのものを落とさない
        log_throttled_warning(
            "jma:tile-recolor", "気象庁の降水のタイルを塗り替えられませんでした path=%s error=%r", path, exc
        )
        return content


def _recolor_palette(path: str, content: bytes) -> bytes:
    with Image.open(io.BytesIO(content)) as image:
        if image.mode != "P":
            return content
        unknown = {
            rgba[:3]
            for _count, rgba in image.convert("RGBA").getcolors(maxcolors=256) or []
            if rgba[3] > 0 and rgba[:3] not in _PRECIPITATION_COLORS
        }
        if unknown:
            log_throttled_warning(
                "jma:tile-recolor",
                "気象庁の降水のタイルに、降水の段に無い色があります path=%s rgb=%s"
                "（domain/weather_display.py: JMA_PRECIPITATION_TILE_COLORS）",
                path,
                sorted(unknown),
            )
        palette = image.getpalette() or []
        entries = [tuple(palette[i : i + 3]) for i in range(0, len(palette), 3)]
        image.putpalette([value for entry in entries for value in _PRECIPITATION_COLORS.get(entry, entry)])
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    return buffer.getvalue()
