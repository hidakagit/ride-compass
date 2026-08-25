"""pbf_source.py（改善計画T331）の単体テスト。

pyosmiumへの依存をこのモジュール1つに閉じ込める設計（モジュールdocstring参照）のため、
ここでの取りこぼしはOSMデータのサイレントな欠損に直結する。実PBFバイナリをosmiumの
SimpleWriterでその場生成し、read_header/stream_waysの入出力契約——特に
「wayのnode_ids配列は位置未解決でも欠けない」「タグ無しnode/node_tag_filter/
node_sink省略時の扱い」を検証する。

requirements-batch.txtのosmiumパッケージが要る（webランタイムには不要、
docs/osm-pbf-import.md参照）。
"""

import osmium
import pytest

from app.batch.pbf_source import read_header, stream_ways


def _write_pbf(path, nodes=(), ways=(), timestamp=None, box=None):
    """テスト用PBFをその場生成する。

    nodes: (id, lat, lon, tags)のタプル列。ways: (id, node_ids, tags)のタプル列。
    node_idsにnodesへ含めていないidを混ぜると、位置未解決の参照を再現できる
    （抽出ファイル境界付近で実際に起きるケースと同じ）。
    """
    header = osmium.io.Header()
    if timestamp is not None:
        header.set("osmosis_replication_timestamp", timestamp)
    if box is not None:
        min_lat, min_lon, max_lat, max_lon = box
        header.add_box(osmium.osm.Box(min_lon, min_lat, max_lon, max_lat))

    writer = osmium.SimpleWriter(str(path), header=header)
    try:
        for node_id, lat, lon, tags in nodes:
            writer.add_node(osmium.osm.mutable.Node(id=node_id, location=(lon, lat), tags=tags or {}))
        for way_id, node_ids, tags in ways:
            writer.add_way(osmium.osm.mutable.Way(id=way_id, nodes=list(node_ids), tags=tags or {}))
    finally:
        writer.close()


class TestReadHeader:
    def test_returns_timestamp_and_bbox_when_present(self, tmp_path):
        path = tmp_path / "with_header.osm.pbf"
        _write_pbf(
            path,
            nodes=[(1, 35.0, 139.0, {})],
            timestamp="2026-01-01T00:00:00Z",
            box=(35.0, 139.0, 35.01, 139.01),
        )
        timestamp, bbox = read_header(path)
        assert timestamp == "2026-01-01T00:00:00Z"
        assert bbox == (35.0, 139.0, 35.01, 139.01)

    def test_returns_none_none_when_header_has_neither(self, tmp_path):
        path = tmp_path / "no_header.osm.pbf"
        _write_pbf(path, nodes=[(1, 35.0, 139.0, {})])
        timestamp, bbox = read_header(path)
        assert timestamp is None
        assert bbox is None

    def test_accepts_str_path(self, tmp_path):
        path = tmp_path / "str_path.osm.pbf"
        _write_pbf(path, nodes=[(1, 35.0, 139.0, {})])
        timestamp, bbox = read_header(str(path))
        assert timestamp is None
        assert bbox is None


