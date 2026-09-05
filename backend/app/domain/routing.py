"""Route Engine（仕様書33-34章）。

Road Graph（domain/graph.py）とEdge Cost（domain/evaluation.py）を使って、2点間の
最小コスト経路を探索する。探索アルゴリズム自体は独自実装せず、標準的なグラフ
アルゴリズムライブラリの実装をそのまま利用する（仕様書34章「探索アルゴリズムを
独断で変更しない」「独自の経路探索アルゴリズムの実装はしない」の趣旨を踏まえ、
新規性のある独自アルゴリズムは開発しない）。2点間探索はrustworkxのA*
（`shortest_path_node_ids_lazy`、C実装、Node/Edge payloadを整数indexにして
Pythonコールバックを探索中に作らない）で行う。

起点からの**一対全**最短経路木（`build_shortest_path_tree`、フロンティア方式の
周回生成の共通基盤）はscipy.sparse.csgraph.dijkstraで求める。一対全は前任者木
（predecessors）が要り、rustworkxの`dijkstra_shortest_path_lengths`は前任者を返さず
EdgeごとにPythonのコールバックへ戻るため、この用途だけはscipyのCSR表現
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

from app.domain.errors import RoutingError
from app.domain.geo import KM_PER_DEGREE_LATITUDE, haversine_distance_km
from app.domain.graph import RoadGraphLike
from app.domain.route import Coordinates


@dataclass
class LazyRoadGraph:
    """探索グラフのrustworkx表現。

    Edgeコストを事前計算しない——トポロジのみを保持し、探索中に実際に訪れたEdgeに
    対してのみ`edge_cost_fn`が都度呼ばれる（lazy評価）。合成グリッドグラフ
    （nodes=139,876 edges=558,008規模）でA*は全Edgeの2.79%しか評価せずに済む
    （bbox全体のコストを事前に一括計算してからCSRを構築する方式は、この無駄な
    事前計算そのものが`prepare_ms`の支配的コストになる）。

    Node/Edgeのpayloadはいずれも整数index（`add_nodes_from(range(n))`・
    `add_edge(u, v, edge_index)`）にしてある。rustworkxの`astar_shortest_path`は
    `goal_fn`/`edge_cost_fn`/`estimate_cost_fn`へノード・Edgeの**payload**（rustworkx内部の
    生indexではない）を渡す仕様のため、payload自体を「配列の添字として直接使える整数」に
    しておくことで、呼び出し元（`shortest_path_node_ids_lazy`の呼び出し元、
    `road_graph_engine.py`）は`cost_list.__getitem__`のような素のlistインデックスアクセスを
    そのままcost_fn/estimate_cost_fnとして渡せる——探索中に一切Pythonの関数フレームを
    作らずに済む（辞書キャッシュ経由のPythonコールバックだとA* 24本で8.3〜17.7秒
    かかるが、素のlist.__getitem__に置き換えると0.37秒に短縮する）。文字列edge_id/node_idは、
    経路確定後の変換（`path_to_edge_ids_lazy`・戻り値のNode ID列）でのみ使う。
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

    Node/Edge payloadは整数index（`LazyRoadGraph`のdocstring参照）。`edge_cost_by_id`
    （edge_id→コスト、省略可）を渡すと、並行Edge（同一Node間の複数Edge）は**cost最小の
    Edgeを採用**する。省略時（コストがまだ判明していない場面、主にテスト）は、
    edge_idの昇順で先頭を採用する決定的な選択にフォールバックする。
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
    （rustworkxのA*）。

    `edge_cost_fn`/`estimate_cost_fn`は、`LazyRoadGraph`のNode/Edge payloadである
    **整数index**（Edge index/Node index、それぞれ`lazy_graph.edge_ids`/
    `lazy_graph.index_to_node_id`の添字）を受け取る。典型的には呼び出し元が
    `cost_list.__getitem__`のような素のlistインデックスアクセスをそのまま渡す
    （探索中にPythonの関数フレームを作らない、`LazyRoadGraph`のdocstring参照）。
    Hard Constraintで除外されるEdgeは`edge_cost_fn`が`math.inf`を返すことで通行不能を
    表現する（コストは探索前に判明しているため、この除外自体は`build_lazy_road_graph`
    より前の時点でコスト配列へ焼き込まれている）。`estimate_cost_fn`は目的地までの
    下界推定（admissibleヒューリスティック、直線距離）を返す。経路が存在しない場合は
    Noneを返す。
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
    # （他の有限コスト経路が存在する限りはそちらが優先されるため、このチェックは
    # finite経路が本当に存在しない場合にのみNoneへ倒す）。経路確定後に合計コストを
    # 検算し、無限大ならHard Constraintで実質到達不能だったとみなす。
    total_cost = 0.0
    for u, v in zip(path_indices, path_indices[1:]):
        edge_index = lazy_graph.edge_index_by_node_pair[(u, v)]
        total_cost += edge_cost_fn(edge_index)
    if not math.isfinite(total_cost):
        return None

    return [lazy_graph.index_to_node_id[i] for i in path_indices]


