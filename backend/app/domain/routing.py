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
from collections.abc import Callable, Collection, Container, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

import numpy as np
from numba import njit
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

from app.domain.errors import RoutingError
from app.domain.geo import KM_PER_DEGREE_LATITUDE, bearing_between, haversine_distance_km
from app.domain.graph import RoadGraphLike
from app.domain.route import Coordinates


@dataclass
class LazyRoadGraph:
    """探索グラフのトポロジ表現。

    Node・Edgeとも整数index（`index_to_node_id`・`edge_ids`の添字）で扱い、文字列の
    node_id/edge_idは経路確定後の変換でのみ使う。コストは持たない——リクエストごとに変わる
    ため、探索へは別に合成した配列を渡す。並行Edge（同一Node間の複数Edge）はコスト最小の
    1本へ解消済み（`edge_index_by_node_pair`）。
    """

    node_id_to_index: dict[str, int]
    index_to_node_id: list[str]
    # edge_index（下記edge_idsの添字）→ edge_id。
    edge_ids: list[str]
    # (from_index, to_index) -> edge_index。並行Edge解消後の実際に採用されたペアのみ持つ。
    edge_index_by_node_pair: dict[tuple[int, int], int]


def build_lazy_road_graph(
    graph: RoadGraphLike, edge_cost_by_id: Mapping[str, float] | None = None
) -> LazyRoadGraph:
    """`graph`のトポロジから`LazyRoadGraph`を構築する（Hard Constraint自体は評価しない。
    除外は呼び出し元がcost=math.infで表現する）。

    `edge_cost_by_id`
    （edge_id→コスト、省略可）を渡すと、並行Edge（同一Node間の複数Edge）は**cost最小の
    Edgeを採用**する。省略時（コストがまだ判明していない場面、主にテスト）は、
    edge_idの昇順で先頭を採用する決定的な選択にフォールバックする。
    """
    node_ids = list(graph.nodes.keys())
    node_id_to_index = {node_id: i for i, node_id in enumerate(node_ids)}

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
        edge_ids.append(edge_id)
        edge_index_by_node_pair[pair] = edge_index

    return LazyRoadGraph(
        node_id_to_index=node_id_to_index,
        index_to_node_id=node_ids,
        edge_ids=edge_ids,
        edge_index_by_node_pair=edge_index_by_node_pair,
    )

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


def find_missing_lazy_graph_edge_id(
    lazy_graph: LazyRoadGraph, graph: RoadGraphLike, *, also_required_in: Container[str] | None = None
) -> str | None:
    """`lazy_graph.edge_ids`のうち`graph.edges`に存在しない最初のedge_idを返す
    （無ければNone）。`lazy_graph.edge_ids`は`graph.edges`の部分集合である前提
    （同じ`graph`から`build_lazy_road_graph`で作られた場合は常に成り立つ）だが、
    `lazy_graph`がタイル集合キーのプロセス内キャッシュ（`infrastructure/
    search_graph_cache.py`）からの再利用で、その間にタイルが再split（`save_graph`の
    edge_id再割当）された場合はこの前提が崩れうる。`build_search_graph_statics`の
    CSR構築を伴わない軽量版チェックで、`RoadGraphEngine._ensure_lazy_graph_consistent`
    （`prepare`・`preview_segment`共通）が呼ぶ。

    `also_required_in`を渡すと、そちらにも存在することを併せて確認する。`lazy_graph`の
    各edge_idは`graph.edges`だけでなく静的スコア行列の行索引（`road_graph_engine.py`の
    `full_edge_row`、`score_matrix.edge_ids`由来で材料とは別キャッシュ）からも引かれる
    ため、検証する集合を実際に消費する集合と一致させる。
    """
    return next(
        (
            edge_id
            for edge_id in lazy_graph.edge_ids
            if edge_id not in graph.edges or (also_required_in is not None and edge_id not in also_required_in)
        ),
        None,
    )


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

# --- ターン展開（状態＝有向Edge、辺＝ターン） ---


@dataclass(frozen=True)
class TurnCostSpec:
    """ターン1回の時間損失（秒）と、直進とみなす方位差の上限（度）。

    費用を秒で持ち、探索へ渡すときに巡航速度でm換算する（探索のコストが距離の単位のため、
    「右折1回＝何m遠回りするのと同じか」として距離と直接比較できる）。
    """

    left_seconds: float = 2.0
    right_seconds: float = 12.0
    uturn_seconds: float = 60.0
    straight_max_deg: float = 30.0