class TestStreamWays:
    def test_tag_filter_excludes_non_matching_ways(self, tmp_path):
        path = tmp_path / "ways.osm.pbf"
        _write_pbf(
            path,
            nodes=[(1, 35.0, 139.0, {}), (2, 35.001, 139.001, {})],
            ways=[
                (1, [1, 2], {"highway": "residential"}),
                (2, [1, 2], {"landuse": "forest"}),
            ],
        )
        seen_way_ids = []
        stream_ways(path, lambda tags: "highway" in tags, lambda way, coords: seen_way_ids.append(way["id"]))
        assert seen_way_ids == [1]

    def test_sink_receives_full_way_fields(self, tmp_path):
        path = tmp_path / "way_fields.osm.pbf"
        _write_pbf(
            path,
            nodes=[(1, 35.0, 139.0, {}), (2, 35.001, 139.001, {})],
            ways=[(10, [1, 2], {"highway": "residential", "surface": "asphalt"})],
        )
        received = []
        stream_ways(path, lambda tags: True, lambda way, coords: received.append(way))
        assert received == [
            {"id": 10, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}
        ]

    def test_node_ids_kept_complete_even_when_location_unresolved(self, tmp_path):
        # way が参照するnode 2をファイルへ書かない → 位置未解決になる
        # （「node_coordsに無いノードは座標なし」という契約をここで検証する。
        # node_ids配列自体が欠けるとサイレントなデータ欠損になるため、そうならないことが要点）。
        path = tmp_path / "dangling_ref.osm.pbf"
        _write_pbf(path, nodes=[(1, 35.0, 139.0, {})], ways=[(1, [1, 2], {"highway": "residential"})])
        received = []
        stream_ways(path, lambda tags: True, lambda way, coords: received.append((way, coords)))
        (way, coords), = received
        assert way["nodes"] == [1, 2]  # 未解決でもnode_ids配列は欠けない
        assert coords == {1: (35.0, 139.0)}  # 座標は解決できたノードのみ

    def test_node_sink_not_called_when_omitted(self, tmp_path):
        path = tmp_path / "no_node_sink.osm.pbf"
        _write_pbf(
            path,
            nodes=[(1, 35.0, 139.0, {"highway": "traffic_signals"})],
            ways=[(1, [1], {"highway": "residential"})],
        )
        # node_sink省略時は例外にならず、単に何も起きないことを確認する
        # （measure_tag_coverage.py等、way取込しか使わない既存呼び出しに影響しないという
        # モジュールdocstringの記述の検証）。
        stream_ways(path, lambda tags: True, lambda way, coords: None)

    def test_node_sink_receives_matching_tagged_nodes(self, tmp_path):
        path = tmp_path / "node_sink.osm.pbf"
        _write_pbf(
            path,
            nodes=[
                (1, 35.0, 139.0, {"highway": "traffic_signals"}),
                (2, 35.001, 139.001, {}),  # タグ無し → node_tag_filterに渡らず除外
                (3, 35.002, 139.002, {"highway": "crossing"}),  # filterで除外
            ],
            ways=[(1, [1, 2, 3], {"highway": "residential"})],
        )
        received_nodes = []
        stream_ways(
            path,
            lambda tags: True,
            lambda way, coords: None,
            node_tag_filter=lambda tags: tags.get("highway") == "traffic_signals",
            node_sink=lambda node: received_nodes.append(node),
        )
        assert [n["id"] for n in received_nodes] == [1]
        assert received_nodes[0]["tags"] == {"highway": "traffic_signals"}
        assert received_nodes[0]["lat"] == pytest.approx(35.0)
        assert received_nodes[0]["lon"] == pytest.approx(139.0)

    def test_untagged_nodes_never_reach_node_tag_filter(self, tmp_path):
        # タグ無しnode（大多数の形状点）は辞書構築自体を省く早期リターンパス
        # （モジュールdocstring参照）。node_tag_filterが一度も呼ばれないことで検証する。
        path = tmp_path / "untagged_nodes.osm.pbf"
        _write_pbf(path, nodes=[(1, 35.0, 139.0, {})], ways=[(1, [1], {"highway": "residential"})])
        filter_calls = []

        def node_tag_filter(tags):
            filter_calls.append(tags)
            return True

        stream_ways(
            path,
            lambda tags: True,
            lambda way, coords: None,
            node_tag_filter=node_tag_filter,
            node_sink=lambda node: None,
        )
        assert filter_calls == []

    def test_multiple_matching_ways_all_reach_sink_in_order(self, tmp_path):
        path = tmp_path / "multi_ways.osm.pbf"
        _write_pbf(
            path,
            nodes=[(1, 35.0, 139.0, {}), (2, 35.001, 139.001, {}), (3, 35.002, 139.002, {})],
            ways=[
                (1, [1, 2], {"highway": "residential"}),
                (2, [2, 3], {"highway": "primary"}),
            ],
        )
        seen_way_ids = []
        stream_ways(path, lambda tags: True, lambda way, coords: seen_way_ids.append(way["id"]))
        assert seen_way_ids == [1, 2]
