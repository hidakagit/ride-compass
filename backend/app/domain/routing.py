"""Route Engine（仕様書33-34章）。

Road Graph（domain/graph.py）とEdge Cost（domain/evaluation.py）を使って、2点間の
最小コスト経路を探索する。探索アルゴリズム自体は独自実装せず、標準的なグラフ
アルゴリズムライブラリのDijkstra実装をそのまま利用する（仕様書34章「探索アルゴリズムを
独断で変更しない」「独自の経路探索アルゴリズムの実装はしない」の趣旨を踏まえ、
新規性のある独自アルゴリズムは開発しない）。当初はNetworkX（Python実装）を使っていたが、
改善計画T220（T12 Stage 2）で大規模グラフ（数万エッジ）向けにscipy.sparse.csgraph
（C実装のDijkstra）へ置き換えた。標準ライブラリの実装をそのまま使うだけで、
アルゴリズム自体の独自実装ではない点は変わらない。

Route Engineは、Costの中身（勾配がきつい、路面が悪い等）を一切知らない設計とする
（仕様書33章）。ここで扱うのはRoad Graphのトポロジーと、既に計算済みのEdge Costのみ。
"""

import math
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass

import numpy as np
import rustworkx as rx
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

from app.domain.evaluation import EdgeCostResult
from app.domain.geo import KM_PER_DEGREE_LATITUDE, haversine_distance_km
from app.domain.graph import RoadGraphLike
from app.domain.route import Coordinates


@dataclass
class SparseRoadGraph:
    """探索グラフのCSR（圧縮行格納）表現（改善計画T220、T12 Stage 2）。

    `RoadGraphEngine.trace_loop`が1リクエストにつき最大24回（3区間×8方位）呼ぶ
    Dijkstraを、scipy.sparse.csgraph（C実装）で高速に解くために使う。同一ノード間の
    並行Edgeは1本のみ保持する（cost最小のEdgeを採用。改善計画T363: 以前は
    `graph.edges`の反復順＝DBクエリの返却行順で後勝ちしていたが、行順序が実行の
    たびに変わりうる非決定性の原因だったため、行順序に依存しないcost比較へ改めた。
    `build_sparse_graph`のdocstring参照）。
    """

    matrix: csr_matrix
    node_id_to_index: dict[str, int]
    index_to_node_id: list[str]
    edge_id_by_index_pair: dict[tuple[int, int], str]