DEFAULT_TURN_COST = TurnCostSpec()


@dataclass
class TurnExpandedStructure:
    """有向Edgeを状態、ターンを辺として見た構造。

    `CsrGraphStructure`と同じくEdgeの重みは持たない（リクエストごとに変わるため）。グラフを
    物理的に作り直さず、遷移は`CsrGraphStructure`から導く——ターンの費用はノード側の性質
    （方位差・信号の有無）だけで決まり、状態の数を増やさずに表せる。行＝遷移元の状態
    （`LazyRoadGraph.edge_ids`の添字）、列＝遷移先の状態で、起点には依存しないため
    `CsrGraphStructure`と同じキーでキャッシュできる。
    """

    state_count: int
    # 状態ごとの遷移範囲。長さ state_count + 1。
    indptr: np.ndarray
    # 遷移先の状態（`LazyRoadGraph.edge_ids`の添字）。
    target_state: np.ndarray
    # 遷移ごとのターンの時間損失（秒）。
    turn_seconds: np.ndarray
    # 状態（有向Edge）の始点・終点Node index。
    edge_from: np.ndarray
    edge_to: np.ndarray


def edge_bearings(graph: RoadGraphLike, lazy_graph: LazyRoadGraph) -> np.ndarray:
    """`lazy_graph.edge_ids`順の方位（度）。`Edge.bearing_deg`（折れ線から求めた実際の向き）を
    使い、持たないEdgeだけ両端のNode座標から補う。"""
    bearings = np.zeros(len(lazy_graph.edge_ids))
    for index, edge_id in enumerate(lazy_graph.edge_ids):
        edge = graph.edges.get(edge_id)
        value = edge.bearing_deg if edge is not None else None
        if value is None and edge is not None:
            from_node = graph.nodes.get(edge.from_node_id)
            to_node = graph.nodes.get(edge.to_node_id)
            if from_node is not None and to_node is not None:
                value = bearing_between(from_node, to_node)
        bearings[index] = 0.0 if value is None else float(value)
    return bearings


def turn_seconds_for(
    from_bearing: np.ndarray, to_bearing: np.ndarray, is_uturn: np.ndarray, spec: TurnCostSpec
) -> np.ndarray:
    """遷移ごとのターンの時間損失（秒）。方位差の符号で左右を分ける（負＝反時計回り＝左折）。"""
    delta = (to_bearing - from_bearing + 180.0) % 360.0 - 180.0
    turning = np.where(delta < 0, spec.left_seconds, spec.right_seconds)
    return np.where(
        is_uturn, spec.uturn_seconds, np.where(np.abs(delta) <= spec.straight_max_deg, 0.0, turning)
    )


def build_turn_expanded_structure(
    csr: CsrGraphStructure,
    lazy_graph: LazyRoadGraph,
    bearing_deg: np.ndarray,
    spec: TurnCostSpec = DEFAULT_TURN_COST,
) -> TurnExpandedStructure:
    """`CsrGraphStructure`から、状態＝有向Edgeの遷移構造を組む。

    状態`e`の遷移先は「`e`の終点Nodeから出る有向Edge」で、遷移の数は
    Σ(入次数×出次数)。`e`の始点へ戻る遷移はUターンとして扱う（禁止はしない——袋小路からの
    折り返しに必要なため、費用で抑える）。
    """
    state_count = len(lazy_graph.edge_ids)
    edge_from = np.zeros(state_count, dtype=np.int64)
    edge_to = np.zeros(state_count, dtype=np.int64)
    for (tail, head), edge_index in lazy_graph.edge_index_by_node_pair.items():
        edge_from[edge_index] = tail
        edge_to[edge_index] = head

    indptr64 = csr.indptr.astype(np.int64)
    out_start = indptr64[edge_to]
    out_count = indptr64[edge_to + 1] - out_start
    total = int(out_count.sum())
    new_indptr = np.zeros(state_count + 1, dtype=np.int64)
    np.cumsum(out_count, out=new_indptr[1:])

    source = np.repeat(np.arange(state_count, dtype=np.int64), out_count)
    entry_index = np.repeat(out_start, out_count) + (
        np.arange(total, dtype=np.int64) - np.repeat(new_indptr[:state_count], out_count)
    )
    target_state = csr.entry_edge_index[entry_index].astype(np.int64)
    is_uturn = csr.indices[entry_index].astype(np.int64) == edge_from[source]
    turn_seconds = turn_seconds_for(bearing_deg[source], bearing_deg[target_state], is_uturn, spec)

    return TurnExpandedStructure(
        state_count=state_count, indptr=new_indptr, target_state=target_state,
        turn_seconds=turn_seconds, edge_from=edge_from, edge_to=edge_to,
    )


