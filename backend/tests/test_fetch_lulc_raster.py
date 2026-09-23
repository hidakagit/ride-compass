"""土地被覆ラスタの取得（scripts/fetch_lulc_raster.py）。

実ダウンロード（70MB規模）はテストで行わず、配布元の応答だけを差し替えて、
「既にあるものは触らない」「壊れたものを取得済みとして残さない」を確かめる。
"""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.config import settings
from scripts import fetch_lulc_raster
from tests.bound_fake import bound


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        pass

    def iter_bytes(self):
        yield self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


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


@pytest.fixture
def stub_download(monkeypatch):
    """配布元の応答を差し替える。返した本文がそのまま保存対象になる。"""

    calls: list[str] = []
    payload = {"body": b""}

    def fake_stream(_method, url, **_kwargs):
        calls.append(url)
        return _FakeResponse(payload["body"])

    monkeypatch.setattr(fetch_lulc_raster.httpx, "stream", bound(fetch_lulc_raster.httpx.stream, fake_stream))
    return calls, payload


def test_downloads_missing_raster_from_the_bucket(tmp_path, monkeypatch, stub_download):
    calls, payload = stub_download
    payload["body"] = _geotiff_bytes(tmp_path)
    destination = tmp_path / "raster" / "54S_2024.tif"
    monkeypatch.setattr(settings, "lulc_raster_paths", str(destination))

    assert fetch_lulc_raster.main() == 0

    assert destination.exists()
    # バケット内のキーは設定されたパスのファイル名そのもの（ゾーン・年は設定側の決定）。
    assert calls == [f"{fetch_lulc_raster.BUCKET_BASE_URL}/54S_2024.tif"]


def test_keeps_existing_raster_untouched(tmp_path, monkeypatch, stub_download):
    calls, _payload = stub_download
    existing = _geotiff_bytes(tmp_path)
    destination = tmp_path / "54S_2024.tif"
    destination.write_bytes(existing)
    monkeypatch.setattr(settings, "lulc_raster_paths", str(destination))

    assert fetch_lulc_raster.main() == 0

    assert destination.read_bytes() == existing
    assert calls == []


def test_does_not_leave_a_broken_file_behind(tmp_path, monkeypatch, stub_download):
    """ラスタとして読めない応答（配布元のエラー本文等）を「取得済み」にしない。

    残すと次の実行が再取得せず、壊れたラスタを読み続ける。
    """
    _calls, payload = stub_download
    payload["body"] = b"<Error>NoSuchKey</Error>"
    destination = tmp_path / "54S_2024.tif"
    monkeypatch.setattr(settings, "lulc_raster_paths", str(destination))

    assert fetch_lulc_raster.main() == 1

    assert not destination.exists()
    assert not list(tmp_path.glob("*.part"))