def build_sparse_graph(graph: RoadGraphLike, edge_costs: dict[str, EdgeCostResult]) -> SparseRoadGraph:
    """RoadGraphとEdge Costから`SparseRoadGraph`を構築する。Hard Constraintで
    除外されたEdge（`allowed=False`）やCostが算出できなかったEdge（`cost=None`）は
    含めない（仕様書29章：探索対象から除外する）。

    `scipy.sparse.coo_matrix`は同一(row, col)への重複エントリを合算してしまうため、
    疎行列を組む前にPython側のdictで(from_index, to_index)ごとに1本（cost最小のEdgeを
    採用）へ集約してから渡す。

    改善計画T363: 以前は「後から登場したEdgeで上書き」（`graph.edges`の反復順=辞書の
    挿入順=DBクエリの返却行順に依存）だったが、`road_edges`をbboxで問い合わせる
    SQL（`road_graph_repository.py: get_graph_in_bbox`/`get_graph_topology_in_bbox`）に
    `ORDER BY`が無く、かつ実測（都心規模で`Parallel Bitmap Heap Scan`が選ばれる）で
    同一クエリの返却行順が実行のたびに変わることを確認した。並行Edgeを持つ(from,to)
    ペアが実データに実在するため（dev DB実測484件）、「後勝ち」のままだと採用される
    Edgeが呼び出しのたびに非決定的に入れ替わり、そのEdgeが接続の要（橋・アンダーパス等）
    だった場合、出発点から先の到達性が同一条件のリクエスト間で成功/失敗を行き来する
    非決定的バグを引き起こしていた（8方位すべてが同時に"no path found"になる症状と一致）。
    行順序に依存しない決定的な結果にするため、単純な上書きではなくcostを比較し、
    より小さい方を採用する（同点なら先に登場した方を保持=変更しない）よう改めた。
    """
    node_ids = list(graph.nodes.keys())
    node_id_to_index = {node_id: i for i, node_id in enumerate(node_ids)}
    size = len(node_ids)

    best_by_pair: dict[tuple[int, int], tuple[float, str]] = {}
    for edge_id, edge in graph.edges.items():
        cost_result = edge_costs.get(edge_id)
        if cost_result is None or not cost_result.allowed or cost_result.cost is None:
            continue
        from_index = node_id_to_index.get(edge.from_node_id)
        to_index = node_id_to_index.get(edge.to_node_id)
        if from_index is None or to_index is None:
            continue
        pair = (from_index, to_index)
        existing = best_by_pair.get(pair)
        if existing is None or cost_result.cost < existing[0]:
            best_by_pair[pair] = (cost_result.cost, edge_id)

    if best_by_pair:
        rows, cols, weights = zip(
            *((u, v, weight) for (u, v), (weight, _edge_id) in best_by_pair.items())
        )
    else:
        rows, cols, weights = (), (), ()

    matrix = csr_matrix((np.asarray(weights, dtype=float), (rows, cols)), shape=(size, size))
    edge_id_by_index_pair = {pair: edge_id for pair, (_weight, edge_id) in best_by_pair.items()}
    return SparseRoadGraph(
        matrix=matrix,
        node_id_to_index=node_id_to_index,
        index_to_node_id=node_ids,
        edge_id_by_index_pair=edge_id_by_index_pair,
    )


def shortest_path_node_ids_sparse(
    sparse_graph: SparseRoadGraph, start_node_id: str, end_node_id: str
) -> list[str] | None:
    """start_node_idからend_node_idまでの最小コスト経路をNode ID列で返す。
    経路が存在しない（到達不能）場合、または始点・終点がgraph上に無い場合はNoneを返す。
    """
    if start_node_id == end_node_id:
        return [start_node_id] if start_node_id in sparse_graph.node_id_to_index else None

    start_index = sparse_graph.node_id_to_index.get(start_node_id)
    end_index = sparse_graph.node_id_to_index.get(end_node_id)
    if start_index is None or end_index is None:
        return None

    distances, predecessors = scipy_dijkstra(
        sparse_graph.matrix, directed=True, indices=start_index, return_predecessors=True
    )
    if not math.isfinite(distances[end_index]):
        return None

    path_indices = [end_index]
    current = end_index
    while current != start_index:
        current = predecessors[current]
        if current < 0:  # scipyの到達不能センチネル（負値）。理論上ここには来ないはず
            return None  # （distancesが有限だった時点で到達可能）だが安全側で扱う。
        path_indices.append(current)
    path_indices.reverse()
    return [sparse_graph.index_to_node_id[i] for i in path_indices]


def path_to_edge_ids_sparse(sparse_graph: SparseRoadGraph, path_node_ids: list[str]) -> list[str]:
    """Node ID列を、それらを結ぶDirected EdgeのID列へ変換する。"""
    return [
        sparse_graph.edge_id_by_index_pair[
            (sparse_graph.node_id_to_index[u], sparse_graph.node_id_to_index[v])
        ]
        for u, v in zip(path_node_ids, path_node_ids[1:])
    ]