def build_turn_expanded_csr(
    structure: TurnExpandedStructure,
    edge_cost: np.ndarray,
    entry_state_indices: np.ndarray,
    speed_ms: float,
    *,
    reverse: bool = False,
) -> csr_matrix:
    """一対全木用のscipy CSRを組む。値は「遷移先の区間のコスト＋ターンの費用」。

    末尾の1行は仮想の始点で、`entry_state_indices`（正方向なら起点から出る区間、
    `reverse=True`なら目的地へ入る区間）へその区間のコスト自身で繋ぐ（複数の始点状態へ
    別々の初期コストを与えるため）。行数・列数はともに`state_count + 1`で、仮想始点の状態
    index は`state_count`。0次フィルタで除外された区間（コストが無限大）への遷移は落とす
    ——scipyは無限大を「辺が無い」ではなく「非常に大きい重み」として扱うため。

    `reverse=True`は遷移の向きだけを反転する（転置グラフ）。ターンの費用は元の進行方向の
    ままで、「その区間から目的地まで」のコストが求まる。
    """
    state_count = structure.state_count
    source = np.repeat(np.arange(state_count, dtype=np.int64), np.diff(structure.indptr))
    weight = edge_cost[structure.target_state] + structure.turn_seconds * speed_ms
    target = structure.target_state

    finite = np.isfinite(weight)
    source = source[finite]
    target = target[finite]
    weight = weight[finite]
    if reverse:
        source, target = target, source

    entry_states = entry_state_indices[np.isfinite(edge_cost[entry_state_indices])]
    source = np.concatenate([source, np.full(len(entry_states), state_count, dtype=np.int64)])
    target = np.concatenate([target, entry_states.astype(np.int64)])
    weight = np.concatenate([weight, edge_cost[entry_states]])

    order = np.argsort(source, kind="stable")
    indptr = np.zeros(state_count + 2, dtype=np.int64)
    np.cumsum(np.bincount(source, minlength=state_count + 1), out=indptr[1:])
    return csr_matrix(
        (weight[order], target[order], indptr), shape=(state_count + 1, state_count + 1)
    )


@dataclass
class TurnExpandedTree:
    """状態＝有向Edgeの一対全最短経路木。`state_*`は`LazyRoadGraph.edge_ids`と同じ行順、
    `node_*`はNode index順。

    `ShortestPathTree`と違い「起点Nodeのコスト0」という状態を持たない——状態の空間に
    「まだ走っていない」が無いため、起点Nodeの`node_cost`は「起点へ戻ってくるコスト」に
    なる。起点を0として扱いたい呼び出し元は自分で上書きする。
    """

    # 仮想始点から各状態への最小コスト。到達不能はinf。
    state_cost: np.ndarray
    # 木の親となる状態。始点の区間・到達不能は-1。
    predecessor: np.ndarray
    # 木に沿った実距離（m）の積算。到達不能はNaN。
    state_length_m: np.ndarray
    # Nodeごとの最小コストと、そのコストでNodeへ入る状態（到達不能は-1）。
    node_cost: np.ndarray
    node_best_state: np.ndarray
    # `node_best_state`に対応する実距離（m）。到達不能はNaN。
    node_length_m: np.ndarray
    # `predecessor`のPython list版（`ShortestPathTree`と同じ理由）。
    predecessor_list: list[int] = field(default_factory=list, repr=False, compare=False)