def path_to_edge_indices_lazy(lazy_graph: LazyRoadGraph, path_node_ids: list[str]) -> list[int]:
    """Node ID列を、それらを結ぶEdgeのindex列（`lazy_graph.edge_ids`の添字）へ変換する。"""
    return [
        lazy_graph.edge_index_by_node_pair[(lazy_graph.node_id_to_index[u], lazy_graph.node_id_to_index[v])]
        for u, v in zip(path_node_ids, path_node_ids[1:])
    ]


def path_to_edge_ids_lazy(lazy_graph: LazyRoadGraph, path_node_ids: list[str]) -> list[str]:
    """Node ID列を、それらを結ぶEdgeのID列へ変換する。"""
    return [lazy_graph.edge_ids[i] for i in path_to_edge_indices_lazy(lazy_graph, path_node_ids)]


# --- 一対全最短経路木（フロンティア方式の周回生成の共通基盤） ---


# CSRのindptr/indices/entry_edge_indexに使うdtype。実データ規模（東京都心30km四方の
# 合成グリッドで約14万Node・56万Edge）はint32の値域（約21億）に対して桁違いに小さく、
# タイル集合キーのプロセス内LRU（上限64件、後述）が常駐させる分の実メモリを半減できる。
_CSR_INDEX_DTYPE = np.int32


@dataclass
class CsrGraphStructure:
    """`LazyRoadGraph`と同じNode/Edge index空間を持つCSR（圧縮行格納）表現の**構造のみ**。
    Edge重み（コスト）はリクエストごとに変わるため持たず、`build_shortest_path_tree`が
    呼び出しのたびに`entry_edge_index`でコスト配列をCSRのdata順へ並べ替えて
    `scipy.sparse.csr_matrix`を組む。構造はタイル集合だけで決まる純粋な派生物のため
    `LazyRoadGraph`と同じキーでキャッシュできる（`infrastructure/search_graph_cache.py`）。
    """

    node_count: int
    # 標準CSR: 行（from Node index）ごとのエントリ範囲。長さnode_count+1。
    indptr: np.ndarray
    # CSRエントリ順のto Node index（各行内で昇順）。
    indices: np.ndarray
    # CSRエントリ順→`LazyRoadGraph.edge_ids`のEdge index（コスト配列の並べ替えに使う）。
    entry_edge_index: np.ndarray


def build_csr_structure(lazy_graph: LazyRoadGraph, *, reverse: bool = False) -> CsrGraphStructure:
    """`LazyRoadGraph`（並行Edge解消後の`edge_index_by_node_pair`）からCSR構造を組む。
    重複ペアは`build_lazy_road_graph`が既に解消済みのため、単純に`(from, to)`の昇順へ
    整列するだけでよい。

    `reverse=True`のときはキーを`v * node_count + u`（行=to Node index、列=from Node index）
    で組み、転置グラフのCSRを返す。転置CSR上で`source_index=destination`としてDijkstra
    をかけると、各Nodeから見た「元の有向グラフでのdestinationまでの最短経路コスト・
    距離」が得られる（後ろ向き木、`RoadGraphEngine.select_via_nodes`参照）。

    `from_index * node_count + to_index`の整列キーはCSR構造の構築だけに使う一時変数で、
    フィールドとしては持たない（`(pred, v)`のCSRエントリ位置検索
    ［`_accumulate_tree_lengths`］に必要な時点で`indptr`/`indices`から都度再構築する
    ——タイル集合キーのプロセス内LRU［上限64件］が常駐させる1エントリぶんのメモリを
    削減する）。
    """
    node_count = len(lazy_graph.index_to_node_id)
    pairs = lazy_graph.edge_index_by_node_pair
    entry_count = len(pairs)
    if reverse:
        keys = np.fromiter((v * node_count + u for u, v in pairs.keys()), dtype=np.int64, count=entry_count)
    else:
        keys = np.fromiter((u * node_count + v for u, v in pairs.keys()), dtype=np.int64, count=entry_count)
    edge_index = np.fromiter(pairs.values(), dtype=np.int64, count=entry_count)
    order = np.argsort(keys, kind="stable")
    keys = keys[order]
    edge_index = edge_index[order]
    indptr = np.zeros(node_count + 1, dtype=_CSR_INDEX_DTYPE)
    if entry_count:
        rows = keys // node_count
        cols = keys % node_count
        np.cumsum(np.bincount(rows, minlength=node_count), out=indptr[1:])
    else:
        cols = np.zeros(0, dtype=np.int64)
    return CsrGraphStructure(
        node_count=node_count,
        indptr=indptr,
        indices=cols.astype(_CSR_INDEX_DTYPE),
        entry_edge_index=edge_index.astype(_CSR_INDEX_DTYPE),
    )