@dataclass
class LazyRoadGraph:
    """探索グラフのrustworkx表現（改善計画T529、`docs/tasks/T529.md`）。

    `SparseRoadGraph`（scipy版）と異なり、Edgeコストを事前計算しない——トポロジのみを
    保持し、探索中に実際に訪れたEdgeに対してのみ`edge_cost_fn`が都度呼ばれる
    （lazy評価）。PoC実測（合成グリッドグラフ、王子実測相当のnodes=139,876
    edges=558,008）でA*は全Edgeの2.79%しか評価せずに済むことを確認済み——現行の
    `build_sparse_graph`（`evaluate_graph`でbbox全体のコストを事前に一括計算してから
    構築する）は、この無駄な事前計算そのものが`prepare_ms`の支配的コストになっている
    （T522実測、王子30km周回でcost_ms=18,105ms）。

    改善計画T536: Node/Edgeのpayloadはいずれも整数index（`add_nodes_from(range(n))`・
    `add_edge(u, v, edge_index)`）にしてある。rustworkxの`astar_shortest_path`は
    `goal_fn`/`edge_cost_fn`/`estimate_cost_fn`へノード・Edgeの**payload**（rustworkx内部の
    生indexではない）を渡す仕様のため、payload自体を「配列の添字として直接使える整数」に
    しておくことで、呼び出し元（`shortest_path_node_ids_lazy`の呼び出し元、
    `road_graph_engine.py`）は`cost_list.__getitem__`のような素のlistインデックスアクセスを
    そのままcost_fn/estimate_cost_fnとして渡せる——探索中に一切Pythonの関数フレームを
    作らずに済む（T522実測: 辞書キャッシュ経由のPythonコールバックがA* 24本で8.3〜17.7秒
    かかっていたが、素のlist.__getitem__に置き換えると0.37秒に短縮、docs/tasks/T536.md
    参照）。文字列edge_id/node_idは、経路確定後の変換（`path_to_edge_ids_lazy`・戻り値の
    Node ID列）でのみ使う。
    """

    py_graph: rx.PyDiGraph
    node_id_to_index: dict[str, int]
    index_to_node_id: list[str]
    # edge_index（py_graphのEdge payload、= 下記edge_idsの添字）→ edge_id。
    edge_ids: list[str]
    # (from_index, to_index) -> edge_index。並行Edge解消後の実際に採用されたペアのみ持つ。
    edge_index_by_node_pair: dict[tuple[int, int], int]


def build_lazy_road_graph(
    graph: RoadGraphLike, edge_cost_by_id: Mapping[str, float] | None = None
) -> LazyRoadGraph:
    """`graph`のトポロジからrustworkxの`PyDiGraph`を構築する（Hard Constraint自体は
    評価しない。除外は呼び出し元がcost=math.infで表現する）。

    改善計画T536: Node/Edge payloadは整数index（`LazyRoadGraph`のdocstring参照）。
    `edge_cost_by_id`（edge_id→コスト、省略可）を渡すと、並行Edge（同一Node間の複数Edge）は
    **cost最小のEdgeを採用**する（改善計画T363の元の意味論——コストが探索前に判明している
    T536設計では、事前一括計算だったT363当時と同じ比較が再び可能になる）。省略時
    （コストがまだ判明していない場面、主にテスト）は、従来どおりedge_idの昇順で先頭を
    採用する決定的な選択にフォールバックする。
    """
    node_ids = list(graph.nodes.keys())
    node_id_to_index = {node_id: i for i, node_id in enumerate(node_ids)}

    py_graph = rx.PyDiGraph()
    py_graph.add_nodes_from(range(len(node_ids)))

    # edge_idの昇順で処理する（複数の並行Edgeのうちどれを「先に登場した」とみなすかの
    # 決定的な基準、cost比較が同点の場合のタイブレークにも使う）。
    best_by_pair: dict[tuple[int, int], str] = {}
    best_cost_by_pair: dict[tuple[int, int], float] = {}
    for edge_id in sorted(graph.edges.keys()):
        edge = graph.edges[edge_id]
        from_index = node_id_to_index.get(edge.from_node_id)
        to_index = node_id_to_index.get(edge.to_node_id)
        if from_index is None or to_index is None:
            continue
        pair = (from_index, to_index)
        if edge_cost_by_id is None:
            if pair not in best_by_pair:
                best_by_pair[pair] = edge_id
            continue
        cost = edge_cost_by_id.get(edge_id, math.inf)
        existing_cost = best_cost_by_pair.get(pair)
        if existing_cost is None or cost < existing_cost:
            best_cost_by_pair[pair] = cost
            best_by_pair[pair] = edge_id

    edge_ids: list[str] = []
    edge_index_by_node_pair: dict[tuple[int, int], int] = {}
    for pair, edge_id in best_by_pair.items():
        edge_index = len(edge_ids)
        py_graph.add_edge(pair[0], pair[1], edge_index)
        edge_ids.append(edge_id)
        edge_index_by_node_pair[pair] = edge_index

    return LazyRoadGraph(
        py_graph=py_graph,
        node_id_to_index=node_id_to_index,
        index_to_node_id=node_ids,
        edge_ids=edge_ids,
        edge_index_by_node_pair=edge_index_by_node_pair,
    )