def build_turn_expanded_tree(
    structure: TurnExpandedStructure,
    edge_cost: np.ndarray,
    edge_length_m: np.ndarray,
    entry_state_indices: np.ndarray,
    speed_ms: float,
    node_count: int,
    *,
    reverse: bool = False,
    cost_limit: float = np.inf,
) -> TurnExpandedTree:
    """状態＝有向Edgeの一対全Dijkstra（scipy、前任者付き）。

    実距離の積算は`_accumulate_tree_lengths`と同じポインタジャンプだが、状態へ入る辺は
    その状態自身（有向Edge）のため、CSRエントリ位置の検索が要らない。
    """
    state_count = structure.state_count
    matrix = build_turn_expanded_csr(structure, edge_cost, entry_state_indices, speed_ms, reverse=reverse)
    cost, predecessor = scipy_dijkstra(
        matrix, directed=True, indices=state_count, return_predecessors=True, limit=cost_limit
    )
    state_cost = cost[:state_count]
    predecessor = predecessor[:state_count].astype(np.int64)
    # 仮想始点（index=state_count）とscipyのセンチネル（-9999）をまとめて-1へ正規化する。
    predecessor[(predecessor < 0) | (predecessor >= state_count)] = -1

    reached = np.isfinite(state_cost)
    has_pred = reached & (predecessor >= 0)
    # ポインタジャンプの不変条件「accumulated[v]はvからancestor[v]までの距離」を保つため、
    # 木の根（始点の区間）の親として長さ0の番兵を置く。番兵が無いと根が自分自身を指し、
    # 根の区間の長さが積算から落ちる（深さ2の経路で最後の1区間しか数えない）。
    sentinel = state_count
    accumulated = np.zeros(state_count + 1)
    accumulated[:state_count] = np.where(reached, np.asarray(edge_length_m, dtype=float), 0.0)
    ancestor = np.full(state_count + 1, sentinel, dtype=np.int64)
    ancestor[:state_count] = np.where(has_pred, predecessor, sentinel)
    for _ in range(64):  # 木の深さ2^64までの安全弁（実際はlog2(深さ)回で収束する）
        next_ancestor = ancestor[ancestor]
        if np.array_equal(next_ancestor, ancestor):
            break
        accumulated = accumulated + accumulated[ancestor]
        ancestor = next_ancestor
    state_length_m = np.where(reached, accumulated[:state_count], np.nan)

    # Nodeごとに最小コストの状態を1つ選ぶ（正方向はNodeへ入る状態、逆方向は出る状態）。
    incoming = structure.edge_from if reverse else structure.edge_to
    order = np.lexsort((state_cost, incoming))
    sorted_nodes = incoming[order]
    first = np.ones(len(order), dtype=bool)
    first[1:] = sorted_nodes[1:] != sorted_nodes[:-1]
    best_states = order[first]
    node_best_state = np.full(node_count, -1, dtype=np.int64)
    node_cost = np.full(node_count, np.inf)
    node_length_m = np.full(node_count, np.nan)
    finite_best = best_states[np.isfinite(state_cost[best_states])]
    node_best_state[incoming[finite_best]] = finite_best
    node_cost[incoming[finite_best]] = state_cost[finite_best]
    node_length_m[incoming[finite_best]] = state_length_m[finite_best]

    return TurnExpandedTree(
        state_cost=state_cost, predecessor=predecessor, state_length_m=state_length_m,
        node_cost=node_cost, node_best_state=node_best_state, node_length_m=node_length_m,
        predecessor_list=predecessor.tolist(),
    )


def turn_expanded_path_from_state(tree: TurnExpandedTree, state_index: int) -> list[int]:
    """前向き木で、始点→`state_index`の経路をEdge index列（進行順）で返す。状態がそのまま
    Edge indexのため、`(parent, current)`からEdgeを引き直す必要がない。"""
    edges: list[int] = []
    state = int(state_index)
    while state >= 0:
        edges.append(state)
        state = tree.predecessor_list[state]
    edges.reverse()
    return edges


def turn_expanded_path_from_state_to_source(tree: TurnExpandedTree, state_index: int) -> list[int]:
    """`reverse=True`で作った木で、`state_index`から木の始点（目的地）までの経路を進行順で
    返す。逆向きの木では前任者を辿ることが目的地へ近づくことに当たるため、反転しない。"""
    edges: list[int] = []
    state = int(state_index)
    while state >= 0:
        edges.append(state)
        state = tree.predecessor_list[state]
    return edges