class LazyGraphEdgeMismatchError(RoutingError):
    """`build_search_graph_statics`が`lazy_graph.edge_ids`のうち`graph.edges`に
    存在しないedge_idを検出したときに送出する。"""


@dataclass
class SearchGraphStatics:
    """タイル集合だけで決まる、探索用グラフの静的な派生物一式。
    `LazyRoadGraph`と同じキャッシュ寿命で保持し、リクエストごとに変わる値（コスト配列）は
    含めない。"""

    csr: CsrGraphStructure
    # `LazyRoadGraph.edge_ids`と同じ行順の実距離（m）。一対全木に沿った実距離の積算
    # （`ShortestPathTree.length_m`）と重複率（`select_diverse_by_overlap`）に使う。
    edge_length_m: np.ndarray


def find_missing_lazy_graph_edge_id(lazy_graph: LazyRoadGraph, graph: RoadGraphLike) -> str | None:
    """`lazy_graph.edge_ids`のうち`graph.edges`に存在しない最初のedge_idを返す
    （無ければNone）。`lazy_graph.edge_ids`は`graph.edges`の部分集合である前提
    （同じ`graph`から`build_lazy_road_graph`で作られた場合は常に成り立つ）だが、
    `lazy_graph`がタイル集合キーのプロセス内キャッシュ（`infrastructure/
    search_graph_cache.py`）からの再利用で、その間にタイルが再split（`save_graph`の
    edge_id再割当）された場合はこの前提が崩れうる。`build_search_graph_statics`の
    CSR構築を伴わない軽量版チェックで、`RoadGraphEngine._ensure_lazy_graph_consistent`
    （`prepare`・`preview_segment`共通）が呼ぶ。
    """
    return next((edge_id for edge_id in lazy_graph.edge_ids if edge_id not in graph.edges), None)


def build_search_graph_statics(
    lazy_graph: LazyRoadGraph, graph: RoadGraphLike, *, reverse: bool = False
) -> SearchGraphStatics:
    """`lazy_graph.edge_ids`が`graph.edges`の部分集合であることを`find_missing_lazy_graph_
    edge_id`で確認し、崩れていれば`LazyGraphEdgeMismatchError`を送出する（呼び出し側の
    `RoadGraphEngine._ensure_lazy_graph_consistent`が事前にこのチェックを済ませ、崩れて
    いれば`lazy_graph`ごと再構築してから呼ぶ前提のため、実運用でここが実際に送出することは
    無い想定——チェック自体を二重に持つことで、将来この関数が事前チェック無しで直接
    呼ばれても安全なままにする）。

    `reverse=True`は転置CSR版の`SearchGraphStatics`を返す（目的地からの後ろ向き木用）。
    `edge_length_m`は向きに依存しない（Edge index→実距離の対応表）ため共通で、`csr`のみ
    `build_csr_structure(..., reverse=True)`に差し替える。
    """
    missing_edge_id = find_missing_lazy_graph_edge_id(lazy_graph, graph)
    if missing_edge_id is not None:
        raise LazyGraphEdgeMismatchError(
            f"lazy_graph.edge_ids contains {missing_edge_id!r} not present in graph.edges "
            "(stale tile-set-keyed cache after re-split)"
        )
    edge_length_m = np.fromiter(
        (graph.edges[edge_id].distance_m for edge_id in lazy_graph.edge_ids),
        dtype=float,
        count=len(lazy_graph.edge_ids),
    )
    return SearchGraphStatics(csr=build_csr_structure(lazy_graph, reverse=reverse), edge_length_m=edge_length_m)


