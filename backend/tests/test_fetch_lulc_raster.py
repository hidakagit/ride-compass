"""土地被覆ラスタの取得（scripts/fetch_lulc_raster.py）。

入口は`main`。実ダウンロード（70MB規模）はテストで行わず、配布元の応答と置き場の設定だけを差し替えて、
設定のファイル名でバケットから取ることと、ラスタとして開けるかで取得済みかを決めることを確かめる。

ここで見ないもの:
- 一時ファイル経由の取得・読めるものを落とし直さない手順（`app/batch/common.py: fetch_verified`）
  → `test_fetch_accident_csv.py`
"""

import numpy as np
import rasterio
from rasterio.transform import from_origin

from app.config import settings
from scripts import fetch_lulc_raster


def _geotiff_bytes(tmp_path) -> bytes:
    path = tmp_path / "source.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="uint8",
        crs="EPSG:32654",
        transform=from_origin(380000.0, 3950000.0, 10.0, 10.0),
        nodata=0,
    ) as dataset:
        dataset.write(np.full((4, 4), 5, dtype="uint8"), 1)
    return path.read_bytes()


def test_downloads_missing_raster_from_the_bucket(tmp_path, monkeypatch, respx_mock):
    # バケット内のキーは設定されたパスのファイル名そのもの（ゾーン・年は設定側の決定）。
    respx_mock.get(f"{fetch_lulc_raster.BUCKET_BASE_URL}/54S_2024.tif").respond(
        content=_geotiff_bytes(tmp_path)
    )
    destination = tmp_path / "raster" / "54S_2024.tif"
    monkeypatch.setattr(settings, "lulc_raster_paths", str(destination))

    assert fetch_lulc_raster.main() == 0

    assert destination.exists()


def test_does_not_leave_a_broken_file_behind(tmp_path, monkeypatch, respx_mock):
    """ラスタとして読めない応答（配布元のエラー本文等）を「取得済み」にしない。

    残すと次の実行が再取得せず、壊れたラスタを読み続ける。
    """
    respx_mock.get(f"{fetch_lulc_raster.BUCKET_BASE_URL}/54S_2024.tif").respond(content=b"<Error>NoSuchKey</Error>")
    destination = tmp_path / "54S_2024.tif"
    monkeypatch.setattr(settings, "lulc_raster_paths", str(destination))

    assert fetch_lulc_raster.main() == 1

    assert not destination.exists()
