"""土地被覆ラスタ（Esri×Impact Observatory Sentinel-2 10m Annual LULC）のタイル描画。

`settings.lulc_raster_paths`のGeoTIFFから、要求されたXYZタイルが覆う範囲を切り出し、
`domain/landcover.py: LANDCOVER_CLASSES`の配色で塗ったPNG（RGBA）を返す。集約を挟まず
元の10m画素を1画素1色のまま出すため、割合の混合（`way_landcover`が持つ8クラスの割合）を
どう塗るかという問題が起きない。

**再投影は最近傍で行う**。画素値はクラス番号であって量ではなく、平均・線形補間をかけると
存在しないクラス（例: 農地5と建物7の平均で6）が生まれる。

`rasterio`のimport前に`proj_data.pin_bundled_proj_data()`を呼ぶ必要があるため、この
モジュールはimport順に依存する（呼ばないとEPSG解決が環境によって失敗する）。
"""

import logging
import threading
import time
from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image

from app.config import settings
from app.domain.landcover import LANDCOVER_CLASSES
from app.infrastructure.proj_data import pin_bundled_proj_data

pin_bundled_proj_data()

import rasterio  # noqa: E402
import rasterio.errors  # noqa: E402
from rasterio.transform import from_bounds  # noqa: E402
from rasterio.warp import Resampling, reproject, transform_bounds  # noqa: E402
from rasterio.windows import Window, transform as window_transform  # noqa: E402

logger = logging.getLogger("ridecompass.landcover_raster")

TILE_SIZE = 256
TILE_CRS = "EPSG:3857"

# Web Mercatorの座標系が覆う範囲の半幅（m）。z/x/yからタイルの矩形を出すのに使う。
_WEB_MERCATOR_HALF_M = 20037508.342789244

# 1回の読み取りで扱う元画素の上限（1辺）。低ズームのタイルほど元画素を多く覆うため、
# これを超える場合は間引いて読む（GDAL側で間引かれ、メモリは常にこの辺長の2乗で収まる）。
# 出力が256画素である以上、これ以上細かく読んでも結果は変わらない。
_MAX_SOURCE_READ_SIDE = 1024


@dataclass
class _RasterSource:
    """開いたままのラスタ1枚。

    `rasterio`のDatasetReaderは同時読み取りに耐えないため、読み取りをロックで直列化する
    （タイル要求はスレッドプールから並列に入る）。
    """

    dataset: "rasterio.DatasetReader"
    lock: threading.Lock


_sources: list[_RasterSource] | None = None
_sources_lock = threading.Lock()
#: 1枚も開けなかったときに、次に開き直すまで待つ秒数。**失敗を記憶し続けない**——デプロイは
#: ラスタの取得とコンテナ入れ替えを別のステップで行うため、起動時に無くても後から現れる。
#: 毎回開き直すとタイル1枚ごとにI/Oとログが出るので、間隔を空けて試す。
_RETRY_OPEN_AFTER_SECONDS = 60.0
_last_open_attempt = 0.0

#: 画素値→RGBA。`LANDCOVER_CLASSES`に無い値（No Data・Clouds）と、塗らないと宣言した
#: クラスは透明のまま残る。
_PALETTE = np.zeros((256, 4), dtype=np.uint8)
for _cls in (c for c in LANDCOVER_CLASSES if c.painted):
    _PALETTE[_cls.value] = (
        int(_cls.color[1:3], 16),
        int(_cls.color[3:5], 16),
        int(_cls.color[5:7], 16),
        255,
    )


def _open_sources() -> list[_RasterSource]:
    """設定されたラスタを開く。1枚でも開けたらそれを保持し、以後は開き直さない。

    **1枚も開けなかった場合は記憶しない**（`_RETRY_OPEN_AFTER_SECONDS`だけ空けて再挑戦する）。
    デプロイはラスタの取得とコンテナ入れ替えを別のステップで行うため、起動時に無くても
    後から現れる——記憶してしまうと、そのプロセスが生きている間ずっと配信できない。
    """
    global _sources, _last_open_attempt
    with _sources_lock:
        if _sources:
            return _sources
        now = time.monotonic()
        if _sources is not None and now - _last_open_attempt < _RETRY_OPEN_AFTER_SECONDS:
            return _sources
        _last_open_attempt = now
        opened: list[_RasterSource] = []
        for path in settings.lulc_raster_paths_list:
            try:
                opened.append(_RasterSource(rasterio.open(path), threading.Lock()))
            except (OSError, rasterio.errors.RasterioIOError) as exc:
                logger.warning("土地被覆ラスタを開けません path=%s error=%r", path, exc)
        _sources = opened
        return _sources