@dataclass
class ShortestPathTree:
    """起点からの一対全最短経路木。配列はいずれも`LazyRoadGraph.
    index_to_node_id`と同じNode index順。"""

    source_index: int
    # 起点からの最小コスト（`edge_cost`の和）。到達不能（コストinf・cost_limit超過含む）はinf。
    cost: np.ndarray
    # 木の親Node index。起点・到達不能は-1。
    predecessor: np.ndarray
    # 木に沿った（＝最小コスト経路の）実距離（m）の積算。到達不能はNaN、起点は0。
    length_m: np.ndarray
    # `predecessor`のPython list版。`tree_path_edge_indices`が数千Nodeぶんの経路復元で
    # numpyスカラーの取り出しを繰り返すのを避ける（実データ規模で約2倍速い）。一対全木は
    # 折返し点選定のたびに必ずこの経路復元で使われるため、遅延構築にする利点が無く
    # 構築時にtolist()する。
    predecessor_list: list[int] = field(default_factory=list, repr=False, compare=False)

    def is_reached(self, node_index: int) -> bool:
        return bool(np.isfinite(self.cost[node_index]))


def build_shortest_path_tree(
    structure: CsrGraphStructure,
    edge_cost: Sequence[float] | np.ndarray,
    edge_length_m: np.ndarray,
    source_index: int,
    cost_limit: float = np.inf,
) -> ShortestPathTree:
    """起点`source_index`からの一対全Dijkstra（scipy.sparse.csgraph、前任者付き）を行い、
    前任者木に沿った実距離も積算して返す。

    `edge_cost`/`edge_length_m`は`LazyRoadGraph.edge_ids`と同じ行順の配列。`math.inf`の
    コストは通行不能（0次フィルタ除外）を表し、scipyはそのEdge経由の到達をinfとして
    扱う（`shortest_path_node_ids_lazy`の検算と同じ意味論）。`cost_limit`はこのコストを
    超えるNodeの探索を打ち切る上限（scipyの`limit`、リングより外側の探索を省く用途。
    `cost >= distance`の不変条件[`_build_estimate_cost_fn`参照]により「実距離の上限×
    (1+P)」が安全な上限になる）。

    実距離の積算は、`(pred[v], v)`のCSRエントリ位置を整列キーへの`searchsorted`で
    一括検索した後、ポインタジャンプ（`acc[v] += acc[anc[v]]; anc[v] = anc[anc[v]]`を
    木の深さのlog2回だけ繰り返す）でベクトル演算する。素朴にcost昇順のPythonループで
    加算すると開発機の合成グリッド（14万Node）で1.2秒、numpyスカラーのループでは8.6秒
    かかるのに対し、この方式は0.2秒。
    """
    n = structure.node_count
    data = np.asarray(edge_cost, dtype=float)[structure.entry_edge_index]
    matrix = csr_matrix((data, structure.indices, structure.indptr), shape=(n, n))
    cost, predecessor = scipy_dijkstra(
        matrix, directed=True, indices=source_index, return_predecessors=True, limit=cost_limit
    )
    predecessor = predecessor.astype(np.int64)
    predecessor[predecessor < 0] = -1  # scipyのセンチネル（-9999）を-1へ正規化
    length_m = _accumulate_tree_lengths(
        structure, predecessor, np.asarray(edge_length_m, dtype=float), source_index, cost
    )
    return ShortestPathTree(
        source_index=source_index, cost=cost, predecessor=predecessor, length_m=length_m,
        predecessor_list=predecessor.tolist(),
    )


def _reconstruct_entry_keys(structure: CsrGraphStructure) -> np.ndarray:
    """CSRエントリ順の`from_index * node_count + to_index`（昇順）を`indptr`/`indices`から
    再構築する（永続フィールドとして持たない理由は`CsrGraphStructure`のdocstring参照）。
    `node_count`の2乗がint32の値域を超えうる（実データ規模で14万Node→約196億）ため、
    キーの計算自体はint64で行う——`indptr`/`indices`のdtype変更とは独立に、この整列キー
    自体は常にint64のまま。
    """
    n = structure.node_count
    rows = np.repeat(np.arange(n, dtype=np.int64), np.diff(structure.indptr))
    return rows * n + structure.indices.astype(np.int64)