def shortest_path_node_ids_lazy(
    lazy_graph: LazyRoadGraph,
    start_node_id: str,
    end_node_id: str,
    edge_cost_fn: Callable[[int], float],
    estimate_cost_fn: Callable[[int], float],
) -> list[str] | None:
    """`start_node_id`から`end_node_id`までの最小コスト経路をNode ID列で返す
    （改善計画T529、`shortest_path_node_ids_sparse`のlazy評価版）。

    改善計画T536: `edge_cost_fn`/`estimate_cost_fn`は、`LazyRoadGraph`のNode/Edge payload
    である**整数index**（Edge index/Node index、それぞれ`lazy_graph.edge_ids`/
    `lazy_graph.index_to_node_id`の添字）を受け取る（旧: edge_id/node_id文字列）。
    典型的には呼び出し元が`cost_list.__getitem__`のような素のlistインデックスアクセスを
    そのまま渡す（探索中にPythonの関数フレームを作らない、`LazyRoadGraph`のdocstring
    参照）。Hard Constraintで除外されるEdgeは`edge_cost_fn`が`math.inf`を返すことで
    通行不能を表現する（`build_sparse_graph`がグラフ構築時にEdgeそのものを除外するのと
    異なり、lazy評価ではコストが分かるまで除外できないため——ただしT536以降はコストが
    探索前に判明しているため、この除外自体は`build_lazy_road_graph`より前の時点で
    コスト配列へ焼き込まれている）。`estimate_cost_fn`は目的地までの下界推定
    （admissibleヒューリスティック、直線距離）を返す。経路が存在しない場合はNoneを返す。
    """
    if start_node_id == end_node_id:
        return [start_node_id] if start_node_id in lazy_graph.node_id_to_index else None

    start_index = lazy_graph.node_id_to_index.get(start_node_id)
    end_index = lazy_graph.node_id_to_index.get(end_node_id)
    if start_index is None or end_index is None:
        return None

    def goal_fn(node_index: int) -> bool:
        return node_index == end_index

    try:
        path_indices = rx.astar_shortest_path(
            lazy_graph.py_graph, start_index, goal_fn, edge_cost_fn, estimate_cost_fn
        )
    except rx.NoPathFound:
        return None
    if len(path_indices) == 0:
        return None

    # rustworkxは`math.inf`を「通行不能」ではなく「非常に高いが有効なコスト」として
    # 扱うため、他に到達手段が無ければinfコストのEdgeを含む経路でもそのまま返してくる
    # （実測で確認、他の有限コスト経路が存在する限りはそちらが優先されるためこの
    # チェックはfinite経路が本当に存在しない場合にのみNoneへ倒す）。経路確定後に
    # 合計コストを検算し、無限大ならHard Constraintで実質到達不能だったとみなす。
    total_cost = 0.0
    for u, v in zip(path_indices, path_indices[1:]):
        edge_index = lazy_graph.edge_index_by_node_pair[(u, v)]
        total_cost += edge_cost_fn(edge_index)
    if not math.isfinite(total_cost):
        return None

    return [lazy_graph.index_to_node_id[i] for i in path_indices]


