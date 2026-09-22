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
    LULC_TREES,
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


def test_tile_cache_key_follows_the_rasters_actually_opened(synthetic_raster, monkeypatch):
    """欠けたゾーンの絵を「完全な構成」の鍵で残さない。

    デプロイはラスタの取得とコンテナ入れ替えを別のステップで行うため、**設定に並んでいても
    まだ置かれていない**ことがある。そのとき設定の側で鍵を作ると、片側が透明なタイルが
    正しい鍵で恒久的に残り、ラスタが揃っても返り続ける。
    """
    opened_only = landcover_tile_service._tile_cache_path(_TILE_Z, _TILE_X, _TILE_Y)

    # 設定にだけ、まだ置かれていないゾーンを足す（開ける側は変わらない）。
    monkeypatch.setattr(
        settings, "lulc_raster_paths", f"{settings.lulc_raster_paths},/not/yet/placed_54T.tif"
    )
    configured_but_missing = landcover_tile_service._tile_cache_path(_TILE_Z, _TILE_X, _TILE_Y)

    assert configured_but_missing == opened_only


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


def test_tile_cache_path_changes_when_the_raster_set_changes(synthetic_raster, tmp_path, monkeypatch):
    """ラスタを1枚足すとディスクキャッシュの鍵が変わる。

    タイルの中身は「どのラスタを開いていたか」に従属する。鍵が同じだと、対応範囲を
    広げても継ぎ目のタイルが古い絵（片側が透明のまま）を返し続け、利用者側からは
    復旧できない。
    """
    before = landcover_tile_service._tile_cache_path(10, 1, 2)
    # 2枚目を**実際に開ける形で**足す。鍵は開けているラスタから作るため、置かれていない
    # パスを並べても鍵は変わらない（それ自体は別のテストが押さえる）。
    second = tmp_path / "53S_synthetic.tif"
    with rasterio.open(
        second, "w", driver="GTiff", width=_SIZE_PX, height=_SIZE_PX, count=1, dtype="uint8",
        crs="EPSG:32654", transform=from_origin(_ORIGIN_EASTING, _ORIGIN_NORTHING, _PIXEL_M, _PIXEL_M),
        nodata=0,
    ) as dataset:
        dataset.write(np.full((_SIZE_PX, _SIZE_PX), LULC_TREES, dtype=np.uint8), 1)
    monkeypatch.setattr(settings, "lulc_raster_paths", f"{settings.lulc_raster_paths},{second}")
    landcover_raster.reset_sources_for_testing()
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