def _accumulate_tree_lengths(
    structure: CsrGraphStructure, predecessor: np.ndarray, edge_length_m: np.ndarray, source_index: int,
    cost: np.ndarray,
) -> np.ndarray:
    """`predecessor >= 0`ではなく`np.isfinite(cost)`を到達判定の正本にする。使用中の
    scipy 1.18.1では両者は一致するが、infコストで打ち切られたEdgeの先へも前任者
    ポインタを書きうる別バージョンに対する契約保証——コストが確定した「到達済み」
    集合だけを実距離の積算対象にする。
    """
    n = structure.node_count
    reached = np.isfinite(cost)
    has_pred = reached & (predecessor >= 0)
    child = np.flatnonzero(has_pred)
    edge_to_child = np.zeros(n)
    if len(child):
        entry_keys = _reconstruct_entry_keys(structure)
        positions = np.searchsorted(entry_keys, predecessor[child] * n + child)
        edge_to_child[child] = edge_length_m[structure.entry_edge_index[positions]]
    ancestor = np.where(has_pred, predecessor, np.arange(n))
    accumulated = edge_to_child.copy()
    for _ in range(64):  # 木の深さ2^64までの安全弁（実際はlog2(深さ)回で収束する）
        next_ancestor = ancestor[ancestor]
        if np.array_equal(next_ancestor, ancestor):
            break
        accumulated = accumulated + accumulated[ancestor]
        ancestor = next_ancestor
    reached = reached.copy()
    reached[source_index] = True
    return np.where(reached, accumulated, np.nan)


def tree_path_edge_indices(tree: ShortestPathTree, lazy_graph: LazyRoadGraph, target_index: int) -> list[int] | None:
    """一対全木上の起点→`target_index`の経路を、`LazyRoadGraph`のEdge index列で返す
    （同じコスト配列でA*をかけ直しても同じ経路になるため、往路の再探索は不要）。
    到達不能ならNone、起点自身なら空リスト。"""
    if not tree.is_reached(target_index):
        return None
    edge_indices: list[int] = []
    current = int(target_index)
    pair_index = lazy_graph.edge_index_by_node_pair
    predecessor = tree.predecessor_list
    source = tree.source_index
    while current != source:
        parent = predecessor[current]
        edge_indices.append(pair_index[(parent, current)])
        current = parent
    edge_indices.reverse()
    return edge_indices


def tree_path_edge_indices_to_source(
    tree: ShortestPathTree, lazy_graph: LazyRoadGraph, start_index: int
) -> list[int] | None:
    """`build_csr_structure(..., reverse=True)`から組んだ木（後ろ向き木、`tree.source_index`が
    目的地）で、`start_index`から目的地までの経路を、実グラフの有向Edge（`start_index`→…→
    `tree.source_index`の順）のEdge index列で返す。転置CSR上の
    `predecessor[X]=P`は実グラフの`X→P`という辺を表すため、`tree_path_edge_indices`
    （前向き木・`(parent, current)`順でEdge検索し最後に反転）とはEdge検索の引数順が逆
    （`(current, parent)`）で、経路は既に`start→source`の順に積み上がるため反転は不要。
    到達不能ならNone、`start_index`自身が`tree.source_index`なら空リスト。"""
    if not tree.is_reached(start_index):
        return None
    edge_indices: list[int] = []
    current = int(start_index)
    pair_index = lazy_graph.edge_index_by_node_pair
    predecessor = tree.predecessor_list
    source = tree.source_index
    while current != source:
        parent = predecessor[current]
        edge_indices.append(pair_index[(current, parent)])
        current = parent
    return edge_indices


def overlap_ratio(candidate_edges: np.ndarray, accepted_edges: np.ndarray, edge_length_m: np.ndarray) -> float:
    """`candidate_edges`（Edge index配列）のうち`accepted_edges`と共有する部分の距離加重割合
    （0〜1）。候補の総距離が0なら0。単一の候補対採用済み1件（DEBUGログの`retrace_ratio`等）
    向けの定義。`select_diverse_by_overlap`内部の間引き本体は同じ定義を、採用済み複数件
    against 候補というbulk計算へ展開したもの（boolean行列×距離のnumpy演算、候補ごとに
    本関数を繰り返し呼ぶより高速）——閾値判定式を変更する場合は両方を揃えること。
    """
    if len(candidate_edges) == 0:
        return 0.0
    lengths = edge_length_m[candidate_edges]
    total = float(lengths.sum())
    if total <= 0:
        return 0.0
    shared = float(lengths[np.isin(candidate_edges, accepted_edges)].sum())
    return shared / total


T = TypeVar("T")


