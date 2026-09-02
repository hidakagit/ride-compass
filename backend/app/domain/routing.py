"""Route Engine（仕様書33-34章）。

Road Graph（domain/graph.py）とEdge Cost（domain/evaluation.py）を使って、2点間の
最小コスト経路を探索する。探索アルゴリズム自体は独自実装せず、標準的なグラフ
アルゴリズムライブラリの実装をそのまま利用する（仕様書34章「探索アルゴリズムを
独断で変更しない」「独自の経路探索アルゴリズムの実装はしない」の趣旨を踏まえ、
新規性のある独自アルゴリズムは開発しない）。当初はNetworkX（Python実装）、改善計画T220で
scipy.sparse.csgraph（C実装のDijkstra）、改善計画T529→T536でrustworkx（C実装のA*、
Node/Edge payloadを整数indexにしてPythonコールバックを探索中に作らない）へ移り、
2点間探索は現在rustworkxのA*（`shortest_path_node_ids_lazy`）で行う。

改善計画T531（フロンティア方式の周回生成）で、起点からの**一対全**最短経路木
（`build_shortest_path_tree`）をscipy.sparse.csgraph.dijkstraで求める用途が加わった。
一対全は前任者木（predecessors）が要り、rustworkxの`dijkstra_shortest_path_lengths`は
前任者を返さずEdgeごとにPythonコールバックへ戻るため、この用途だけはscipyのCSR表現
（`CsrGraphStructure`、`LazyRoadGraph`と同じEdge index空間・構造のみでタイル集合キーの
キャッシュ対象）を使う。標準ライブラリの実装をそのまま使うだけで、アルゴリズム自体の
独自実装ではない点は変わらない。

Route Engineは、Costの中身（勾配がきつい、路面が悪い等）を一切知らない設計とする
（仕様書33章）。ここで扱うのはRoad Graphのトポロジーと、既に計算済みのEdge Costのみ。
"""
import math
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

import numpy as np
import rustworkx as rx
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

from app.domain.geo import KM_PER_DEGREE_LATITUDE, haversine_distance_km
from app.domain.graph import RoadGraphLike
from app.domain.route import Coordinates