def path_to_edge_ids_lazy(lazy_graph: LazyRoadGraph, path_node_ids: list[str]) -> list[str]:
    """Node ID列を、それらを結ぶEdgeのID列へ変換する（`path_to_edge_ids_sparse`と同じ形）。"""
    return [
        lazy_graph.edge_ids[
            lazy_graph.edge_index_by_node_pair[
                (lazy_graph.node_id_to_index[u], lazy_graph.node_id_to_index[v])
            ]
        ]
        for u, v in zip(path_node_ids, path_node_ids[1:])
    ]


def routable_node_ids(sparse_graph: SparseRoadGraph) -> set[str]:
    """`sparse_graph`上で最低1本のEdge（発/着どちらでも可）を持つNode ID集合を返す
    （改善計画T256）。

    `build_sparse_graph`はHard Constraintで除外されたEdgeを含めないため、幹線道路
    （`highway=trunk`等）にしか接続していないNodeは、除外後のグラフ上では次数0の
    孤立点になる。孤立Nodeを最近傍探索の候補に含めたまま`find_nearest_node_indexed`を
    呼ぶと、地理的には最も近くても実際には出発・経由不能なNodeが選ばれ、そこから先の
    Dijkstra探索が常に失敗する（主要駅が国道の交差点に直接面している新宿駅・渋谷駅等で
    実機確認、8方位すべてが`no path found`になる）。`build_node_spatial_index`へ
    この集合を渡すことで、索引の候補を「実際に経路探索可能なNode」だけに絞れる。
    """
    rows, cols = sparse_graph.matrix.nonzero()
    connected_indices = set(rows.tolist()) | set(cols.tolist())
    return {sparse_graph.index_to_node_id[i] for i in connected_indices}


@dataclass
class NodeSpatialIndex:
    """緯度経度の総当たり線形探索を高速化するグリッドバケット索引
    （改善計画T219、T12 Stage 1）。

    `RoadGraphEngine`は1リクエストの同じRoad Graphに対し最大17回、指定地点に最も
    近いNodeを探す呼び出しを行う（`prepare`で1回・`trace_loop`で方位ごとに2回）。
    ノード数が増えるとこの繰り返しが線形探索×17回ぶん積み上がるため、索引を1回だけ
    構築して使い回す。新規外部ライブラリ（scipy.spatial.cKDTree等）は導入せず、既定の
    `dict`だけで組めるグリッドバケット方式にする（PostGIS空間インデックスが無い
    構成でも同じロジックで動く）。
    """

    graph: RoadGraphLike
    cell_size_deg: float
    buckets: dict[tuple[int, int], list[str]]


# 1セルの一辺（度）。緯度で約1.1km四方（東京付近では経度方向はcos(35°)倍で約0.9km四方）。
# Road Graph構築bbox（起点半径+マージン、数km〜数十km四方）に対して、1セルあたり
# 概ね数十〜数百ノード程度に収まる粒度を狙った経験的な値（探索半径拡張のコストと
# バケット数のトレードオフ、実測は不要——グリッドバケット方式は極端に不適切な値
# でなければ正しく動作する。将来チューニングする場合はbenchmarks/bench_nearest_node.py
# へ計測を追加する）。
DEFAULT_NODE_INDEX_CELL_SIZE_DEG = 0.01