def pareto_front_mask(
    minimize_a: np.ndarray,
    minimize_b: np.ndarray,
    *,
    quantum_a: float,
    quantum_b: float,
) -> np.ndarray:
    """2つの「小さいほど良い」指標について、パレート非劣解（他のどの候補にも両方で
    負けていない候補）を示す真偽配列を返す。

    候補iが劣解になるのは「aもbもi以下で、少なくとも一方が真に小さい候補jが存在する」
    とき。ルート候補では距離と難易度がこの2指標にあたり、劣解＝「より短くてより易しい
    候補が他にあるので誰も選ぶ理由がない」を意味する。2指標を1つのスコアへ合成しない
    ため、重み配分という恣意的なパラメータを持たずに済む。

    `quantum_a`/`quantum_b`は「実質同じ」とみなす粒度で、比較の前に各指標をこの単位へ
    丸める（例: 距離200m・難易度0.1）。粒度を持たせないと、1m短いだけの候補が互いに
    非劣解として全件残りフィルタとして機能しない——逆に粗すぎると候補が減りすぎるため、
    呼び出し側が指標の意味に応じて決める。

    計算量はO(n log n)（aの昇順に走査しbの最小値を更新するだけ）。同値の扱いを含めて
    決定的で、入力順には依存しない。
    """
    if len(minimize_a) == 0:
        return np.zeros(0, dtype=bool)
    a = np.round(np.asarray(minimize_a, dtype=float) / quantum_a)
    b = np.round(np.asarray(minimize_b, dtype=float) / quantum_b)
    # aの昇順（同値内はbの昇順）に走査し、「自分より真に前にある点」の最小bと比べる。
    # 丸めた結果aもbも完全に同値になった点同士は互いを支配しないため、同じグループとして
    # まとめて同じ判定にする（1つだけ残す形にすると、完全に対称な候補群——例えば起点から
    # 全方位が等距離・同難易度の地形——が層へばらけ、後段の方位分散[prefer]が働く同点
    # グループを壊してしまう）。
    order = np.lexsort((b, a))
    sorted_a, sorted_b = a[order], b[order]
    group_starts = np.flatnonzero(
        np.concatenate(([True], (sorted_a[1:] != sorted_a[:-1]) | (sorted_b[1:] != sorted_b[:-1])))
    )
    group_b = sorted_b[group_starts]
    prefix_min = np.minimum.accumulate(group_b)
    # 自分のグループより前のグループにおける最小b。先頭は比較対象が無いため+inf。
    best_before_group = np.concatenate(([np.inf], prefix_min[:-1]))
    group_lengths = np.diff(np.append(group_starts, len(sorted_a)))
    best_before = np.repeat(best_before_group, group_lengths)
    is_front_sorted = sorted_b < best_before
    mask = np.zeros(len(a), dtype=bool)
    mask[order[is_front_sorted]] = True
    return mask


def pareto_layer_index(
    minimize_a: np.ndarray,
    minimize_b: np.ndarray,
    *,
    quantum_a: float,
    quantum_b: float,
    max_items: int,
) -> np.ndarray:
    """各点が第何層のパレートフロントに属するかを返す（非優越ソート、0始まり）。
    層に入らなかった点は-1。

    第1層（`pareto_front_mask`が返す非劣解）だけでは候補が2〜3件にしかならない
    ——2次元のパレートフロントは点の数が増えてもほとんど大きくならないため。第1層を
    取り除いた残りで再びフロントを求める、を繰り返して層を作ることで、必要な件数
    （`max_items`）ぶんがすべてトレードオフ構造で並ぶ。

    `max_items`件に達した層で打ち切る（それ以降の層は計算しない）。

    **計算量の要点**: 全点をそのまま繰り返しフロント判定にかけると層の数×O(n log n)に
    なり、リングが数万件規模だと無視できない時間になる（実測: 20万件で約670ms）。
    aを`quantum_a`で丸めた各段階について、bの小さい順に`max_items`件を超える点は
    層`max_items`以降にしか入りえない（同じ段階でbがより小さい点がk個あればそれらが
    すべて自分を支配するため層番号はk以上になる）ので、先に落としてから層を作る
    （同20万件で約38ms）。
    """
    n = len(minimize_a)
    layer = np.full(n, -1, dtype=np.int32)
    if n == 0 or max_items <= 0:
        return layer
    a = np.asarray(minimize_a, dtype=float)
    b = np.asarray(minimize_b, dtype=float)
    # 層max_items未満に入りえない点を先に落とす（上記「計算量の要点」参照）。落とす単位は
    # 点ではなく「aの段階×bの丸め値」のグループ——同値の点同士は互いを支配しないため
    # 同じ層に入る。点単位で数えると、完全に対称な候補群（全方位が等距離・同難易度の
    # 地形）がmax_items件で切られ、残りが層に入れないまま最後尾へ回ってしまう。
    bins = np.round(a / quantum_a).astype(np.int64)
    b_quantized = np.round(b / quantum_b).astype(np.int64)
    order = np.lexsort((np.arange(n), b_quantized, bins))
    sorted_bins, sorted_bq = bins[order], b_quantized[order]
    is_new_group = np.concatenate(
        ([True], (sorted_bins[1:] != sorted_bins[:-1]) | (sorted_bq[1:] != sorted_bq[:-1]))
    )
    group_index = np.cumsum(is_new_group) - 1
    is_new_bin = np.concatenate(([True], sorted_bins[1:] != sorted_bins[:-1]))
    bin_starts = np.flatnonzero(is_new_bin)
    first_group_of_bin = np.repeat(group_index[bin_starts], np.diff(np.append(bin_starts, n)))
    keep = order[group_index - first_group_of_bin < max_items]

    remaining = keep
    assigned = 0
    for index in range(max_items):
        if len(remaining) == 0:
            break
        mask = pareto_front_mask(a[remaining], b[remaining], quantum_a=quantum_a, quantum_b=quantum_b)
        layer[remaining[mask]] = index
        assigned += int(mask.sum())
        if assigned >= max_items:
            break
        remaining = remaining[~mask]
    return layer