def turn_expanded_path_edge_indices(tree: TurnExpandedTree, target_node_index: int) -> list[int] | None:
    """木上の始点→`target_node_index`の経路をEdge index列で返す。到達不能ならNone。"""
    state = int(tree.node_best_state[target_node_index])
    if state < 0:
        return None
    return turn_expanded_path_from_state(tree, state)


@dataclass
class NodeJunction:
    """前向き木と後ろ向き木を各Nodeで繋いだ結果。配列はNode index順。"""

    # 繋いだ合計コスト（前向き＋そのNodeでのターン＋後ろ向き）。繋げないNodeはinf。
    cost: np.ndarray
    # 同じ経路の実距離（m）。繋げないNodeはNaN。
    length_m: np.ndarray
    # 繋いだときの前向き側・後ろ向き側の状態（Edge index）。繋げないNodeは-1。
    forward_state: np.ndarray
    backward_state: np.ndarray


def combine_forward_backward_at_nodes(
    structure: TurnExpandedStructure,
    forward: TurnExpandedTree,
    backward: TurnExpandedTree,
    speed_ms: float,
    node_count: int,
) -> NodeJunction:
    """前向き木と後ろ向き木を、Nodeごとに「そこでのターンの費用を含めて」繋ぐ。

    Nodeで単に`forward.node_cost + backward.node_cost`を足すと、そのNodeを通り抜けるときの
    ターンの費用が抜ける（入る方向と出る方向の組み合わせで決まるため）。遷移（入る区間×出る
    区間の対）ごとに合計を求め、Nodeごとの最小を採る。
    """
    state_count = structure.state_count
    source = np.repeat(np.arange(state_count, dtype=np.int64), np.diff(structure.indptr))
    target = structure.target_state
    total = forward.state_cost[source] + structure.turn_seconds * speed_ms + backward.state_cost[target]
    length = forward.state_length_m[source] + backward.state_length_m[target]
    junction_node = structure.edge_to[source]

    cost = np.full(node_count, np.inf)
    length_m = np.full(node_count, np.nan)
    forward_state = np.full(node_count, -1, dtype=np.int64)
    backward_state = np.full(node_count, -1, dtype=np.int64)

    finite = np.flatnonzero(np.isfinite(total))
    if len(finite):
        order = finite[np.lexsort((total[finite], junction_node[finite]))]
        nodes = junction_node[order]
        first = np.ones(len(order), dtype=bool)
        first[1:] = nodes[1:] != nodes[:-1]
        best = order[first]
        best_nodes = junction_node[best]
        cost[best_nodes] = total[best]
        length_m[best_nodes] = length[best]
        forward_state[best_nodes] = source[best]
        backward_state[best_nodes] = target[best]
    return NodeJunction(
        cost=cost, length_m=length_m, forward_state=forward_state, backward_state=backward_state
    )


def node_costs_from_state_costs(
    state_cost: np.ndarray, structure: TurnExpandedStructure, node_count: int
) -> np.ndarray:
    """状態（有向Edge）ごとの到達コストを、Nodeごとの最小コストへ畳む。

    起点Nodeだけは「起点へ戻ってくるコスト」になる（状態＝有向Edgeの空間には「まだ走って
    いない状態」が無いため）。起点のコストを0として扱いたい呼び出し元は自分で上書きする。
    """
    per_node = np.full(node_count, np.inf)
    np.minimum.at(per_node, structure.edge_to, state_cost[: structure.state_count])
    return per_node


