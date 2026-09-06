"""配信元が実データを持たないズームのJMAタイルを、1段上のタイルから補間する。

気象庁のタイルは要素ごとに`zoomUse`（使用するズームの偶奇）を持ち、合わないズームでは
空タイルが返る（`domain/jma_tile_specs.py`参照）。MapLibreのソース設定は連続したズーム
区間しか表現できず「偶数だけ使う」を伝えられないため、要求されたズームのタイルが存在
しない場合はこの層が親タイルから該当象限を切り出して返す。

**最近傍で拡大する**: キキクル・ナウキャストはいずれも危険度・強度を離散的な色で塗り
分けた画像で、凡例の色と1対1に対応する。バイリニア等で滑らかに拡大すると境界に中間色が
生まれ、凡例のどの段階でもない色が地図に出る。
"""

import io
import re

from PIL import Image

#: `bosai/jmatile/data/<group>/<basetime>/<member>/<validtime>/surf/<element>/<z>/<x>/<y>.<ext>`
#: からズーム・タイル座標・要素idを取り出す。クエリ文字列付き（liden系のGeoJSON）は
#: タイルではないため一致しない。
_TILE_PATH_PATTERN = re.compile(
    r"^(?P<head>.+/surf/(?P<element>[a-z0-9_]+))/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)\.(?P<ext>png|pbf)$"
)


class TileCoords:
    """タイルパスから読み取った座標と、親タイルのパスを組み立てる手段。"""

    def __init__(self, head: str, element: str, z: int, x: int, y: int, ext: str):
        self.head = head
        self.element = element
        self.z = z
        self.x = x
        self.y = y
        self.ext = ext

    def parent_path(self) -> str:
        """1段上（z-1）のタイルのパス。"""
        return f"{self.head}/{self.z - 1}/{self.x // 2}/{self.y // 2}.{self.ext}"

    @property
    def quadrant(self) -> tuple[int, int]:
        """親タイルのどの象限に対応するか（左上を(0,0)とする）。"""
        return self.x % 2, self.y % 2


def parse_tile_path(path: str) -> TileCoords | None:
    """タイルパスを解析する。タイル以外（targetTimes.json・GeoJSON等）はNone。"""
    match = _TILE_PATH_PATTERN.match(path)
    if match is None:
        return None
    return TileCoords(
        head=match.group("head"),
        element=match.group("element"),
        z=int(match.group("z")),
        x=int(match.group("x")),
        y=int(match.group("y")),
        ext=match.group("ext"),
    )


def crop_and_upscale(parent_png: bytes, quadrant: tuple[int, int]) -> bytes:
    """親タイルの指定象限を切り出し、元のタイルサイズへ最近傍で拡大する。"""
    with Image.open(io.BytesIO(parent_png)) as source:
        # パレット形式（実データを持つタイル）とRGBA（空タイル）が混在するため揃える。
        image = source.convert("RGBA")
        width, height = image.size
        half_width, half_height = width // 2, height // 2
        left = quadrant[0] * half_width
        top = quadrant[1] * half_height
        cropped = image.crop((left, top, left + half_width, top + half_height))
        upscaled = cropped.resize((width, height), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    upscaled.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
