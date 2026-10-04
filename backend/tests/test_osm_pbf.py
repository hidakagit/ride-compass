"""`batch/source_adapters/osm_pbf.py`——OSMのPBFのアダプタ。

入口はノードのソースの取込（`read_osm_nodes`）と、wayの条件の型（`OsmWayRows`）。ノードは、本物のプロファイル
（`source_profile.yaml`）で手で書いたOSMのファイルを読む。差し替えるのは読むファイルの置き場だけ。
見るのは、ノードのソースが採る点（道の頂点・道の外の補給・休憩の点と面）と、道の種別を含まない条件を断ること。
補給・休憩かの判定（`domain/traffic.py: has_supply_poi_tag`）の空白・大文字の揃えと、何を売るかによらない自販機も、
ほかに通すテストが無いのでここで通す。

ここで見ないもの:
- wayのソースの取込（`read_osm_ways`）→ どのテストも通さない（派生の段のテストは`tests/source_ingest.py`で
  アダプタを差し替えて入れる）
"""

import dataclasses
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest
import shapely
from shapely.geometry import Polygon

from app.batch.source_adapters import osm_pbf
from app.batch.source_adapters.osm_pbf import OsmWayRows
from app.batch.source_profile import SourceProfileError, load_source_profile

BASE_LAT, BASE_LON = 35.69, 139.70

#: ノード → (緯度の差, 経度の差, タグ)。
NODES: dict[int, tuple[float, float, dict[str, str]]] = {
    # 採る道の頂点。タグの無い頂点も、補給・休憩のタグを持つ頂点も採る。
    1: (0.0, 0.0, {}),
    3: (0.0, 0.002, {"shop": "convenience"}),
    # 採らない道（自転車の通れない歩道）の頂点。
    4: (0.001, 0.0, {}),
    5: (0.001, 0.001, {}),
    # 道の頂点でない点。
    10: (0.0005, 0.0005, {"shop": "convenience"}),
    11: (0.0005, 0.0006, {"amenity": "vending_machine", "vending": "cigarettes"}),
    12: (0.0005, 0.0007, {"shop": "bakery"}),
    13: (0.0005, 0.0008, {"amenity": " Toilets "}),
    14: (5.0, 0.0, {"shop": "convenience"}),
    # 面で描かれたコンビニの輪郭。
    20: (-0.001, 0.0, {}),
    21: (-0.001, 0.0004, {}),
    22: (-0.0014, 0.0004, {}),
    23: (-0.0014, 0.0, {}),
}

#: way → (ノードの並び, タグ)。
WAYS: dict[int, tuple[list[int], dict[str, str]]] = {
    1: ([1, 3], {"highway": "residential"}),
    2: ([4, 5], {"highway": "footway"}),
    3: ([20, 21, 22, 23, 20], {"building": "yes", "shop": "convenience", "name": "店"}),
}


def _tags_xml(tags: dict[str, str]) -> str:
    return "".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())


def _refs_xml(node_ids: list[int]) -> str:
    return "".join(f'<nd ref="{n}"/>' for n in node_ids)


def _write_osm(path: Path) -> None:
    nodes = "".join(
        f'<node id="{node_id}" version="1" lat="{BASE_LAT + dlat}" lon="{BASE_LON + dlon}">{_tags_xml(tags)}</node>'
        for node_id, (dlat, dlon, tags) in NODES.items())
    ways = "".join(
        f'<way id="{way_id}" version="1">{_refs_xml(node_ids)}{_tags_xml(tags)}</way>'
        for way_id, (node_ids, tags) in WAYS.items())
    path.write_text(f'<?xml version="1.0" encoding="UTF-8"?><osm version="0.6">{nodes}{ways}</osm>',
                    encoding="utf-8")


async def _read(tmp_path: Path, monkeypatch) -> dict[str, tuple[shapely.Geometry, dict[str, str]]]:
    _write_osm(tmp_path / "scene.osm")
    monkeypatch.setattr(osm_pbf, "DATA_DIR", tmp_path)
    profile = load_source_profile(None)
    sources = tuple(
        dataclasses.replace(spec, rows=dataclasses.replace(spec.rows, file="scene.osm"))
        if spec.name == "osm_way" else spec
        for spec in profile.sources)
    profile = dataclasses.replace(profile, sources=sources)
    records = [r async for r in osm_pbf.read_osm_nodes(profile.source("osm_node"), profile, {})]
    keys = [r.natural_key for r in records]
    assert len(keys) == len(set(keys))
    return {r.natural_key: (shapely.from_wkb(r.geom_wkb), r.attrs) for r in records}


async def test_road_vertices_and_supply_points_off_the_road_are_taken(tmp_path, monkeypatch):
    """道の頂点に加え、道から離れた補給・休憩の点を採る。範囲の外と、補給・休憩でない点は採らない。"""
    taken = await _read(tmp_path, monkeypatch)

    assert set(taken) == {"1", "3", "10", "11", "13", "-3"}
    assert taken["10"][1] == {"shop": "convenience"}


async def test_supply_area_becomes_one_point_inside_it_keyed_by_the_negated_way_id(tmp_path, monkeypatch):
    """面で描かれた施設は、面の内側の1点として、wayのタグを持って入る。"""
    taken = await _read(tmp_path, monkeypatch)

    point, tags = taken["-3"]
    outline = Polygon([(BASE_LON + NODES[n][1], BASE_LAT + NODES[n][0]) for n in WAYS[3][0]])
    assert outline.contains(point)
    assert tags == WAYS[3][1]


def test_a_way_condition_without_road_kind_is_refused():
    """種別を問わない条件は種別の無い道を採りうるので、取込を始める前に止める。"""
    with pytest.raises(SourceProfileError, match="highway を含む必要があります.*'bicycle'"):
        OsmWayRows(any_of=[{"highway": ["cycleway"]}, {"bicycle": ["designated"]}])