@njit(cache=True)
def _turn_expanded_astar(
    indptr: np.ndarray,
    target_state: np.ndarray,
    turn_seconds: np.ndarray,
    edge_to: np.ndarray,
    edge_cost: np.ndarray,
    node_heuristic: np.ndarray,
    origin_states: np.ndarray,
    goal_node: int,
    speed_ms: float,
    capacity: int,
) -> tuple[np.ndarray, int]:
    """状態＝有向区間・辺＝ターンのA*（JITコンパイル）。

    優先度キューはnumpy配列のバイナリヒープとして持つ（numbaは`heapq`を扱えない）。
    ヒープには`f = g + 目的地までの直線距離`と`g`の両方を積み、取り出したときに`g`が
    `best`より大きければ古いエントリとして捨てる。戻り値は前任者の配列と、目的地へ入った
    状態（到達不能なら-1）。
    """
    state_count = edge_to.shape[0]
    best = np.full(state_count, np.inf)
    predecessor = np.full(state_count, -1, dtype=np.int64)
    heap_f = np.empty(capacity)
    heap_g = np.empty(capacity)
    heap_state = np.empty(capacity, dtype=np.int64)
    size = 0

    for i in range(origin_states.shape[0]):
        state = origin_states[i]
        g = edge_cost[state]
        if not np.isfinite(g) or g >= best[state]:
            continue
        best[state] = g
        f = g + node_heuristic[edge_to[state]]
        j = size
        heap_f[j] = f
        heap_g[j] = g
        heap_state[j] = state
        while j > 0:
            parent = (j - 1) // 2
            if heap_f[parent] <= heap_f[j]:
                break
            tf = heap_f[parent]
            heap_f[parent] = heap_f[j]
            heap_f[j] = tf
            tg = heap_g[parent]
            heap_g[parent] = heap_g[j]
            heap_g[j] = tg
            ts = heap_state[parent]
            heap_state[parent] = heap_state[j]
            heap_state[j] = ts
            j = parent
        size += 1

    goal_state = -1
    while size > 0:
        g = heap_g[0]
        state = heap_state[0]
        size -= 1
        heap_f[0] = heap_f[size]
        heap_g[0] = heap_g[size]
        heap_state[0] = heap_state[size]
        j = 0
        while True:
            left = 2 * j + 1
            right = left + 1
            smallest = j
            if left < size and heap_f[left] < heap_f[smallest]:
                smallest = left
            if right < size and heap_f[right] < heap_f[smallest]:
                smallest = right
            if smallest == j:
                break
            tf = heap_f[smallest]
            heap_f[smallest] = heap_f[j]
            heap_f[j] = tf
            tg = heap_g[smallest]
            heap_g[smallest] = heap_g[j]
            heap_g[j] = tg
            ts = heap_state[smallest]
            heap_state[smallest] = heap_state[j]
            heap_state[j] = ts
            j = smallest

        if g > best[state]:
            continue
        if edge_to[state] == goal_node:
            goal_state = state
            break
        for entry in range(indptr[state], indptr[state + 1]):
            nxt = target_state[entry]
            cost = edge_cost[nxt]
            if not np.isfinite(cost):
                continue
            next_g = g + cost + turn_seconds[entry] * speed_ms
            if next_g >= best[nxt]:
                continue
            best[nxt] = next_g
            predecessor[nxt] = state
            next_f = next_g + node_heuristic[edge_to[nxt]]
            j = size
            heap_f[j] = next_f
            heap_g[j] = next_g
            heap_state[j] = nxt
            while j > 0:
                parent = (j - 1) // 2
                if heap_f[parent] <= heap_f[j]:
                    break
                tf = heap_f[parent]
                heap_f[parent] = heap_f[j]
                heap_f[j] = tf
                tg = heap_g[parent]
                heap_g[parent] = heap_g[j]
                heap_g[j] = tg
                ts = heap_state[parent]
                heap_state[parent] = heap_state[j]
                heap_state[j] = ts
                j = parent
            size += 1
    return predecessor, goal_state


def turn_expanded_shortest_path(
    structure: TurnExpandedStructure,
    edge_cost: np.ndarray,
    node_heuristic: np.ndarray,
    origin_states: np.ndarray,
    goal_node_index: int,
    speed_ms: float,
) -> list[int] | None:
    """起点から出る区間`origin_states`から`goal_node_index`までの最小コスト経路を、
    Edge index列（進行順）で返す。到達不能ならNone。

    `node_heuristic`はNodeごとの目的地までの直線距離（m）で、コストが距離以上である
    （`cost >= distance`）という不変条件により下界として使える。
    """
    capacity = len(structure.target_state) + len(origin_states) + 16
    predecessor, goal_state = _turn_expanded_astar(
        structure.indptr, structure.target_state, structure.turn_seconds, structure.edge_to,
        np.asarray(edge_cost, dtype=np.float64), np.asarray(node_heuristic, dtype=np.float64),
        np.asarray(origin_states, dtype=np.int64), int(goal_node_index), float(speed_ms), capacity,
    )
    if goal_state < 0:
        return None
    edges: list[int] = []
    state = int(goal_state)
    while state >= 0:
        edges.append(state)
        state = int(predecessor[state])
    edges.reverse()
    return edges
