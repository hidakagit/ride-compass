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

import mapbox_vector_tile
from PIL import Image
from shapely import union_all
from shapely.affinity import scale, translate
from shapely.geometry import GeometryCollection, box, shape
from shapely.geometry.base import BaseGeometry

from app.domain.jma_tile_specs import JmaTile, jma_tile_path
from app.infrastructure.jma_tile_paths import read_jma_tile_path

class TileCoords:
    """タイルパスから読み取った座標と、親タイルのパスを組み立てる手段。"""

    def __init__(self, tile: JmaTile, ext: str):
        self._tile = tile
        self.element = tile.element_id
        self.z = tile.z
        self.x = tile.x
        self.y = tile.y
        self.ext = ext

    def parent_path(self) -> str:
        """1段上（z-1）のタイルのパス。"""
        return jma_tile_path(self._tile._replace(z=self.z - 1, x=self.x // 2, y=self.y // 2))

    @property
    def quadrant(self) -> tuple[int, int]:
        """親タイルのどの象限に対応するか（左上を(0,0)とする）。"""
        return self.x % 2, self.y % 2


def parse_tile_path(path: str) -> TileCoords | None:
    """タイルパスを解析する。タイル以外（時刻一覧・地点のGeoJSON等）と宣言の無い要素はNone。"""
    tile = read_jma_tile_path(path)
    # 読み戻せたパスはテンプレートどおりに拡張子（ベクタは`pbf`、ラスタは`png`）で終わる。
    return None if tile is None else TileCoords(tile, path.rsplit(".", 1)[1])


def crop_and_upscale(parent_png: bytes, quadrant: tuple[int, int]) -> bytes:
    """親タイルの指定象限を切り出し、元のタイルサイズへ最近傍で拡大する。"""
    with Image.open(io.BytesIO(parent_png)) as source:
        width, height = source.size
        half_width, half_height = width // 2, height // 2
        left = quadrant[0] * half_width
        top = quadrant[1] * half_height
        # パレット形式（実データを持つタイル）とRGBA（空タイル）が混在するため、切り出した4分の1をRGBAへ揃える。
        cropped = source.crop((left, top, left + half_width, top + half_height)).convert("RGBA")
        upscaled = cropped.resize((width, height), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    upscaled.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


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
    残る部分が複数ならMulti系の1つの形へまとめる（MVTはGeometryCollectionをエンコードできない）。
    """
    if clipped.is_empty:
        return None
    if isinstance(clipped, GeometryCollection):
        parts = [g for g in clipped.geoms if _geometry_family(g) == family and not g.is_empty]
        return union_all(parts) if parts else None
    return clipped if _geometry_family(clipped) == family else None


def crop_and_upscale_mvt(parent_pbf: bytes, quadrant: tuple[int, int]) -> bytes:
    """親のベクタタイルの指定象限を切り出し、同じextentのタイルとしてエンコードし直す。

    デコード結果の座標系は**y軸が上向き**（`y_coord_down=False`が既定）なのに対し、
    `quadrant`はタイルXY（yは南向きに増える）で表されるため、上下を入れ替えて対応付ける。

    どの地物も象限に掛からなければ0バイト（＝地物なし）を返す。これは配信元がその
    ズームで404を返すのと同じ意味で、呼び出し側がキャッシュへ書き戻すことで次回以降の
    上流問い合わせを省ける。

    デコード結果は層ごとの`extent`と地物ごとの`id`・`properties`を必ず持つ（タイルに無い項目はMVTの既定値で埋まる）。
    """
    decoded = mapbox_vector_tile.decode(parent_pbf)
    quadrant_x, quadrant_y = quadrant
    layers = []
    # extentはレイヤーごとに違いうるため、エンコード時も層ごとに指定する。
    layer_options: dict[str, dict[str, int]] = {}
    for name, layer in decoded.items():
        extent = layer["extent"]
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
            features.append({"geometry": moved, "properties": feature["properties"], "id": feature["id"]})
        if features:
            layers.append({"name": name, "features": features})
            layer_options[name] = {"extents": int(extent)}
    if not layers:
        return b""
    return mapbox_vector_tile.encode(layers, per_layer_options=layer_options)
