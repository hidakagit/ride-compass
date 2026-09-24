"""`infrastructure/landcover_raster.py`——土地被覆ラスタからタイル1枚を描く。

実ラスタ（配布元のGeoTIFF）はリポジトリに無いため、東京付近へ置いた小さな合成ラスタを
UTM 54N（配布元と同じCRS）で作り、再投影を含む実際の経路をそのまま通す。
"""

from io import BytesIO

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin

from app.config import settings
from app.domain.landcover import LANDCOVER_CLASSES, LULC_BUILT, LULC_TREES
from app.infrastructure import landcover_raster

# 合成ラスタの位置（東京付近、UTM 54N）。1辺1kmで、下のz14タイル（地上でおよそ2km四方）
# より小さくしてある——タイルの一部だけが覆われる状態にして、覆わない部分が透明のまま
# 残ることも同じ1枚で確かめる。
_ORIGIN_EASTING = 380000.0
_ORIGIN_NORTHING = 3950000.0
_PIXEL_M = 10.0
_SIZE_PX = 100
# 上のラスタの中心（経度139.679度・緯度35.682度）を含むz14タイル。
_TILE_Z, _TILE_X, _TILE_Y = 14, 14548, 6451


@pytest.fixture
def synthetic_raster(tmp_path, monkeypatch):
    """左半分が樹木・右半分が建物の合成ラスタを設定へ差し込む。"""
    path = tmp_path / "54S_synthetic.tif"
    data = np.full((_SIZE_PX, _SIZE_PX), LULC_TREES, dtype=np.uint8)
    data[:, _SIZE_PX // 2 :] = LULC_BUILT
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=_SIZE_PX,
        height=_SIZE_PX,
        count=1,
        dtype="uint8",
        crs="EPSG:32654",
        transform=from_origin(_ORIGIN_EASTING, _ORIGIN_NORTHING, _PIXEL_M, _PIXEL_M),
        nodata=0,
    ) as dataset:
        dataset.write(data, 1)

    monkeypatch.setattr(settings, "lulc_raster_paths", str(path))
    landcover_raster.reset_sources_for_testing()
    yield path
    landcover_raster.reset_sources_for_testing()


def _colors(png: bytes) -> set[tuple[int, int, int, int]]:
    with Image.open(BytesIO(png)) as image:
        assert image.size == (256, 256)
        return {color for _count, color in image.convert("RGBA").getcolors(maxcolors=256 * 256)}


def _rgba(color: str) -> tuple[int, int, int, int]:
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16), 255)


def test_render_tile_paints_classes_with_their_own_colors(synthetic_raster):
    png = landcover_raster.render_tile(_TILE_Z, _TILE_X, _TILE_Y)
    assert png is not None
    colors = _colors(png)
    by_key = {cls.percent_field: cls for cls in LANDCOVER_CLASSES}
    assert _rgba(by_key["trees_percent"].color) in colors
    # ラスタが覆わない部分は透明のまま残る（合成ラスタはタイルより小さい）。
    assert (0, 0, 0, 0) in colors
    # 混色は作らない。塗られている色はクラスの色そのものだけ。
    assert colors <= {(0, 0, 0, 0)} | {_rgba(cls.color) for cls in LANDCOVER_CLASSES}


def test_render_tile_leaves_unpainted_classes_transparent(synthetic_raster):
    """塗らないと宣言したクラスの画素は透明のまま残る。

    建物は市街地で画素の大半を占め、塗ると地図が単色で覆われるだけになる
    （docs/records/tasks/T902.md）。合成ラスタは建物の画素を含むが、色は出ない。
    """
    png = landcover_raster.render_tile(_TILE_Z, _TILE_X, _TILE_Y)
    assert png is not None
    colors = _colors(png)
    unpainted = {_rgba(cls.color) for cls in LANDCOVER_CLASSES if not cls.painted}

    assert unpainted, "塗らないクラスが1つも無いなら、このテストは何も確かめていない"
    assert not (colors & unpainted)


def test_render_tile_outside_raster_returns_none(synthetic_raster):
    """ラスタが覆わない範囲は「値なし」。空タイルを作るのは呼び出し側の役目。"""
    assert landcover_raster.render_tile(_TILE_Z, 0, 0) is None


def test_render_tile_without_raster_configured(monkeypatch):
    monkeypatch.setattr(settings, "lulc_raster_paths", "")
    landcover_raster.reset_sources_for_testing()
    try:
        assert landcover_raster.has_sources() is False
    finally:
        landcover_raster.reset_sources_for_testing()
