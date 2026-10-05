"""PBFファイルの読み取り（pyosmium）。osmiumへの依存をこのモジュールに閉じ込める。

pyosmium（requirements-batch.txt、web運用では未インストール）はこのモジュール以外から
importしない。呼び出し側はこのモジュールを実行時にのみ読み込む。
"""

from collections.abc import Callable
from pathlib import Path

import osmium

#: way1件ぶんの生データ（id・タグ・参照ノードid列）と、そのwayが参照するノードのうち
#: 位置が判明しているものの座標（node_id -> (lat, lon)）。
_WaySink = Callable[[dict, dict[int, tuple[float, float]]], None]

#: node1件ぶんの生データ（id・タグ・座標）。
_NodeSink = Callable[[dict], None]


class _WayHandler(osmium.SimpleHandler):
    def __init__(
        self,
        tag_filter: Callable[[dict[str, str]], bool],
        sink: _WaySink,
        node_sink: _NodeSink | None,
    ):
        super().__init__()
        self._tag_filter = tag_filter
        self._sink = sink
        self._node_sink = node_sink

    def way(self, w) -> None:
        tags = {t.k: t.v for t in w.tags}
        # ノード位置の解決前にタグでふるい落とす（wayの大半はhighway以外）。
        if not self._tag_filter(tags):
            return
        node_ids: list[int] = []
        coords: dict[int, tuple[float, float]] = {}
        for n in w.nodes:
            node_ids.append(n.ref)
            location = n.location
            # 抽出ファイルの境界付近では、wayが参照するノードがファイルに含まれず
            # 位置が解決できないことがある（invalid）。
            if location.valid():
                coords[n.ref] = (location.lat, location.lon)
        self._sink({"id": w.id, "tags": tags, "nodes": node_ids}, coords)

    def node(self, n) -> None:
        # タグ無しnode（大多数の形状点）はタグ辞書の構築自体を省略して早期リターンする。
        if self._node_sink is None or not n.tags:
            return
        tags = {t.k: t.v for t in n.tags}
        location = n.location
        if not location.valid():
            return
        self._node_sink({"id": n.id, "tags": tags, "lat": location.lat, "lon": location.lon})


def stream_ways(
    pbf_path: str | Path,
    tag_filter: Callable[[dict[str, str]], bool],
    sink: _WaySink,
    node_sink: _NodeSink | None = None,
) -> None:
    """PBF内の全way（・node_sink指定時はnodeも）を1パスで読み、tag_filterを
    通ったwayとタグを持つnodeをそれぞれのsinkへ流す（ブロッキング）。

    ノード位置インデックスはflex_mem（メモリ上）で、PBFの規模に対して十分なメモリが要る。
    """
    handler = _WayHandler(tag_filter, sink, node_sink)
    handler.apply_file(str(pbf_path), locations=True, idx="flex_mem")
