"""OSMの抽出ファイルの取得（scripts/fetch_osm_pbf.py）。

入口は`main`。配布元の応答と置き場だけを差し替え、何を取りに行くかは本物のプロファイルから導く。
見るのは、取込が開くファイルを取りに行くことと、落としたPBFをosmiumで開けたら取得済みとすること。

ここで見ないもの:
- 一時ファイル経由の取得・読めるものを落とし直さない・読めないものを退ける手順（`app/batch/common.py: fetch_verified`）
  → `test_fetch_accident_csv.py`
"""

import sys

import osmium
import pytest

from app.batch.source_adapters.osm_pbf import OsmWayRows
from app.batch.source_profile import load_source_profile
from scripts import fetch_osm_pbf


@pytest.fixture
def pbf_bytes(tmp_path) -> bytes:
    """osmiumが開ける最小のPBF（ノード1つ）。"""
    path = tmp_path / "tiny.osm.pbf"
    writer = osmium.SimpleWriter(str(path))
    writer.add_node(osmium.osm.mutable.Node(id=1, location=(139.7, 35.6)))
    writer.close()
    return path.read_bytes()


def test_default_profile_fetches_the_file_the_ingest_reads(tmp_path, monkeypatch, pbf_bytes, respx_mock):
    """プロファイルがファイル名を書いていなくても、取込が開くファイルを取りに行く。"""
    respx_mock.route().respond(content=pbf_bytes)
    store = tmp_path / "pbf"
    monkeypatch.setattr(fetch_osm_pbf, "DATA_DIR", store)
    monkeypatch.setattr(sys, "argv", ["fetch_osm_pbf.py"])

    assert fetch_osm_pbf.main() == 0

    ingested = {spec.rows.file for spec in load_source_profile(None).sources
                if isinstance(spec.rows, OsmWayRows)}
    assert ingested
    assert sorted(p.name for p in store.iterdir()) == sorted(ingested)
