"""PBFファイルの読み取り（pyosmium）。osmiumへの依存をこのモジュールに閉じ込める。

pyosmium（requirements-batch.txt、web運用では未インストール）はこのモジュール以外から
importしない。取込バッチ本体（import_pbf.py）はこのモジュールを実行時にのみ読み込む。
"""

from collections.abc import Callable
from pathlib import Path

import osmium

# way1件ぶんの生データ（OverpassClient.get_ways_and_nodesのway要素と同じ形）と、
# そのwayが参照するノードのうち位置が判明しているものの座標（node_id -> (lat, lon)）。
WaySink = Callable[[dict, dict[int, tuple[float, float]]], None]


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
    def __init__(self, tag_filter: Callable[[dict[str, str]], bool], sink: WaySink):
        super().__init__()
        self._tag_filter = tag_filter
        self._sink = sink

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


def stream_ways(pbf_path: str | Path, tag_filter: Callable[[dict[str, str]], bool], sink: WaySink) -> None:
    """PBF内の全wayを1パスで読み、tag_filterを通ったwayをsinkへ流す（ブロッキング）。

    locations=Trueによりwayの参照ノードの位置がその場で解決される。ノード位置
    インデックスはflex_mem（メモリ上、抽出ファイルの規模に応じて自動選択）。
    国・大陸規模のPBFでメモリが不足する場合はdense_file_array等のディスクバック
    インデックスへの切り替えを検討する（docs/osm-pbf-import.md）。
    """
    handler = _WayHandler(tag_filter, sink)
    handler.apply_file(str(pbf_path), locations=True, idx="flex_mem")
