"""PBFファイルの読み取り（pyosmium）。osmiumへの依存をこのモジュールに閉じ込める。

pyosmium（requirements-batch.txt、web運用では未インストール）はこのモジュール以外から
importしない。取込バッチ本体（import_pbf.py）はこのモジュールを実行時にのみ読み込む。
"""

from collections.abc import Callable
from pathlib import Path

import osmium

# way1件ぶんの生データ（osm_adapter.py: osm_way_to_way_specが受け取る形と同じ）と、
# そのwayが参照するノードのうち位置が判明しているものの座標（node_id -> (lat, lon)）。
WaySink = Callable[[dict, dict[int, tuple[float, float]]], None]

# node1件ぶんの生データ（osm_adapter.py: osm_node_to_poi_specが受け取る形と同じ）。
# 静的道路属性P1（信号・横断歩道・一時停止・踏切のnode取込）。
NodeSink = Callable[[dict], None]


def read_header(pbf_path: str | Path) -> tuple[str | None, tuple[float, float, float, float] | None]:
    """PBFヘッダから(osmosis_replication_timestamp, bbox)を読む。

    bboxは(min_lat, min_lon, max_lat, max_lon)。どちらも無ければNone。
    """
    reader = osmium.io.Reader(str(pbf_path))
    try:
        header = reader.header()
        timestamp = header.get("osmosis_replication_timestamp", "") or None
        box = header.box()
        bbox = None
        if box is not None and box.valid():
            bbox = (box.bottom_left.lat, box.bottom_left.lon, box.top_right.lat, box.top_right.lon)
        return timestamp, bbox
    finally:
        reader.close()


class _WayHandler(osmium.SimpleHandler):
    def __init__(
        self,
        tag_filter: Callable[[dict[str, str]], bool],
        sink: WaySink,
        node_tag_filter: Callable[[dict[str, str]], bool] | None = None,
        node_sink: NodeSink | None = None,
    ):
        super().__init__()
        self._tag_filter = tag_filter
        self._sink = sink
        self._node_tag_filter = node_tag_filter
        self._node_sink = node_sink

    def way(self, w) -> None:
        tags = {t.k: t.v for t in w.tags}
        # ノード位置の解決前にタグでふるい落とす（Tokyo抽出でwayの大半はhighway以外）。
        if not self._tag_filter(tags):
            return
        node_ids: list[int] = []
        coords: dict[int, tuple[float, float]] = {}
        for n in w.nodes:
            node_ids.append(n.ref)
            location = n.location
            # 抽出ファイルの境界付近では、wayが参照するノードがファイルに含まれず
            # 位置が解決できないことがある（invalid）。Overpassランタイム経路の
            # 「node_coordsに無いノードは座標なし」と同じ扱いにする。
            if location.valid():
                coords[n.ref] = (location.lat, location.lon)
        self._sink({"id": w.id, "tags": tags, "nodes": node_ids}, coords)

    def node(self, n) -> None:
        # 静的道路属性P1（信号・横断歩道・一時停止・踏切のnode取込）。node_sink未指定時は
        # 何もしない（measure_tag_coverage.py等、way取込しか使わない既存呼び出しに影響しない）。
        # タグ無しnode（大多数の形状点）はタグ辞書構築自体を省略して早期リターンする。
        if self._node_sink is None or not n.tags:
            return
        tags = {t.k: t.v for t in n.tags}
        if not self._node_tag_filter(tags):
            return
        location = n.location
        if not location.valid():
            return
        # timestampはOSM要素の最終編集日時（tz-aware datetime）。取込パイプライン本体は
        # 未参照（POISpecへは渡さない）だが、measure_poi_freshness.py（T101検証）が
        # check_date/survey:dateタグ未設定な要素の鮮度代理指標として使う。
        self._node_sink(
            {"id": n.id, "tags": tags, "lat": location.lat, "lon": location.lon, "timestamp": n.timestamp}
        )


def stream_ways(
    pbf_path: str | Path,
    tag_filter: Callable[[dict[str, str]], bool],
    sink: WaySink,
    node_tag_filter: Callable[[dict[str, str]], bool] | None = None,
    node_sink: NodeSink | None = None,
) -> None:
    """PBF内の全way（・node_sink指定時はnodeも）を1パスで読み、tag_filter/node_tag_filterを
    通った要素をそれぞれのsinkへ流す（ブロッキング）。

    locations=Trueによりwayの参照ノードの位置がその場で解決される。ノード位置
    インデックスはflex_mem（メモリ上、抽出ファイルの規模に応じて自動選択）。
    国・大陸規模のPBFでメモリが不足する場合はdense_file_array等のディスクバック
    インデックスへの切り替えを検討する（docs/osm-pbf-import.md）。

    node_sinkは静的道路属性P1（信号・横断歩道・一時停止・踏切のnode取込）で使う。
    wayとnodeを同じ1パスで処理する（PBFの再読み込みを避ける）。
    """
    handler = _WayHandler(tag_filter, sink, node_tag_filter, node_sink)
    handler.apply_file(str(pbf_path), locations=True, idx="flex_mem")
