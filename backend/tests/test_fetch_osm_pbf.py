"""OSMの抽出ファイルの取得（scripts/fetch_osm_pbf.py）。

配布元の応答と置き場だけを差し替え、何を取りに行くかは本物のプロファイルから導く。
"""

import sys

import osmium
import pytest

from app.batch.source_adapters.osm_pbf import OsmWayRows
from app.batch.source_profile import load_source_profile
from scripts import fetch_osm_pbf
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


@pytest.fixture
def pbf_bytes(tmp_path) -> bytes:
    """osmiumが開ける最小のPBF（ノード1つ）。"""
    path = tmp_path / "tiny.osm.pbf"
    writer = osmium.SimpleWriter(str(path))
    writer.add_node(osmium.osm.mutable.Node(id=1, location=(139.7, 35.6)))
    writer.close()
    return path.read_bytes()


def test_default_profile_fetches_the_file_the_ingest_reads(tmp_path, monkeypatch, pbf_bytes):
    """プロファイルがファイル名を書いていなくても、取込が開くファイルを取りに行く。"""
    calls: list[str] = []

    def fake_stream(_method, url, **_kwargs):
        calls.append(url)
        return _FakeResponse(pbf_bytes)

    store = tmp_path / "pbf"
    monkeypatch.setattr(fetch_osm_pbf.httpx, "stream", bound(fetch_osm_pbf.httpx.stream, fake_stream))
    monkeypatch.setattr(fetch_osm_pbf, "DATA_DIR", store)
    monkeypatch.setattr(sys, "argv", ["fetch_osm_pbf.py"])

    assert fetch_osm_pbf.main() == 0

    ingested = {spec.rows.file for spec in load_source_profile().sources
                if isinstance(spec.rows, OsmWayRows)}
    assert ingested
    assert calls == [fetch_osm_pbf.PBF_URL.format(name=name) for name in sorted(ingested)]
    assert sorted(p.name for p in store.iterdir()) == sorted(ingested)