def reset_sources_for_testing() -> None:
    """開いたラスタを閉じて未初期化へ戻す（設定を差し替えるテスト用）。"""
    global _sources
    with _sources_lock:
        for source in _sources or []:
            source.dataset.close()
        _sources = None


def tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """XYZタイルが覆う範囲（Web Mercatorのメートル、west/south/east/north）。"""
    size = 2 * _WEB_MERCATOR_HALF_M / (2**z)
    west = -_WEB_MERCATOR_HALF_M + x * size
    north = _WEB_MERCATOR_HALF_M - y * size
    return west, north - size, west + size, north


def _read_decimated(source: _RasterSource, bounds: tuple[float, float, float, float]):
    """ラスタ`source`から`bounds`（そのラスタのCRS）を覆う部分を、必要なら間引いて読む。

    戻り値は(画素配列, その配列に対応するtransform)。範囲が重ならなければNone。
    """
    dataset = source.dataset
    # **datasetへ触る全体をロックで囲う**。`read`だけを囲っても、`window`・`transform`は
    # 同じDatasetReaderの状態を読むため直列化にならない（docstringが宣言しているのは
    # 「読み取りの直列化」で、1行だけではそれを満たさない）。
    with source.lock:
        window = dataset.window(*bounds).round_offsets().round_lengths()
        try:
            window = window.intersection(Window(0, 0, dataset.width, dataset.height))
        except rasterio.errors.WindowError:
            # 重なりが空。ゾーン単位のラスタに対しては、覆っていないタイルの方が普通に多い。
            return None
        if window.width <= 0 or window.height <= 0:
            return None
        scale = max(window.width, window.height) / _MAX_SOURCE_READ_SIDE
        if scale > 1:
            out_shape = (max(1, int(window.height / scale)), max(1, int(window.width / scale)))
        else:
            out_shape = (int(window.height), int(window.width))
        data = dataset.read(1, window=window, out_shape=out_shape, resampling=Resampling.nearest)
        base = window_transform(window, dataset.transform)
    # 間引いて読むと1画素が覆う実距離が伸びる。読んだ配列の形へtransformを合わせないと、
    # 再投影が元の画素サイズのまま貼り付けてタイルの一部しか埋まらない。
    return data, base * base.scale(window.width / data.shape[1], window.height / data.shape[0])


def empty_tile_png() -> bytes:
    """全面透明のPNG（ラスタが覆わない範囲へ返す空タイル）。"""
    buffer = BytesIO()
    Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0)).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def has_sources() -> bool:
    """配信できるラスタが1枚でもあるか（未設定・開けないものしか無い状態と区別する）。"""
    return bool(_open_sources())


def render_tile(z: int, x: int, y: int) -> bytes | None:
    """1タイルぶんのPNG（RGBA、256x256）を返す。

    どのラスタも覆っていない範囲ではNone——ラスタの外側は「土地被覆が無い」のではなく
    このデータが何も言えない場所で、呼び出し側が空タイルとして扱う（後からラスタを
    足せば値を持ちうるため、キャッシュへは残さない）。
    """
    sources = _open_sources()
    bounds = tile_bounds_3857(z, x, y)
    dst_transform = from_bounds(*bounds, TILE_SIZE, TILE_SIZE)
    classes = np.zeros((TILE_SIZE, TILE_SIZE), dtype=np.uint8)

    for source in sources:
        dataset = source.dataset
        # densify_pts: 投影をまたぐと矩形の辺は直線でなくなる。角だけで変換すると、
        # 辺のふくらみぶんが読み取り範囲から落ちてタイルの縁が欠ける。
        src_bounds = transform_bounds(TILE_CRS, dataset.crs, *bounds, densify_pts=21)
        read = _read_decimated(source, src_bounds)
        if read is None:
            continue
        data, src_transform = read
        patch = np.zeros((TILE_SIZE, TILE_SIZE), dtype=np.uint8)
        reproject(
            source=data,
            destination=patch,
            src_transform=src_transform,
            src_crs=dataset.crs,
            dst_transform=dst_transform,
            dst_crs=TILE_CRS,
            resampling=Resampling.nearest,
            src_nodata=0,
            dst_nodata=0,
        )
        # 先に値が入った側を残す（複数枚が重なる継ぎ目で、後のラスタの範囲外[0]が
        # 既に描けている画素を消さないようにする）。
        classes = np.where(classes == 0, patch, classes)

    if not classes.any():
        return None

    image = Image.fromarray(_PALETTE[classes], mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