@dataclass
class LazyRoadGraph:
    """探索グラフのrustworkx表現（改善計画T529、`docs/tasks/T529.md`）。

    Edgeコストを事前計算しない——トポロジのみを保持し、探索中に実際に訪れたEdgeに
    対してのみ`edge_cost_fn`が都度呼ばれる（lazy評価）。PoC実測（合成グリッドグラフ、
    王子実測相当のnodes=139,876 edges=558,008）でA*は全Edgeの2.79%しか評価せずに済む
    ことを確認済み——T529以前の実装（bbox全体のコストを事前に一括計算してからscipyの
    CSRを構築する）は、この無駄な事前計算そのものが`prepare_ms`の支配的コストになって
    いた（T522実測、王子30km周回でcost_ms=18,105ms）。

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
    （改善計画T529、rustworkxのA*）。

    改善計画T536: `edge_cost_fn`/`estimate_cost_fn`は、`LazyRoadGraph`のNode/Edge payload
    である**整数index**（Edge index/Node index、それぞれ`lazy_graph.edge_ids`/
    `lazy_graph.index_to_node_id`の添字）を受け取る（旧: edge_id/node_id文字列）。
    典型的には呼び出し元が`cost_list.__getitem__`のような素のlistインデックスアクセスを
    そのまま渡す（探索中にPythonの関数フレームを作らない、`LazyRoadGraph`のdocstring
    参照）。Hard Constraintで除外されるEdgeは`edge_cost_fn`が`math.inf`を返すことで
    通行不能を表現する（T536以降はコストが探索前に判明しているため、この除外自体は
    `build_lazy_road_graph`より前の時点でコスト配列へ焼き込まれている）。`estimate_cost_fn`は目的地までの下界推定
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
    """Node ID列を、それらを結ぶEdgeのID列へ変換する。"""
    return [
        lazy_graph.edge_ids[
            lazy_graph.edge_index_by_node_pair[
                (lazy_graph.node_id_to_index[u], lazy_graph.node_id_to_index[v])
            ]
        ]
        for u, v in zip(path_node_ids, path_node_ids[1:])
    ]


# --- 改善計画T531: 一対全最短経路木（フロンティア方式の周回生成の共通基盤） ---


@dataclass
class CsrGraphStructure:
    """`LazyRoadGraph`と同じNode/Edge index空間を持つCSR（圧縮行格納）表現の**構造のみ**
    （改善計画T531）。Edge重み（コスト）はリクエストごとに変わるため持たず、
    `build_shortest_path_tree`が呼び出しのたびに`entry_edge_index`でコスト配列を
    CSRのdata順へ並べ替えて`scipy.sparse.csr_matrix`を組む。構造はタイル集合だけで
    決まる純粋な派生物のため`LazyRoadGraph`と同じキーでキャッシュできる
    （`infrastructure/search_graph_cache.py`）。
    """

    node_count: int
    # 標準CSR: 行（from Node index）ごとのエントリ範囲。長さnode_count+1。
    indptr: np.ndarray
    # CSRエントリ順のto Node index（各行内で昇順）。
    indices: np.ndarray
    # CSRエントリ順→`LazyRoadGraph.edge_ids`のEdge index（コスト配列の並べ替えに使う）。
    entry_edge_index: np.ndarray
    # CSRエントリ順の`from_index * node_count + to_index`（昇順）。`(pred, v)`のエントリ位置を
    # `np.searchsorted`で一括検索するための整列キー。
    entry_keys: np.ndarray


def build_csr_structure(lazy_graph: LazyRoadGraph) -> CsrGraphStructure:
    """`LazyRoadGraph`（並行Edge解消後の`edge_index_by_node_pair`）からCSR構造を組む。
    重複ペアは`build_lazy_road_graph`が既に解消済みのため、単純に`(from, to)`の昇順へ
    整列するだけでよい。"""
    node_count = len(lazy_graph.index_to_node_id)
    pairs = lazy_graph.edge_index_by_node_pair
    entry_count = len(pairs)
    keys = np.fromiter((u * node_count + v for u, v in pairs.keys()), dtype=np.int64, count=entry_count)
    edge_index = np.fromiter(pairs.values(), dtype=np.int64, count=entry_count)
    order = np.argsort(keys, kind="stable")
    keys = keys[order]
    edge_index = edge_index[order]
    indptr = np.zeros(node_count + 1, dtype=np.int64)
    if entry_count:
        rows = keys // node_count
        cols = keys % node_count
        np.cumsum(np.bincount(rows, minlength=node_count), out=indptr[1:])
    else:
        cols = np.zeros(0, dtype=np.int64)
    return CsrGraphStructure(
        node_count=node_count, indptr=indptr, indices=cols, entry_edge_index=edge_index, entry_keys=keys,
    )


@dataclass
class SearchGraphStatics:
    """タイル集合だけで決まる、探索用グラフの静的な派生物一式（改善計画T531）。
    `LazyRoadGraph`と同じキャッシュ寿命で保持し、リクエストごとに変わる値（コスト配列）は
    含めない。"""

    csr: CsrGraphStructure
    # `LazyRoadGraph.edge_ids`と同じ行順の実距離（m）。一対全木に沿った実距離の積算
    # （`ShortestPathTree.length_m`）と重複率（`select_diverse_by_overlap`）に使う。
    edge_length_m: np.ndarray


def build_search_graph_statics(lazy_graph: LazyRoadGraph, graph: RoadGraphLike) -> SearchGraphStatics:
    edge_length_m = np.fromiter(
        (graph.edges[edge_id].distance_m for edge_id in lazy_graph.edge_ids),
        dtype=float,
        count=len(lazy_graph.edge_ids),
    )
    return SearchGraphStatics(csr=build_csr_structure(lazy_graph), edge_length_m=edge_length_m)


@dataclass
class ShortestPathTree:
    """起点からの一対全最短経路木（改善計画T531）。配列はいずれも`LazyRoadGraph.
    index_to_node_id`と同じNode index順。"""

    source_index: int
    # 起点からの最小コスト（`edge_cost`の和）。到達不能（コストinf・cost_limit超過含む）はinf。
    cost: np.ndarray
    # 木の親Node index。起点・到達不能は-1。
    predecessor: np.ndarray
    # 木に沿った（＝最小コスト経路の）実距離（m）の積算。到達不能はNaN、起点は0。
    length_m: np.ndarray
    # `predecessor`のPython list版（遅延構築）。`tree_path_edge_indices`が数千Nodeぶんの
    # 経路復元でnumpyスカラーの取り出しを繰り返すのを避ける（実データ規模で約2倍速い）。
    _predecessor_list: list[int] | None = field(default=None, repr=False, compare=False)

    def is_reached(self, node_index: int) -> bool:
        return bool(np.isfinite(self.cost[node_index]))

    def predecessor_list(self) -> list[int]:
        if self._predecessor_list is None:
            self._predecessor_list = self.predecessor.tolist()
        return self._predecessor_list


def build_shortest_path_tree(
    structure: CsrGraphStructure,
    edge_cost: np.ndarray,
    edge_length_m: np.ndarray,
    source_index: int,
    cost_limit: float = np.inf,
) -> ShortestPathTree:
    """起点`source_index`からの一対全Dijkstra（scipy.sparse.csgraph、前任者付き）を行い、
    前任者木に沿った実距離も積算して返す（改善計画T531）。

    `edge_cost`/`edge_length_m`は`LazyRoadGraph.edge_ids`と同じ行順の配列。`math.inf`の
    コストは通行不能（0次フィルタ除外）を表し、scipyはそのEdge経由の到達をinfとして
    扱う（実測確認済み、`shortest_path_node_ids_lazy`の検算と同じ意味論）。`cost_limit`は
    このコストを超えるNodeの探索を打ち切る上限（scipyの`limit`、リングより外側の探索を
    省く用途。`cost >= distance`の不変条件[`_build_estimate_cost_fn`参照]により
    「実距離の上限×(1+P)」が安全な上限になる）。

    実距離の積算は、`(pred[v], v)`のCSRエントリ位置を`entry_keys`への`searchsorted`で
    一括検索した後、ポインタジャンプ（`acc[v] += acc[anc[v]]; anc[v] = anc[anc[v]]`を
    木の深さのlog2回だけ繰り返す）でベクトル演算する。素朴にcost昇順のPythonループで
    加算すると開発機の合成グリッド（14万Node）で1.2秒、numpyスカラーのループでは8.6秒
    かかったのに対し、この方式は0.2秒（docs/tasks/T531.md）。
    """
    n = structure.node_count
    data = np.asarray(edge_cost, dtype=float)[structure.entry_edge_index]
    matrix = csr_matrix((data, structure.indices, structure.indptr), shape=(n, n))
    cost, predecessor = scipy_dijkstra(
        matrix, directed=True, indices=source_index, return_predecessors=True, limit=cost_limit
    )
    predecessor = predecessor.astype(np.int64)
    predecessor[predecessor < 0] = -1  # scipyのセンチネル（-9999）を-1へ正規化
    length_m = _accumulate_tree_lengths(structure, predecessor, np.asarray(edge_length_m, dtype=float), source_index)
    return ShortestPathTree(source_index=source_index, cost=cost, predecessor=predecessor, length_m=length_m)


def _accumulate_tree_lengths(
    structure: CsrGraphStructure, predecessor: np.ndarray, edge_length_m: np.ndarray, source_index: int
) -> np.ndarray:
    n = structure.node_count
    has_pred = predecessor >= 0
    child = np.flatnonzero(has_pred)
    edge_to_child = np.zeros(n)
    if len(child):
        positions = np.searchsorted(structure.entry_keys, predecessor[child] * n + child)
        edge_to_child[child] = edge_length_m[structure.entry_edge_index[positions]]
    ancestor = np.where(has_pred, predecessor, np.arange(n))
    accumulated = edge_to_child.copy()
    for _ in range(64):  # 木の深さ2^64までの安全弁（実際はlog2(深さ)回で収束する）
        next_ancestor = ancestor[ancestor]
        if np.array_equal(next_ancestor, ancestor):
            break
        accumulated = accumulated + accumulated[ancestor]
        ancestor = next_ancestor
    reached = has_pred.copy()
    reached[source_index] = True
    return np.where(reached, accumulated, np.nan)


def tree_path_edge_indices(tree: ShortestPathTree, lazy_graph: LazyRoadGraph, target_index: int) -> list[int] | None:
    """一対全木上の起点→`target_index`の経路を、`LazyRoadGraph`のEdge index列で返す
    （改善計画T531。同じコスト配列でA*をかけ直しても同じ経路になるため、往路の再探索は
    不要）。到達不能ならNone、起点自身なら空リスト。"""
    if not tree.is_reached(target_index):
        return None
    edge_indices: list[int] = []
    current = int(target_index)
    pair_index = lazy_graph.edge_index_by_node_pair
    predecessor = tree.predecessor_list()
    source = tree.source_index
    while current != source:
        parent = predecessor[current]
        edge_indices.append(pair_index[(parent, current)])
        current = parent
    edge_indices.reverse()
    return edge_indices


def overlap_ratio(candidate_edges: np.ndarray, accepted_edges: np.ndarray, edge_length_m: np.ndarray) -> float:
    """`candidate_edges`（Edge index配列）のうち`accepted_edges`と共有する部分の距離加重割合
    （0〜1）。候補の総距離が0なら0。"""
    if len(candidate_edges) == 0:
        return 0.0
    lengths = edge_length_m[candidate_edges]
    total = float(lengths.sum())
    if total <= 0:
        return 0.0
    shared = float(lengths[np.isin(candidate_edges, accepted_edges)].sum())
    return shared / total


T = TypeVar("T")


def select_diverse_by_overlap(
    items: Sequence[T],
    edge_indices_of: Callable[[T], Sequence[int] | None],
    edge_length_m: np.ndarray,
    max_overlap_ratio: float,
    max_count: int,
    is_compatible: Callable[[T, list[T]], bool] | None = None,
    initial_selected: Sequence[T] | None = None,
    rejected_by_overlap: list[T] | None = None,
) -> list[T]:
    """ランク順の`items`を先頭から貪欲に採用し、採用済みのいずれかと経路の重複率
    （候補側の距離加重、`overlap_ratio`と同じ定義）が`max_overlap_ratio`を超えるもの、
    または`is_compatible(item, 採用済みリスト)`がFalseのものを飛ばして`max_count`件まで
    返す（改善計画T531の多様性間引き）。`edge_indices_of`がNoneを返すitemは対象外として
    飛ばす。`initial_selected`を渡すと、それらを採用済みとして（戻り値の先頭に含めて）
    続きを選ぶ（閾値を緩めた2回目のパスで、1回目の採用分を再検査しないため）。
    `rejected_by_overlap`（list）を渡すと、重複率だけを理由に飛ばしたitemを順に追記する
    （2回目のパスは`is_compatible`や経路無しで飛ばしたitemを再検査する必要が無いため、
    このリストだけを`items`に渡せばよい）。決定的（入力順と同じ規則でしか選ばない）。

    重複率は採用済み候補ごとのEdge集合をbool行列（採用数×Edge数）で持ち、候補のEdge index
    配列で列を抜き出して距離加重和を1回のnumpy演算で求める（採用済みごとに`np.isin`を
    呼ぶ実装は、数千件のリングNodeを検査する実データ規模で数百ms〜1秒超かかった）。
    """
    edge_count = len(edge_length_m)
    selected: list[T] = []
    masks = np.zeros((max(max_count, 1), edge_count), dtype=bool)

    def try_accept(item: T, edges: Sequence[int]) -> bool:
        if len(selected) >= max_count:
            return False
        edge_array = np.asarray(edges, dtype=np.int64)
        if len(selected) and len(edge_array):
            lengths = edge_length_m[edge_array]
            total = float(lengths.sum())
            if total > 0:
                shared = (masks[: len(selected)][:, edge_array] * lengths).sum(axis=1)
                if bool((shared / total > max_overlap_ratio).any()):
                    if rejected_by_overlap is not None:
                        rejected_by_overlap.append(item)
                    return False
        masks[len(selected), edge_array] = True
        selected.append(item)
        return True

    for item in initial_selected or ():
        edges = edge_indices_of(item)
        if edges is not None:
            try_accept(item, edges)
    seeded = set(map(id, selected))

    for item in items:
        if len(selected) >= max_count:
            break
        if id(item) in seeded:
            continue
        if is_compatible is not None and not is_compatible(item, selected):
            continue
        edges = edge_indices_of(item)
        if edges is None:
            continue
        try_accept(item, edges)
    return selected


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