def build_node_spatial_index(
    graph: RoadGraphLike,
    cell_size_deg: float = DEFAULT_NODE_INDEX_CELL_SIZE_DEG,
    node_ids: Collection[str] | None = None,
) -> NodeSpatialIndex:
    """`graph.nodes`からグリッドバケット索引を構築する。ノードが1つも無くても
    空のbucketsを持つ索引を返す（呼び出し元は`find_nearest_node_indexed`が
    その場合Noneを返すことで区別すればよい）。

    `node_ids`省略時は`graph.nodes`全件を対象にする。指定時はその集合に含まれるNode
    のみを索引の候補にする（改善計画T256: `routable_node_ids`と組み合わせ、Hard
    Constraint通過後に孤立するNodeを最近傍探索の候補から除外するために使う）。
    """
    ids = graph.nodes.keys() if node_ids is None else node_ids
    buckets: dict[tuple[int, int], list[str]] = {}
    for node_id in ids:
        node = graph.nodes[node_id]
        key = (math.floor(node.latitude / cell_size_deg), math.floor(node.longitude / cell_size_deg))
        buckets.setdefault(key, []).append(node_id)
    return NodeSpatialIndex(graph=graph, cell_size_deg=cell_size_deg, buckets=buckets)


def find_nearest_node_indexed(index: NodeSpatialIndex, point: Coordinates) -> str | None:
    """`build_node_spatial_index`が作った索引を使い、指定地点に最も近いNodeを総当たり
    より高速に探す。

    グリッドバケットを中心セルから外側へリング状に広げながら探索し、既知の最近傍距離が
    「まだ調べていない外側リングのどの点までの距離よりも近い」と保証できた時点で打ち切る
    （標準的なグリッド最近傍探索の安全な停止条件）。安全マージンには経度方向（cos補正込み、
    高緯度ほど1度あたりの物理距離が短くなる）の1度あたり距離を使う——経度方向のセルは
    緯度方向より常に狭い（赤道上でのみ等しい）ため、緯度方向の距離をそのまま安全マージンに
    使うと、実際にはまだ調べていない経度方向のセルの方が近い可能性があるのに打ち切って
    しまう（改善計画T463で訂正。訂正前のdocstringは逆の主張をしていた）。
    """
    if not index.graph.nodes:
        return None

    cell_lat = math.floor(point.latitude / index.cell_size_deg)
    cell_lon = math.floor(point.longitude / index.cell_size_deg)
    # 経度方向1度あたりの物理距離（cos補正込み）を安全マージンに使う——2方向のうち
    # 常に短い（＝より保守的な）方でなければ、リング内に未探索の近い点が残りうる。
    longitude_cos_factor = math.cos(math.radians(point.latitude))
    cell_size_km_lower_bound = index.cell_size_deg * KM_PER_DEGREE_LATITUDE * longitude_cos_factor

    nearest_node_id: str | None = None
    nearest_distance: float | None = None
    radius = 0
    max_radius = max(len(index.buckets), 1) + 1  # 理論上到達しない安全弁（無限ループ防止）
    while radius <= max_radius:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue  # 内側のリングは前回までのループで調べ済み
                for node_id in index.buckets.get((cell_lat + dx, cell_lon + dy), ()):
                    node = index.graph.nodes[node_id]
                    # 改善計画T262: nodeは既にlatitude/longitudeを持つ（NodeLike）ため、
                    # Coordinatesへ包み直さない。
                    distance = haversine_distance_km(point, node)
                    if nearest_distance is None or distance < nearest_distance:
                        nearest_distance = distance
                        nearest_node_id = node_id
        if nearest_distance is not None and radius * cell_size_km_lower_bound >= nearest_distance:
            break
        radius += 1
    return nearest_node_id


def concat_node_paths(paths: list[list[str]]) -> list[str]:
    """複数区間（例: 起点→経由地A、経由地A→経由地B、...）のNode ID列を1本に連結する。
    隣接する区間の境界ノード（前区間の終端＝次区間の始端）が重複しないようにする。
    """
    if not paths:
        return []
    combined = list(paths[0])
    for path in paths[1:]:
        combined.extend(path[1:])
    return combined