def select_diverse_by_overlap(
    items: Sequence[T],
    edge_indices_of: Callable[[T], Sequence[int] | None],
    edge_length_m: np.ndarray,
    max_overlap_ratios: Sequence[float],
    max_count: int,
    is_compatible: Callable[[T, list[T]], bool] | None = None,
    *,
    tie_groups: Sequence[Sequence[T]] | None = None,
    prefer: Callable[[Sequence[T], list[T]], Sequence[T]] | None = None,
) -> list[T]:
    """ランク順の`items`を先頭から貪欲に採用し、採用済みのいずれかと経路の重複率
    （候補側の距離加重、`overlap_ratio`と同じ定義）が閾値を超えるもの、または
    `is_compatible(item, 採用済みリスト)`がFalseのものを飛ばして`max_count`件まで返す
    （多様性間引き）。`edge_indices_of`がNoneを返すitemは対象外として飛ばす。

    `max_overlap_ratios`は先頭から順に試す閾値列。ある閾値のパスで重複率だけを理由に
    飛ばした候補は、次の（より緩い）閾値のパスで再検査する——`is_compatible`がFalse・
    経路が無い（Noneを返す）ために飛ばした候補は、閾値を緩めても結果が変わらないため
    再検査しない。`max_count`件に達すれば以降の閾値は試さない。決定的（入力順と同じ
    規則でしか選ばない）。

    `tie_groups`を渡すと`items`の代わりに「同点グループ列」（ランク順に並んだグループの
    列、各グループは順位の付かない同点候補の集合）を走査する。グループ内の試行順は
    `prefer(残り候補, 採用済みリスト)`が返す順で、1件採用するたびに（採用済みが変わった
    時点で）残り候補に対して呼び直す——「採用済み候補に対してどれだけ離れているか」の
    ような、採用済み集合に依存する優先順を、走査した候補の数ではなく採用件数
    （`max_count`以下）の回数だけ計算すれば済むようにするため。`prefer`が無ければ
    グループ内は与えられた順。`tie_groups`無しの呼び出しは各itemを1件のグループとして
    扱うため挙動は変わらない。

    重複率は採用済み候補ごとの集合をEdgeごとのuint64ビットマスク1本（bit `i` が「採用済み
    `i`件目がこのEdgeを含む」を表す）で持ち、候補のEdge index配列で行を抜き出して
    距離加重和を1回のnumpy演算で求める（`max_count`の実際の上限は`TURNAROUND_POOL_MAX`
    =40・`MAX_ROUTES`=15のいずれもuint64の64bitに収まる。常駐メモリはEdge数×8B）。
    採用済みごとに`np.isin`を呼ぶ実装は、数千件のリングNodeを検査する実データ規模で
    数百ms〜1秒超かかった。
    """
    if max_count > 64:
        raise ValueError(f"select_diverse_by_overlap: max_count={max_count} exceeds the uint64 bitmask limit (64)")
    selected: list[T] = []
    edge_bits = np.zeros(len(edge_length_m), dtype=np.uint64)
    slot_bits = np.uint64(1) << np.arange(max(max_count, 1), dtype=np.uint64)

    def try_accept(item: T, edges: Sequence[int], max_overlap_ratio: float, rejected: list[T] | None) -> bool:
        if len(selected) >= max_count:
            return False
        edge_array = np.asarray(edges, dtype=np.int64)
        if len(selected) and len(edge_array):
            lengths = edge_length_m[edge_array]
            total = float(lengths.sum())
            if total > 0:
                candidate_bits = edge_bits[edge_array]
                shared_mask = (candidate_bits[:, None] & slot_bits[: len(selected)]) != 0
                shared = (shared_mask * lengths[:, None]).sum(axis=0)
                if bool((shared / total > max_overlap_ratio).any()):
                    if rejected is not None:
                        rejected.append(item)
                    return False
        edge_bits[edge_array] |= slot_bits[len(selected)]
        selected.append(item)
        return True

    groups: list[list[T]] = (
        [list(group) for group in tie_groups] if tie_groups is not None else [[item] for item in items]
    )
    for ratio_index, max_overlap_ratio in enumerate(max_overlap_ratios):
        is_last_ratio = ratio_index == len(max_overlap_ratios) - 1
        rejected_groups: list[list[T]] | None = None if is_last_ratio else []
        for group in groups:
            if len(selected) >= max_count:
                break
            rejected_in_group: list[T] | None = None if is_last_ratio else []
            remaining: list[T] = group
            while remaining and len(selected) < max_count:
                ordered = list(prefer(remaining, selected)) if prefer is not None else remaining
                accepted_at: int | None = None
                for position, item in enumerate(ordered):
                    if len(selected) >= max_count:
                        break
                    if is_compatible is not None and not is_compatible(item, selected):
                        continue
                    edges = edge_indices_of(item)
                    if edges is None:
                        continue
                    if try_accept(item, edges, max_overlap_ratio, rejected_in_group):
                        accepted_at = position
                        break
                if accepted_at is None:
                    break
                # 採用より前に飛ばした候補は、採用済みが増えても結果が変わらない（重複率は
                # 増える一方、非互換・経路無しは不変）ため残り候補から外す。
                remaining = ordered[accepted_at + 1:]
            if rejected_groups is not None and rejected_in_group:
                rejected_groups.append(rejected_in_group)
        if len(selected) >= max_count or not rejected_groups:
            break
        groups = rejected_groups
    return selected


