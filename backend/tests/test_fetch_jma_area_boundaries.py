"""気象庁の区域の境界の取得（scripts/fetch_jma_area_boundaries.py）。

実ダウンロード（150MB規模）はテストで行わず、配布元の応答を小さなシェープファイルのzipへ
差し替えて、「取得した境界から区域を引ける」「既にあるものは取りに行かない」「壊れたものを
取得済みとして残さない」を確かめる。
"""

import io
import zipfile

import pytest
import shapefile

from app.infrastructure import jma_area_boundaries
from scripts import fetch_jma_area_boundaries
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


def _square(lon: float, lat: float, size: float = 0.1) -> list[list[tuple[float, float]]]:
    return [[(lon, lat), (lon, lat + size), (lon + size, lat + size), (lon + size, lat), (lon, lat)]]


def _areas_zip() -> bytes:
    """配布元と同じ列（regioncode等）・同じ日本語のファイル名のzip。コードが空の図形も1つ含む。"""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON, encoding="utf-8") as writer:
        writer.field("regioncode", "C", size=7)
        writer.field("name", "C", size=84)
        writer.poly(_square(139.7, 35.6))
        writer.record("1310100", "千代田区")
        writer.poly(_square(139.9, 35.6))
        writer.record("1310200", "中央区")
        writer.poly(_square(146.0, 43.0))
        writer.record("", "色丹島")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as out:
        for suffix, body in ((".shp", shp), (".shx", shx), (".dbf", dbf)):
            out.writestr(f"気象警報等/市町村等（気象警報等）{suffix}", body.getvalue())
    return archive.getvalue()


@pytest.fixture
def stub_download(tmp_path, monkeypatch):
    """配布元の応答を差し替え、置き場を`tmp_path`へ移す。返した本文がそのまま取得物になる。"""
    calls: list[str] = []
    payload = {"body": b""}

    def fake_stream(_method, url, **_kwargs):
        calls.append(url)
        return _FakeResponse(payload["body"])

    monkeypatch.setattr(fetch_jma_area_boundaries.httpx, "stream",
                        bound(fetch_jma_area_boundaries.httpx.stream, fake_stream))
    destination = tmp_path / "jma_area" / "current.json"
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", destination)
    return calls, payload, destination


def test_fetched_boundaries_resolve_points_to_their_areas(stub_download):
    calls, payload, destination = stub_download
    payload["body"] = _areas_zip()
    old_version = destination.parent / "older.json"
    old_version.parent.mkdir(parents=True)
    old_version.write_text("{}", encoding="utf-8")

    assert fetch_jma_area_boundaries.main() == 0

    assert calls == [jma_area_boundaries.SOURCE_URL]
    boundaries = jma_area_boundaries.load_boundaries(destination)
    assert boundaries.find(35.65, 139.75) == "1310100"
    assert boundaries.find(35.65, 139.95) == "1310200"
    # コードの無い図形（警報の出ない区域）は書かない。
    assert boundaries.find(43.05, 146.05) is None
    # 置き場に残るのは今の版の境界だけ（落としたzip・前の版は消える）。
    assert list(destination.parent.iterdir()) == [destination]


def test_keeps_existing_boundaries_untouched(stub_download):
    calls, _payload, destination = stub_download
    destination.parent.mkdir(parents=True)
    destination.write_text("{}", encoding="utf-8")

    assert fetch_jma_area_boundaries.main() == 0

    assert destination.read_text(encoding="utf-8") == "{}"
    assert calls == []


def test_does_not_leave_boundaries_behind_from_a_broken_download(stub_download):
    """zipとして読めない応答（配布元のエラー本文等）から境界を作らない。

    作ると次の実行が再取得せず、区域を1つも引けない境界を読み続ける。
    """
    _calls, payload, destination = stub_download
    payload["body"] = b"<html>404 Not Found</html>"

    assert fetch_jma_area_boundaries.main() == 1

    assert not destination.exists()
