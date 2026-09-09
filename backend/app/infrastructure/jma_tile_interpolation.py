"""配信元が実データを持たないズームのJMAタイルを、1段上のタイルから補間する。

気象庁のタイルは要素ごとに`zoomUse`（使用するズームの偶奇）を持ち、合わないズームでは
空タイルが返る（`domain/jma_tile_specs.py`参照）。MapLibreのソース設定は連続したズーム
区間しか表現できず「偶数だけ使う」を伝えられないため、要求されたズームのタイルが存在
しない場合はこの層が親タイルから該当象限を切り出して返す。

**ラスタは最近傍で拡大する**: キキクル・ナウキャストはいずれも危険度・強度を離散的な色で
塗り分けた画像で、凡例の色と1対1に対応する。バイリニア等で滑らかに拡大すると境界に中間色が
生まれ、凡例のどの段階でもない色が地図に出る。

**ベクタ（洪水キキクル）は座標を変換して詰め直す**: 画像と違い拡大という操作が無いため、
親タイルの該当象限を切り出し、タイル内座標を2倍にして同じextentのタイルとして
エンコードし直す。属性はそのまま引き継ぐ（危険度levelは切り出しで変わらない）。
"""

import io
import re

import mapbox_vector_tile
from PIL import Image
from shapely.affinity import scale, translate
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry

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


#: MVTのタイル内座標の既定extent（配信元のタイルもこの値を使う。デコード結果が
#: extentを持たない場合のフォールバック）。
_DEFAULT_MVT_EXTENT = 4096

#: 切り出し時にタイル境界の外側へ残す余白（extentに対する割合）。線がタイルの継ぎ目で
#: 途切れて見えないよう、MVTの慣習どおり少しはみ出させたまま持つ。
_MVT_CLIP_BUFFER_RATIO = 1 / 64


def _geometry_family(geometry: BaseGeometry) -> str:
    """Point/LineString/Polygonのどの系統か（Multi・単体をまとめた呼び名）。"""
    return geometry.geom_type.replace("Multi", "")


def _same_family_parts(clipped: BaseGeometry, family: str) -> BaseGeometry | None:
    """切り出し結果から元と同じ系統の部分だけを取り出す。

    線を矩形で切ると、辺に接した箇所が点として混ざったGeometryCollectionになることがある。
    元が線なら線だけを残す（点は描画に寄与せず、MVTのエンコードでも型が揃わない）。
    """
    if clipped.is_empty:
        return None
    if clipped.geom_type == "GeometryCollection":
        parts = [g for g in clipped.geoms if _geometry_family(g) == family and not g.is_empty]
        if not parts:
            return None
        from shapely.geometry import GeometryCollection  # 局所import: 通常経路では使わない

        merged = GeometryCollection(parts)
        return merged if len(parts) > 1 else parts[0]
    return clipped if _geometry_family(clipped) == family else None


def crop_and_upscale_mvt(parent_pbf: bytes, quadrant: tuple[int, int]) -> bytes:
    """親のベクタタイルの指定象限を切り出し、同じextentのタイルとしてエンコードし直す。

    デコード結果の座標系は**y軸が上向き**（`y_coord_down=False`が既定）なのに対し、
    `quadrant`はタイルXY（yは南向きに増える）で表されるため、上下を入れ替えて対応付ける。

    どの地物も象限に掛からなければ0バイト（＝地物なし）を返す。これは配信元がその
    ズームで404を返すのと同じ意味で、呼び出し側がキャッシュへ書き戻すことで次回以降の
    上流問い合わせを省ける。
    """
    decoded = mapbox_vector_tile.decode(parent_pbf)
    quadrant_x, quadrant_y = quadrant
    layers = []
    # extentはレイヤーごとに違いうるため、エンコード時も層ごとに指定する。
    layer_options: dict[str, dict[str, int]] = {}
    for name, layer in decoded.items():
        extent = layer.get("extent") or _DEFAULT_MVT_EXTENT
        half = extent / 2
        left = quadrant_x * half
        # タイルXYのy=0（北半分）は、y軸が上向きの座標系では上半分＝[half, extent]。
        bottom = (1 - quadrant_y) * half
        margin = extent * _MVT_CLIP_BUFFER_RATIO / 2
        clip_box = box(left - margin, bottom - margin, left + half + margin, bottom + half + margin)
        features = []
        for feature in layer["features"]:
            geometry = shape(feature["geometry"])
            clipped = _same_family_parts(geometry.intersection(clip_box), _geometry_family(geometry))
            if clipped is None:
                continue
            moved = scale(
                translate(clipped, xoff=-left, yoff=-bottom), xfact=2, yfact=2, origin=(0, 0)
            )
            entry = {"geometry": moved, "properties": feature.get("properties", {})}
            if feature.get("id") is not None:
                entry["id"] = feature["id"]
            features.append(entry)
        if features:
            layers.append({"name": name, "features": features})
            layer_options[name] = {"extents": int(extent)}
    if not layers:
        return b""
    return mapbox_vector_tile.encode(layers, per_layer_options=layer_options)
