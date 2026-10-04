"""`infrastructure/landcover_raster.py`——土地被覆のGeoTIFFから、XYZタイル1枚ぶんのクラスと絵を作る。

入口は`tile_classes`・`render_tile`・`empty_tile_png`・`has_sources`・`opened_raster_paths`。
ラスタは一時ディレクトリに本物のGeoTIFFを書き、設定（`settings.lulc_raster_paths`）でその置き場を
渡す。開いたラスタはプロセスに残るので、テストごとに開く前の状態から始めて、後で閉じる。
タイルの範囲はXYZの公開の定義（Web Mercatorの全幅を2^z等分し、yは北から数える）から作る。

ここで見ないもの:
- 配色の中身（どのクラスを塗り、何色か） → `domain/landcover.py: LANDCOVER_CLASSES`の宣言。
  ここではクラスを「塗る」「塗らない」の性質で選び、色は宣言から読む
- 空のタイルを返すか503にするか・キャッシュの鍵 → `test_landcover_tile.py`
- 取込がタイルのクラスをDBへ入れること → 取込のアダプタ（`batch/source_adapters/io_lulc_tile.py`）の持ち物
"""

import io
import logging
import math

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from rasterio.warp import transform as transform_points

from app.infrastructure import landcover_raster

HALF_WORLD_M = 20037508.342789244
TOKYO = (14, 14552, 6451)
SIZE = landcover_raster.TILE_SIZE


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    size = 2 * HALF_WORLD_M / 2**z
    west = -HALF_WORLD_M + x * size
    north = HALF_WORLD_M - y * size
    return west, north - size, west + size, north


def tile_center_lonlat(z: int, x: int, y: int) -> tuple[float, float]:
    n = 2**z
    lon = (x + 0.5) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / n))))
    return lon, lat


def write_raster(path, classes: np.ndarray, crs: str, west: float, north: float, pixel_m: float) -> str:
    height, width = classes.shape
    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=1, dtype="uint8", crs=crs,
        transform=from_origin(west, north, pixel_m, pixel_m), compress="deflate",
    ) as dataset:
        dataset.write(classes.astype(np.uint8), 1)
    return str(path)


def over_tile(path, classes: np.ndarray, z: int, x: int, y: int) -> str:
    """タイルの範囲をちょうど覆うWeb Mercatorのラスタ（1画素がタイルの1画素に揃う大きさなら、画素がそのまま写る）。"""
    west, _, east, north = tile_bounds(z, x, y)
    return write_raster(path, classes, "EPSG:3857", west, north, (east - west) / classes.shape[1])


@pytest.fixture
def configure(monkeypatch):
    """設定するラスタの置き場を渡し、ラスタをまだ開いていない状態から始める。"""
    monkeypatch.setattr(landcover_raster, "opened_sources", None)

    def configure(*paths: str) -> None:
        monkeypatch.setattr(landcover_raster.settings, "lulc_raster_paths", ",".join(paths))

    yield configure
    for source in landcover_raster.opened_sources or []:
        source.dataset.close()


def stripes(*values: int, size: int = SIZE) -> np.ndarray:
    """西から東へ、等しい幅の縦縞に値を並べる。"""
    columns = np.array_split(np.arange(size), len(values))
    out = np.zeros((size, size), dtype=np.uint8)
    for value, cols in zip(values, columns, strict=True):
        out[:, cols] = value
    return out


def decoded(png: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(png)) as image:
        assert image.mode == "RGBA"
        return np.asarray(image)


def test_reprojecting_a_utm_raster_keeps_class_numbers_and_invents_none(tmp_path, configure):
    """画素値はクラス番号なので、隣り合う2クラスの間に別のクラスが生まれてはいけない。"""
    lon, lat = tile_center_lonlat(*TOKYO)
    (easting,), (northing,) = transform_points("EPSG:4326", "EPSG:32654", [lon], [lat])
    half_m = 3000
    configure(write_raster(tmp_path / "54S.tif", stripes(5, 7, size=600), "EPSG:32654",
                           easting - half_m, northing + half_m, 10))

    classes = landcover_raster.tile_classes(*TOKYO)

    assert classes.shape == (SIZE, SIZE)
    # タイルはラスタの内側にあるので、縁まで全画素がクラスを持つ。
    assert set(np.unique(classes)) == {5, 7}


def test_a_tile_no_raster_reaches_has_no_classes_and_no_image(tmp_path, configure):
    configure(over_tile(tmp_path / "a.tif", stripes(2), *TOKYO))
    z, x, y = TOKYO

    assert landcover_raster.tile_classes(z, x + 2, y) is None
    assert landcover_raster.render_tile(z, x + 2, y) is None


