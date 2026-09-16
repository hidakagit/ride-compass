"""土地被覆ラスタタイルの描画（infrastructure/landcover_raster.py）と配信
（api/routers/region.py）。

実ラスタ（配布元のGeoTIFF）はリポジトリに無いため、東京付近へ置いた小さな合成ラスタを
UTM 54N（配布元と同じCRS）で作り、再投影を含む実際の経路をそのまま通す。
"""

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from PIL import Image
from io import BytesIO
from rasterio.transform import from_origin

from app.config import settings
from app.domain.landcover import (
    LANDCOVER_CLASSES,
    LANDCOVER_TILE_MAX_ZOOM,
    LANDCOVER_TILE_MIN_ZOOM,
    LULC_BUILT,
    LULC_INVALID_VALUES,
    LULC_TREES,
    LandcoverPercentages,
)
from app.api import cache_policy
from app.infrastructure import landcover_raster, rate_limiter, tile_cache
from app.services import landcover_tile_service
from app.main import app

client = TestClient(app)

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


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


def _colors(png: bytes) -> set[tuple[int, int, int, int]]:
    with Image.open(BytesIO(png)) as image:
        assert image.size == (256, 256)
        return {color for _count, color in image.convert("RGBA").getcolors(maxcolors=256 * 256)}


def _rgba(color: str) -> tuple[int, int, int, int]:
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16), 255)


def test_class_registry_covers_every_percent_column():
    """割合8列と表示クラスが1対1であること（列を足して表示だけ取り残さない）。"""
    percent_fields = {name for name in LandcoverPercentages.model_fields if name.endswith("_percent")}
    assert {cls.percent_field for cls in LANDCOVER_CLASSES} == percent_fields
    # 無効値（No Data・Clouds）は表示対象を持たない。
    assert not {cls.value for cls in LANDCOVER_CLASSES} & LULC_INVALID_VALUES


def test_render_tile_paints_classes_with_their_own_colors(synthetic_raster):
    png = landcover_raster.render_tile(_TILE_Z, _TILE_X, _TILE_Y)
    assert png is not None
    colors = _colors(png)
    by_key = {cls.percent_field: cls for cls in LANDCOVER_CLASSES}
    assert _rgba(by_key["trees_percent"].color) in colors
    assert _rgba(by_key["built_percent"].color) in colors
    # ラスタが覆わない部分は透明のまま残る（合成ラスタはタイルより小さい）。
    assert (0, 0, 0, 0) in colors
    # 混色は作らない。塗られている色はクラスの色そのものだけ。
    assert colors <= {(0, 0, 0, 0)} | {_rgba(cls.color) for cls in LANDCOVER_CLASSES}


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


def test_landcover_tile_endpoint_returns_png(synthetic_raster, monkeypatch):
    monkeypatch.setattr(tile_cache, "get", lambda path: None)
    monkeypatch.setattr(tile_cache, "set", lambda path, content, content_type: None)

    response = client.get(f"/api/region/landcover-tiles/{_TILE_Z}/{_TILE_X}/{_TILE_Y}.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_landcover_tile_endpoint_without_raster_reports_unavailable(monkeypatch):
    """ラスタ未設定は「範囲外で空」ではなく、利用できない状態として出す
    （地図チップのデータ状態がエラーになり、黙って白紙にならない）。"""
    monkeypatch.setattr(settings, "lulc_raster_paths", "")
    landcover_raster.reset_sources_for_testing()
    try:
        response = client.get(f"/api/region/landcover-tiles/{_TILE_Z}/{_TILE_X}/{_TILE_Y}.png")
    finally:
        landcover_raster.reset_sources_for_testing()

    assert response.status_code == 503


@pytest.mark.parametrize("z", [LANDCOVER_TILE_MIN_ZOOM - 1, LANDCOVER_TILE_MAX_ZOOM + 1])
def test_landcover_tile_endpoint_rejects_zoom_outside_range(z):
    response = client.get(f"/api/region/landcover-tiles/{z}/1/1.png")
    assert response.status_code == 400


def test_tile_cache_path_changes_when_the_raster_set_changes(monkeypatch):
    """ラスタを1枚足すとディスクキャッシュの鍵が変わる。

    タイルの中身は「どのラスタを開いていたか」に従属する。鍵が同じだと、対応範囲を
    広げても継ぎ目のタイルが古い絵（片側が透明のまま）を返し続け、利用者側からは
    復旧できない。
    """
    monkeypatch.setattr(settings, "lulc_raster_paths", "/app/raster/54S_2024.tif")
    before = landcover_tile_service._tile_cache_path(10, 1, 2)
    monkeypatch.setattr(
        settings, "lulc_raster_paths", "/app/raster/54S_2024.tif,/app/raster/53S_2024.tif"
    )
    after = landcover_tile_service._tile_cache_path(10, 1, 2)

    assert before != after
    # 世代（配色・クラス構成）そのものは変わらない——URLは同じまま、サーバー側の鍵だけが割れる。
    assert landcover_tile_service.LANDCOVER_TILE_VERSION in before
    assert landcover_tile_service.LANDCOVER_TILE_VERSION in after


def test_landcover_tiles_are_not_served_as_immutable():
    """開いているラスタの構成はURLに現れないため、内容が変わりうる。

    `immutable`を付けるとブラウザは条件付きリクエストすら省き、ラスタを足しても
    その利用者の画面は`max-age`のあいだ古いまま戻らない。
    """
    policy = cache_policy.policy_for_path("/api/region/landcover-tiles/10/1/2.png")

    assert policy is not None
    assert policy.immutable is False
