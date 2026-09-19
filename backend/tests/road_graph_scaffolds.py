"""PostGISのテストが共有する、最小のRoad Graphの形。

同じ1本道・同じ交差点を各ファイルが組み直していたぶんを1箇所へ寄せたもの。**DBは触らない**
——保存・commit・事前集計のどれが要るかはテストごとに違い、そこを隠すと「何を用意した状態で
確かめているのか」が読めなくなる。座標は`road_nodes`の次数集計・距離判定が同じ前提で動く
よう、寄せた側で固定する。
"""

from app.domain.graph import RoadGraph, WaySpec, build_road_graph

#: 近接する2点（1本道の両端）。距離判定（事故の帰属半径30m等）が成り立つ間隔。
NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)
#: 上の2点から十分離れた2点（別のwayの端点。近接判定へ混ざらない）。
NODE3 = (35.750, 139.750)
NODE4 = (35.751, 139.751)


def single_way_spec() -> tuple[WaySpec, dict[int, tuple[float, float]]]:
    """NODE1-NODE2を結ぶ1本のway（生wayとして保存する側が使う）。"""
    return WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential"), {1: NODE1, 2: NODE2}


def single_way_graph() -> RoadGraph:
    """NODE1-NODE2の1本道（双方向で2 Edge）。"""
    way, nodes = single_way_spec()
    return build_road_graph([way], nodes, graph_version="v1")


def three_way_junction_spec(
    node3=NODE3, node4=NODE4
) -> tuple[list[WaySpec], dict[int, tuple[float, float]]]:
    """NODE2へ3本のwayが集まる交差点の生way（生wayとして保存する側が使う）。"""
    ways = [
        WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential"),
        WaySpec(osm_way_id=101, node_ids=[2, 3], highway="residential"),
        WaySpec(osm_way_id=102, node_ids=[2, 4], highway="residential"),
    ]
    return ways, {1: NODE1, 2: NODE2, 3: node3, 4: node4}


def three_way_junction_graph(node3=NODE3, node4=NODE4) -> RoadGraph:
    """NODE2へ3本のwayが集まる交差点（NODE2の次数3、端点3つは次数1）。"""
    ways, nodes = three_way_junction_spec(node3, node4)
    return build_road_graph(ways, nodes, graph_version="v1")


async def save_ways_and_graph(repository, ways, nodes, graph_version: str = "v1") -> RoadGraph:
    """生wayを永続化してから、その派生のグラフを保存する（本番と同じ順）。

    区間は`osm_raw_ways`の派生行（`road_edges.osm_way_id`がNOT NULL + FK）のため、
    wayを入れずに`save_graph`を呼ぶ状態は本番では作れない。
    """
    await repository.save_raw_ways(ways, nodes)
    graph = build_road_graph(ways, nodes, graph_version=graph_version)
    await repository.save_graph(graph)
    return graph