def test_where_rasters_overlap_the_first_configured_wins_and_the_next_fills_its_gaps(tmp_path, configure):
    """値0（範囲外・No Data）は、先のラスタが描いた画素を消さず、後のラスタに埋めさせる。"""
    west_only = over_tile(tmp_path / "west.tif", stripes(2, 0), *TOKYO)
    everywhere = over_tile(tmp_path / "all.tif", stripes(5), *TOKYO)

    configure(west_only, everywhere)
    classes = landcover_raster.tile_classes(*TOKYO)

    assert (classes[:, : SIZE // 2] == 2).all()
    assert (classes[:, SIZE // 2 :] == 5).all()


def test_the_raster_listed_first_is_not_overwritten_by_a_later_one(tmp_path, configure):
    west_only = over_tile(tmp_path / "west.tif", stripes(2, 0), *TOKYO)
    everywhere = over_tile(tmp_path / "all.tif", stripes(5), *TOKYO)

    configure(everywhere, west_only)

    assert (landcover_raster.tile_classes(*TOKYO) == 5).all()


def test_a_raster_finer_than_the_read_limit_still_fills_the_whole_tile(tmp_path, configure):
    """低いズームでは間引いて読む。間引いた分の画素の大きさを合わせないと、タイルの一部しか埋まらない。"""
    z, x, y = 12, TOKYO[1] // 4, TOKYO[2] // 4
    configure(over_tile(tmp_path / "fine.tif", stripes(2, 5, size=2048), z, x, y))

    classes = landcover_raster.tile_classes(z, x, y)

    assert (classes[:, : SIZE // 2] == 2).all()
    assert (classes[:, SIZE // 2 :] == 5).all()


def test_the_image_paints_painted_classes_in_their_colour_and_leaves_the_rest_clear(tmp_path, configure):
    classes = landcover_raster.LANDCOVER_CLASSES
    painted = [c for c in classes if c.painted]
    unpainted = [c for c in classes if not c.painted]
    assert painted, "塗るクラスが1つも無い"
    assert unpainted, "塗らないクラスが1つも無い"
    unknown = next(v for v in range(1, 256) if v not in {c.value for c in classes})
    configure(over_tile(tmp_path / "a.tif", stripes(painted[0].value, unpainted[0].value, unknown), *TOKYO))

    image = decoded(landcover_raster.render_tile(*TOKYO))

    assert image.shape == (SIZE, SIZE, 4)
    hex_colour = painted[0].color.lstrip("#")
    assert tuple(image[SIZE // 2, 10]) == (*bytes.fromhex(hex_colour), 255)
    assert image[SIZE // 2, SIZE // 2, 3] == 0
    assert image[SIZE // 2, SIZE - 10, 3] == 0


def test_the_empty_tile_is_a_fully_clear_image_of_tile_size():
    image = decoded(landcover_raster.empty_tile_png())

    assert image.shape == (SIZE, SIZE, 4)
    assert (image[:, :, 3] == 0).all()


def test_a_configured_raster_that_cannot_be_opened_is_skipped_and_logged(tmp_path, configure, caplog):
    present = over_tile(tmp_path / "present.tif", stripes(2), *TOKYO)
    configure(str(tmp_path / "missing.tif"), present)

    with caplog.at_level(logging.WARNING, logger="ridecompass.landcover_raster"):
        assert landcover_raster.has_sources()

    assert landcover_raster.opened_raster_paths() == [present]
    assert "missing.tif" in caplog.text


def test_once_a_raster_is_open_the_set_of_rasters_stays_until_restart(tmp_path, configure):
    first = over_tile(tmp_path / "first.tif", stripes(2), *TOKYO)
    configure(first)
    assert landcover_raster.opened_raster_paths() == [first]

    configure(first, over_tile(tmp_path / "second.tif", stripes(5), *TOKYO))

    assert landcover_raster.opened_raster_paths() == [first]


def test_a_raster_that_appears_after_start_is_picked_up_after_the_retry_interval(tmp_path, configure, clock, caplog):
    """デプロイはラスタの取得とコンテナの入れ替えを別に行うので、起動時に無くても後から現れる。"""
    path = tmp_path / "late.tif"
    configure(str(path))
    with caplog.at_level(logging.WARNING, logger="ridecompass.landcover_raster"):
        assert not landcover_raster.has_sources()
        over_tile(path, stripes(2), *TOKYO)
        clock.tick(59)
        assert not landcover_raster.has_sources()

    assert len([r for r in caplog.records if "late.tif" in r.getMessage()]) == 1
    clock.tick(1)
    assert landcover_raster.has_sources()
    assert landcover_raster.opened_raster_paths() == [str(path)]