@dataclass
class NodeSpatialIndex:
    """緯度経度の総当たり線形探索を高速化するグリッドバケット索引。

    `RoadGraphEngine`は1リクエストの同じRoad Graphに対し繰り返し、指定地点に最も
    近いNodeを探す呼び出しを行う（`prepare`で起点1回・`trace_loop`で経由地と目的地
    ごとに1回・`preview_segment`で両端2回）。ノード数が増えるとこの繰り返しが
    線形探索×回数ぶん積み上がるため、索引を1回だけ構築して使い回す。新規外部
    ライブラリ（scipy.spatial.cKDTree等）は導入せず、既定の`dict`だけで組める
    グリッドバケット方式にする（PostGIS空間インデックスが無い構成でも同じロジックで
    動く）。
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
    のみを索引の候補にする（`routable_node_ids`と組み合わせ、Hard Constraint通過後に
    孤立するNodeを最近傍探索の候補から除外するために使う）。
    """
    ids = graph.nodes.keys() if node_ids is None else node_ids
    buckets: dict[tuple[int, int], list[str]] = {}
    for node_id in ids:
        node = graph.nodes[node_id]
        key = (math.floor(node.latitude / cell_size_deg), math.floor(node.longitude / cell_size_deg))
        buckets.setdefault(key, []).append(node_id)
    return NodeSpatialIndex(graph=graph, cell_size_deg=cell_size_deg, buckets=buckets)


def find_nearest_node_indexed(
    index: NodeSpatialIndex, point: Coordinates, predicate: Callable[[str], bool] | None = None
) -> str | None:
    """`build_node_spatial_index`が作った索引を使い、指定地点に最も近いNodeを総当たり
    より高速に探す。

    グリッドバケットを中心セルから外側へリング状に広げながら探索し、既知の最近傍距離が
    「まだ調べていない外側リングのどの点までの距離よりも近い」と保証できた時点で打ち切る
    （標準的なグリッド最近傍探索の安全な停止条件）。安全マージンには経度方向（cos補正込み、
    高緯度ほど1度あたりの物理距離が短くなる）の1度あたり距離を使う——経度方向のセルは
    緯度方向より常に狭い（赤道上でのみ等しい）ため、緯度方向の距離をそのまま安全マージンに
    使うと、実際にはまだ調べていない経度方向のセルの方が近い可能性があるのに打ち切って
    しまう。

    `predicate`を渡すと、それがFalseを返すNodeを最近傍候補から除外する（目的地ルートで
    一番近いNodeがメインの道路網から孤立している場合に、アクセス可能な最寄りNodeへ
    改めて絞り込むために使う）。停止条件は「見つかった最近傍（`predicate`を満たすもの
    限定）の距離」を基準にするため、除外対象があっても安全性は変わらない。
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
                    if predicate is not None and not predicate(node_id):
                        continue
                    node = index.graph.nodes[node_id]
                    # nodeは既にlatitude/longitudeを持つ（NodeLike）ため、
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
