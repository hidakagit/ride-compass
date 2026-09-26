"""Route Engine。

Road Graph（domain/graph.py）とEdge Cost（domain/evaluation.py）を使って、2点間の
最小コスト経路を探索する。アルゴリズムは教科書どおりのDijkstra/A*で、独自のものは作らない。

探索の状態は**Nodeではなく有向Edge**にする（辺基準グラフ）。右左折の費用はNodeに閉じず
「どの区間から入ってどの区間へ出るか」で決まるため、Nodeを状態にすると表現できない。
状態遷移はグラフを物理展開せず既存のCSR（`CsrGraphStructure`）から導く
（`TurnExpandedStructure`）。

2点間探索も一対全の最短経路木も、numbaでJITした探索で求める（優先度キューはnumpy配列の
バイナリヒープ）。ライブラリ（scipy等）へ委ねられないのは**到達時刻をラベルとして
持ち回る**ためで、コストが辺の静的な属性である前提のライブラリでは時刻で変わるコストを
表せない。

Route Engineは、Costの中身（勾配がきつい、路面が悪い等）を一切知らない。ここで扱うのは
Road Graphのトポロジーと、既に計算済みのEdge Costのみ。
"""
import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

import numpy as np
from numba import njit
from app.domain.geo import bearing_between, haversine_distance_km_array, km_per_degree_longitude
from app.domain.route import Coordinates
from app.domain.traffic import MAJOR_CROSSING_MIN_RANK
from app.domain.tuning import tuning_value

logger = logging.getLogger("ridecompass.graph")


@dataclass
class LazyRoadGraph:
    """探索グラフのトポロジ表現。

    Node・区間とも番号で扱う。区間の番号（`edge_rows`の添字）は探索の状態でもあり、
    `(始点, 終点)`の昇順に並ぶ。コストは持たない——リクエストごとに変わるため、探索へは別に
    合成した配列を渡す。同じノード対を結ぶ並行区間は、元の行（`edge_rows`の値）が最も小さい
    1本だけを残す。
    """

    node_count: int
    # 区間の番号→元の区間の行（探索範囲の材料・スコア行列の行）。
    edge_rows: np.ndarray
    edge_from: np.ndarray
    edge_to: np.ndarray


def build_lazy_road_graph(edge_from: np.ndarray, edge_to: np.ndarray, node_count: int) -> LazyRoadGraph:
    """区間の始点・終点（元の行の順）から`LazyRoadGraph`を組む（Hard Constraint自体は
    評価しない。除外は呼び出し元がcost=math.infで表現する）。

    並行区間の解消はコストに依らず決める——コストはリクエストごとに変わるため、トポロジを
    組む時点では決められない。
    """
    tail = np.asarray(edge_from, dtype=np.int64)
    head = np.asarray(edge_to, dtype=np.int64)
    keys = tail * node_count + head
    order = np.lexsort((np.arange(len(keys)), keys))
    sorted_keys = keys[order]
    first = np.ones(len(order), dtype=bool)
    first[1:] = sorted_keys[1:] != sorted_keys[:-1]
    kept = order[first]
    return LazyRoadGraph(node_count=node_count, edge_rows=kept, edge_from=tail[kept], edge_to=head[kept])


# --- 一対全最短経路木（フロンティア方式の周回生成の共通基盤） ---


# CSRのindptr/indices/entry_edge_indexに使うdtype。Node数・Edge数はint32の値域に対して
# 桁違いに小さく、生成1回ぶんの一時的なメモリを半減できる。
_CSR_INDEX_DTYPE = np.int32

# 優先度キューの初期容量（種の数＋この余裕）。満杯になれば倍へ伸びるため上限を当てる必要は
# 無く、**当ててはいけない**——コストが時刻で変わると押し込み回数が遷移数で頭打ちにならない。
# 小さく始めることで、伸長の経路が普通の探索で毎回通る（使われない分岐にしない）。
_HEAP_INITIAL_SLACK = 64


@dataclass
class CsrGraphStructure:
    """`LazyRoadGraph`と同じNode/区間の番号を持つCSR（圧縮行格納）表現の**構造のみ**。

    Edge重み（コスト）はリクエストごとに変わるため持たず、`entry_edge_index`が
    CSRエントリ順とコスト配列の行順を結ぶ。各行の中は終点の昇順（`edge_index_between`が二分探索する）。
    """

    node_count: int
    # 標準CSR: 行（from Node index）ごとのエントリ範囲。長さnode_count+1。
    indptr: np.ndarray
    # CSRエントリ順のto Node index（各行内で昇順）。
    indices: np.ndarray
    # CSRエントリ順→区間の番号（コスト配列の並べ替えに使う）。
    entry_edge_index: np.ndarray


def _build_csr_structure(lazy_graph: LazyRoadGraph) -> CsrGraphStructure:
    """`LazyRoadGraph`（区間は`(始点, 終点)`の昇順）からCSR構造を組む。"""
    node_count = lazy_graph.node_count
    indptr = np.zeros(node_count + 1, dtype=_CSR_INDEX_DTYPE)
    np.cumsum(np.bincount(lazy_graph.edge_from, minlength=node_count), out=indptr[1:])
    return CsrGraphStructure(
        node_count=node_count,
        indptr=indptr,
        indices=lazy_graph.edge_to.astype(_CSR_INDEX_DTYPE),
        entry_edge_index=np.arange(len(lazy_graph.edge_to), dtype=_CSR_INDEX_DTYPE),
    )


def edge_index_between(csr: CsrGraphStructure, tail: int, head: int) -> int | None:
    """`tail`→`head`の区間の番号。無ければNone（一方通行の逆向き等）。"""
    start, stop = int(csr.indptr[tail]), int(csr.indptr[tail + 1])
    position = start + int(np.searchsorted(csr.indices[start:stop], head))
    if position < stop and csr.indices[position] == head:
        return int(csr.entry_edge_index[position])
    return None


@dataclass
class SearchGraphStatics:
    """探索用グラフの静的な派生物一式。リクエストごとに変わる値（コスト配列）は含めない。"""

    csr: CsrGraphStructure
    # 区間の番号順の実距離（m）。一対全木に沿った実距離の積算
    # （`TurnExpandedTree.state_length_m`）と重複率（`select_diverse_by_overlap`）に使う。
    edge_length_m: np.ndarray


def build_search_graph_statics(lazy_graph: LazyRoadGraph, distance_m: np.ndarray) -> SearchGraphStatics:
    """探索用の静的な派生物一式を組む。`distance_m`は元の行の順の区間の長さ。"""
    return SearchGraphStatics(
        csr=_build_csr_structure(lazy_graph),
        edge_length_m=np.asarray(distance_m, dtype=float)[lazy_graph.edge_rows],
    )

def overlap_ratio(candidate_edges: np.ndarray, accepted_edges: np.ndarray, edge_length_m: np.ndarray) -> float:
    """`candidate_edges`（Edge index配列）のうち`accepted_edges`と共有する部分の距離加重
    割合（0〜1）。候補1件対採用済み1件向けの定義。

    `select_diverse_by_overlap`の間引き本体はこれを呼ぶ（同じ定義を2箇所に書かない
    ——書けば、片方だけ変えても何も落ちない）。
    """
    if len(candidate_edges) == 0:
        return 0.0
    lengths = edge_length_m[candidate_edges]
    return _shared_ratio(lengths, np.isin(candidate_edges, accepted_edges))


def _shared_ratio(lengths: np.ndarray, shared_mask: np.ndarray) -> float:
    """共有部分の距離加重割合。`overlap_ratio`と間引き本体が共有する唯一の定義。"""
    return float(lengths[shared_mask].sum()) / float(lengths.sum())


T = TypeVar("T")


def _pareto_front_mask(
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

    第1層（`_pareto_front_mask`が返す非劣解）だけでは候補が2〜3件にしかならない
    ——2次元のパレートフロントは点の数が増えてもほとんど大きくならないため。第1層を
    取り除いた残りで再びフロントを求める、を繰り返して層を作ることで、必要な件数
    （`max_items`）ぶんがすべてトレードオフ構造で並ぶ。

    `max_items`件に達した層で打ち切る（それ以降の層は計算しない）。

    **計算量の要点**: 全点をそのまま繰り返しフロント判定にかけると層の数×O(n log n)に
    なり、リングが数万件規模だと無視できない時間になる。aを`quantum_a`で丸めた各段階に
    ついて、bの小さい順に`max_items`件を超える点は層`max_items`以降にしか入りえない
    （同じ段階でbがより小さい点がk個あればそれらがすべて自分を支配するため層番号はk以上に
    なる）ので、先に落としてから層を作る。
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
        mask = _pareto_front_mask(a[remaining], b[remaining], quantum_a=quantum_a, quantum_b=quantum_b)
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
    距離加重和を1回のnumpy演算で求める。そのため`max_count`はuint64の64bitを超えられない。
    """
    if max_count > 64:
        raise ValueError(f"select_diverse_by_overlap: max_count={max_count} exceeds the uint64 bitmask limit (64)")
    selected: list[T] = []
    edge_bits = np.zeros(len(edge_length_m), dtype=np.uint64)
    slot_bits = np.uint64(1) << np.arange(max(max_count, 1), dtype=np.uint64)

    def try_accept(item: T, edges: Sequence[int], max_overlap_ratio: float, rejected: list[T] | None) -> bool:
        edge_array = np.asarray(edges, dtype=np.int64)
        if len(selected):
            lengths = edge_length_m[edge_array]
            candidate_bits = edge_bits[edge_array]
            shared_mask = (candidate_bits[:, None] & slot_bits[: len(selected)]) != 0
            ratios = [
                _shared_ratio(lengths, shared_mask[:, slot]) for slot in range(len(selected))
            ]
            if any(ratio > max_overlap_ratio for ratio in ratios):
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
                    # 空は「どれとも重複しない候補」ではなく「経路にならない」。Noneと同じ扱い。
                    if not edges:
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

    `RoadGraphEngine`は1リクエストの同じRoad Graphに対し、指定地点に最も近いNodeを探す
    呼び出しを繰り返す。ノード数が増えるとその繰り返しが線形探索×回数ぶん積み上がるため、
    索引を1回だけ構築して使い回す。
    """

    # ノード番号順の座標（索引に載らないノードも含む）。
    latitude: np.ndarray
    longitude: np.ndarray
    cell_size_deg: float
    # セル→そのセルにある候補のノード番号（昇順）。
    buckets: dict[tuple[int, int], np.ndarray]
    #: 非空セルが占める範囲（最小・最大のセル座標）。Nodeが1つも無ければNone。
    #: **探索の打ち切りに要る**——この外側にはどれだけ広げてもセルが1つも無い。
    #: 既定値を持たせない: 省略できると、渡し忘れた索引が黙って「Nodeが無い」ふるまいに
    #: なる（`build_node_spatial_index`が唯一の作り手）。
    cell_bounds: tuple[int, int, int, int] | None


# 1セルの一辺（度）。緯度で約1.1km四方。探索半径を広げるコストとバケット数のトレードオフを
# 取った経験的な値で、極端に不適切でなければ結果は変わらない（速さだけが変わる）。
_DEFAULT_NODE_INDEX_CELL_SIZE_DEG = 0.01
#: 索引が覆う範囲のどれだけ外側までを「隣」として許すか（セル数）。範囲の縁をわずかに
#: 外した点まで弾くと、読み込んだ地図の端をクリックしただけでスナップできなくなる。
_NEIGHBOR_CELL_TOLERANCE = 1


def build_node_spatial_index(
    latitude: np.ndarray,
    longitude: np.ndarray,
    candidates: np.ndarray | None = None,
    cell_size_deg: float = _DEFAULT_NODE_INDEX_CELL_SIZE_DEG,
) -> NodeSpatialIndex:
    """ノードの座標からグリッドバケット索引を構築する。ノードが1つも無くても空の
    bucketsを持つ索引を返す（`find_nearest_node_indexed`がNoneを返す）。

    `candidates`（ノード番号順の真偽）を渡すと、真のノードだけを索引の候補にする（Hard
    Constraint通過後に孤立するNodeを最近傍探索から外すために使う）。
    """
    latitude = np.asarray(latitude, dtype=np.float64)
    longitude = np.asarray(longitude, dtype=np.float64)
    ids = np.arange(len(latitude)) if candidates is None else np.flatnonzero(candidates)
    cell_lat = np.floor(latitude[ids] / cell_size_deg).astype(np.int64)
    cell_lon = np.floor(longitude[ids] / cell_size_deg).astype(np.int64)
    order = np.lexsort((ids, cell_lon, cell_lat))
    ids, cell_lat, cell_lon = ids[order], cell_lat[order], cell_lon[order]
    starts = np.flatnonzero(np.concatenate(([True], (cell_lat[1:] != cell_lat[:-1]) | (cell_lon[1:] != cell_lon[:-1]))))
    stops = np.append(starts[1:], len(ids))
    buckets = {
        (int(cell_lat[start]), int(cell_lon[start])): ids[start:stop]
        for start, stop in zip(starts.tolist(), stops.tolist(), strict=True)
    } if len(ids) else {}
    bounds = (
        (int(cell_lat.min()), int(cell_lon.min()), int(cell_lat.max()), int(cell_lon.max()))
        if len(ids)
        else None
    )
    return NodeSpatialIndex(
        latitude=latitude, longitude=longitude, cell_size_deg=cell_size_deg, buckets=buckets, cell_bounds=bounds
    )


def find_nearest_node_indexed(
    index: NodeSpatialIndex,
    point: Coordinates,
    allowed: np.ndarray | None = None,
    max_distance_km: float | None = None,
) -> int | None:
    """`build_node_spatial_index`が作った索引を使い、指定地点に最も近いNodeを総当たり
    より高速に探す。

    グリッドバケットを中心セルから外側へリング状に広げながら探索し、既知の最近傍距離が
    「まだ調べていない外側リングのどの点までの距離よりも近い」と保証できた時点で打ち切る
    （標準的なグリッド最近傍探索の安全な停止条件）。安全マージンには経度方向（cos補正込み、
    高緯度ほど1度あたりの物理距離が短くなる）の1度あたり距離を使う——経度方向のセルは
    緯度方向より常に狭い（赤道上でのみ等しい）ため、緯度方向の距離をそのまま安全マージンに
    使うと、実際にはまだ調べていない経度方向のセルの方が近い可能性があるのに打ち切って
    しまう。

    `allowed`（ノード番号順の真偽）を渡すと、偽のNodeを最近傍候補から除外する（目的地ルートで
    一番近いNodeがメインの道路網から孤立している場合に、アクセス可能な最寄りNodeへ
    改めて絞り込むために使う）。停止条件は「見つかった最近傍（`allowed`が真のもの
    限定）の距離」を基準にするため、除外対象があっても安全性は変わらない。

    **`allowed`が1つも真にならないとき、上の停止条件は成立しない。** そのため半径は
    索引が占める範囲の外へ出た時点でも打ち切る——その外側にはどれだけ広げてもセルが
    1つも無く、走査は結果を変えずに時間だけを使う。

    索引が覆う範囲の外を指した点はNoneを返す（`_NEIGHBOR_CELL_TOLERANCE`セルだけ外側まで
    は許す。範囲の縁をわずかに外した点は、すぐ隣にある道へ寄せるのが自然なため）。
    **この判定が無いと、何十kmも離れた道へ黙って寄せた結果を返す**——呼び出し側はそれを
    「利用者が指した地点」として扱うため、指した覚えのない場所を通るルートになる。

    `max_distance_km`を渡すと、それより遠いNodeは返さない（Noneになる）。探索する
    リング数もその距離ぶんで打ち切るため、`allowed`が1つも真にならない場合の走査量も
    同時に抑えられる。「近くに無いなら寄せない」という意味を持つ呼び出しは、範囲の
    広さではなく距離でこれを表す。

    戻り値はノード番号。
    """
    if index.cell_bounds is None:
        return None

    cell_lat = math.floor(point.latitude / index.cell_size_deg)
    cell_lon = math.floor(point.longitude / index.cell_size_deg)
    # 経度方向1度あたりの物理距離（cos補正込み）を安全マージンに使う——2方向のうち
    # 常に短い（＝より保守的な）方でなければ、リング内に未探索の近い点が残りうる。
    cell_size_km_lower_bound = index.cell_size_deg * km_per_degree_longitude(point.latitude)

    nearest_node: int | None = None
    nearest_distance: float | None = None
    radius = 0
    # 検索セルから、非空セルが占める範囲の一番遠い角までのリング数。ここを超えると
    # どのリングも空になる。
    min_cell_lat, min_cell_lon, max_cell_lat, max_cell_lon = index.cell_bounds
    if (
        cell_lat < min_cell_lat - _NEIGHBOR_CELL_TOLERANCE
        or cell_lat > max_cell_lat + _NEIGHBOR_CELL_TOLERANCE
        or cell_lon < min_cell_lon - _NEIGHBOR_CELL_TOLERANCE
        or cell_lon > max_cell_lon + _NEIGHBOR_CELL_TOLERANCE
    ):
        return None
    max_radius = max(
        abs(cell_lat - min_cell_lat),
        abs(cell_lat - max_cell_lat),
        abs(cell_lon - min_cell_lon),
        abs(cell_lon - max_cell_lon),
    )
    if max_distance_km is not None:
        # 1セルの物理的な最小の幅で割る（切り上げ）。最小で割ることで、まだ範囲内にある
        # Nodeをリング不足で取りこぼさない。
        max_radius = min(
            max_radius, math.ceil(max_distance_km / cell_size_km_lower_bound) + 1
        )
    while radius <= max_radius:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue  # 内側のリングは前回までのループで調べ済み
                nodes = index.buckets.get((cell_lat + dx, cell_lon + dy))
                if nodes is None:
                    continue
                if allowed is not None:
                    nodes = nodes[allowed[nodes]]
                    if len(nodes) == 0:
                        continue
                distances = haversine_distance_km_array(index.latitude[nodes], index.longitude[nodes], point)
                best = int(np.argmin(distances))
                if nearest_distance is None or distances[best] < nearest_distance:
                    nearest_distance = float(distances[best])
                    nearest_node = int(nodes[best])
        if nearest_distance is not None and radius * cell_size_km_lower_bound >= nearest_distance:
            break
        radius += 1
    if max_distance_km is not None and (nearest_distance is None or nearest_distance > max_distance_km):
        return None
    return nearest_node

# --- ターン展開（状態＝有向Edge、辺＝ターン） ---


@dataclass(frozen=True)
class TurnCostSpec:
    """ターン1回の時間損失（秒）と、直進とみなす方位差の上限（度）。

    探索のコストも秒のため、換算せずそのまま足せる（「右折1回＝何秒余計にかかるか」として
    走行時間と直接比べられる）。

    左折・右折・Uターン・直進とみなす方位差・上位の道の横断/右左折は、いずれも走ってみて
    決める値のため`domain/tuning.py`が宣言する。既定を組み立てるのは`current_turn_cost()`で、
    ここにフィールドの既定値は置かない——既定が分かれると、片方だけが変わる。
    """

    left_seconds: float
    right_seconds: float
    uturn_seconds: float
    straight_max_deg: float
    # 進入した道より上位の階級の道と交わる**信号の無い**交差点で追加する秒数（横断＝直進で
    # 渡る場合と、右左折で入る場合）。信号のある交差点の待ちは停止密度の材料が走行モデルへ
    # 運ぶ（`domain/traffic.py: stop_seconds`）ため、そちらで数え、ここでは足さない
    # ——両方で足すと同じ待ちを二重に数える（`docs/architecture/design-principles.md`構造仕様13）。
    # ここが担うのは「信号が無いのに上位の道を渡る・そこへ入る」ときの、車列の切れ目を
    # 待つ時間である。
    major_crossing_seconds: float
    major_turn_seconds: float


def current_turn_cost() -> TurnCostSpec:
    """いま効いている較正値で組み立てたターンの費用。

    **呼ぶたびに組み立てる**——プロセス内に束ねると、管理画面から変えた値が効かない。
    """
    return TurnCostSpec(
        left_seconds=tuning_value("turn.left_seconds"),
        right_seconds=tuning_value("turn.right_seconds"),
        uturn_seconds=tuning_value("turn.uturn_seconds"),
        straight_max_deg=tuning_value("turn.straight_max_deg"),
        major_crossing_seconds=tuning_value("turn.major_crossing_seconds"),
        major_turn_seconds=tuning_value("turn.major_turn_seconds"),
    )


@dataclass
class TurnExpandedStructure:
    """有向Edgeを状態、ターンを辺として見た構造。

    `CsrGraphStructure`と同じくEdgeの重みは持たない（リクエストごとに変わるため）。グラフを
    物理的に作り直さず、遷移は`CsrGraphStructure`から導く——ターンの費用はノード側の性質
    （方位差・信号の有無）だけで決まり、状態の数を増やさずに表せる。行＝遷移元の状態
    （区間の番号）、列＝遷移先の状態で、起点には依存しない。
    """

    state_count: int
    # 状態ごとの遷移範囲。長さ state_count + 1。
    indptr: np.ndarray
    # 遷移先の状態（区間の番号）。
    target_state: np.ndarray
    # 遷移ごとのターンの時間損失（秒）。
    turn_seconds: np.ndarray
    # 状態（有向Edge）の始点・終点Node index。
    edge_from: np.ndarray
    edge_to: np.ndarray
    # 逆向き（転置）の遷移。目的地から遡る木が使う。最初に要求されたときだけ組む
    # （前向きだけの探索では要らないため）。ターンの待ちは元の進行方向のまま運ぶ。
    _reverse: tuple[np.ndarray, np.ndarray, np.ndarray] | None = field(
        default=None, repr=False, compare=False
    )

    def reverse_transitions(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """`(indptr, source_state, turn_seconds)`を遷移の向きを反転した形で返す。

        前向きの遷移「状態a→状態b、待ちw」を、後ろ向きでは「状態b→状態a、待ちw」として
        並べ替える（待ちは元の進行方向で決まるため値は変えない）。
        """
        if self._reverse is None:
            source = np.repeat(
                np.arange(self.state_count, dtype=np.int64), np.diff(self.indptr)
            )
            order = np.argsort(self.target_state, kind="stable")
            counts = np.bincount(self.target_state, minlength=self.state_count)
            indptr = np.zeros(self.state_count + 1, dtype=np.int64)
            np.cumsum(counts, out=indptr[1:])
            self._reverse = (indptr, source[order], self.turn_seconds[order])
        return self._reverse


def edge_bearings(
    lazy_graph: LazyRoadGraph, bearing_deg: np.ndarray, node_lat: np.ndarray, node_lon: np.ndarray
) -> np.ndarray:
    """区間の番号順の方位（度）。`bearing_deg`（元の行の順、折れ線から求めた実際の向き）を
    使い、NaNの区間だけ両端のNode座標から補う。"""
    bearings = np.asarray(bearing_deg, dtype=float)[lazy_graph.edge_rows].copy()
    for index in np.flatnonzero(np.isnan(bearings)).tolist():
        tail, head = int(lazy_graph.edge_from[index]), int(lazy_graph.edge_to[index])
        bearings[index] = bearing_between(
            Coordinates(latitude=float(node_lat[tail]), longitude=float(node_lon[tail])),
            Coordinates(latitude=float(node_lat[head]), longitude=float(node_lon[head])),
        )
    return bearings


def _turn_seconds_for(
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
    edge_rank: np.ndarray,
    spec: TurnCostSpec,
    node_has_signal: np.ndarray,
    node_db_rank: np.ndarray,
) -> TurnExpandedStructure:
    """`CsrGraphStructure`から、状態＝有向Edgeの遷移構造を組む。

    状態`e`の遷移先は「`e`の終点Nodeから出る有向Edge」で、遷移の数は
    Σ(入次数×出次数)。`e`の始点へ戻る遷移はUターンとして扱う（禁止はしない——袋小路からの
    折り返しに必要なため、費用で抑える）。

    ターンの費用に要る入力はすべて引数で受け取り、**`None`を受け取らない**。既定を持たせても
    実行時に`None`を許しても、渡し忘れた呼び出しが「上位の道の横断に待ちが付かない」構造を
    黙って作る（例外もログも出ない）。
    """
    state_count = len(lazy_graph.edge_rows)
    edge_from = lazy_graph.edge_from
    edge_to = lazy_graph.edge_to

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
    turn_seconds = _turn_seconds_for(bearing_deg[source], bearing_deg[target_state], is_uturn, spec)

    # ノードの階級は、読み込んだ部分グラフに現れる道から導く。DB側の事前集計値
    # （`node_materials.max_highway_rank`）があれば大きい方を採る——bboxの外へはみ出した
    # 上位の道は部分グラフに現れないため、導出だけでは取りこぼす。未集計の0は導出値を
    # 下回るので、バッチ未実行でも結果は変わらない。
    node_rank = np.zeros(csr.node_count, dtype=np.int64)
    np.maximum.at(node_rank, edge_to, edge_rank)
    np.maximum.at(node_rank, edge_from, edge_rank)
    node_rank = np.maximum(node_rank, node_db_rank)
    # 「自分より上位」だけでなく「そもそも待ちの要る階級か」も見る
    # （`MAJOR_CROSSING_MIN_RANK`、domain/traffic.py）。
    target_node_rank = node_rank[edge_to[source]]
    crosses_major = (
        (target_node_rank > edge_rank[source])
        & (target_node_rank >= MAJOR_CROSSING_MIN_RANK)
        # 信号のある交差点では足さない（待ちは停止密度の材料が走行モデルへ運ぶ）。
        # 未集計なら全ノードが「信号なし」で、この列の導入前と同じ結果になる。
        & ~node_has_signal[edge_to[source]]
    )
    delta = (bearing_deg[target_state] - bearing_deg[source] + 180.0) % 360.0 - 180.0
    straight = np.abs(delta) <= spec.straight_max_deg
    turn_seconds = turn_seconds + np.where(
        crosses_major & ~is_uturn,
        np.where(straight, spec.major_crossing_seconds, spec.major_turn_seconds),
        0.0,
    )

    return TurnExpandedStructure(
        state_count=state_count, indptr=new_indptr, target_state=target_state,
        turn_seconds=turn_seconds, edge_from=edge_from, edge_to=edge_to,
    )


# 探索の優先度キュー（numpy配列のバイナリヒープ）。順位のキー・状態・積んだ時点のコスト`g`の列と、
# `g`の列を使うか。`g`の列を使わないヒープはキーそのものを`g`として扱う。
_Heap = tuple[np.ndarray, np.ndarray, np.ndarray, bool]


def _kernel_array(values: np.ndarray, dtype: type) -> np.ndarray:
    """JITした探索へ渡す配列を、1つの型（dtype・C順・書き込み可）へ揃える。揃っている配列は写さない。

    numbaは引数の型（dtype・並び・読み取り専用か）ごとに別々にコンパイルする。揃えずに渡すと、
    イメージの組み立てで焼いたコンパイル結果（`compile_search_kernels`）と型の違う呼び出しが、
    本番の最初のルート生成でコンパイルを払う。
    """
    array: np.ndarray = np.ascontiguousarray(values, dtype=dtype)
    return array if array.flags.writeable else array.copy()


@njit(cache=True, inline="always")
def _empty_heap(capacity: int, carries_g: bool) -> _Heap:
    """空のヒープを作る。`carries_g`はキーが`g`と別の値になる探索（A*のキーは`g`＋下界）だけが立てる。

    容量は最低1にする——伸長は要素数を倍にするため、容量0からは伸びない。
    """
    capacity = max(capacity, 1)
    return (
        np.empty(capacity),
        np.empty(capacity, dtype=np.int64),
        np.empty(capacity if carries_g else 0),
        carries_g,
    )


@njit(cache=True, inline="always")
def _grown(values: np.ndarray, size: int) -> np.ndarray:
    grown = np.empty(size * 2, dtype=values.dtype)
    grown[:size] = values
    return grown


@njit(cache=True, inline="always")
def _heap_push(heap: _Heap, size: int, key: float, state: int, g: float = math.nan) -> tuple[_Heap, int]:
    """エントリを1つ積み、（伸ばしたかもしれない）ヒープと新しい要素数を返す。`g`は`g`の列を
    使うヒープにだけ渡す（使わないヒープでは取り出しがキーを`g`として返す）。

    **満杯なら倍へ伸ばす**。コストが時刻で変わると「各状態は一度だけ確定する」が成り立たず
    （確定済みの状態が、後から別の時刻ビンを通る安い経路で更新されうる）、押し込み回数が
    遷移数で頭打ちにならない。JITは配列の境界を検査しないため、上限を決め打つと超えた瞬間に
    例外ではなく範囲外書き込みになる。
    """
    heap_key, heap_state, heap_g, carries_g = heap
    if size == heap_key.shape[0]:
        heap_key = _grown(heap_key, size)
        heap_state = _grown(heap_state, size)
        if carries_g:
            heap_g = _grown(heap_g, size)
    j = size
    while j > 0:
        parent = (j - 1) // 2
        if heap_key[parent] <= key:
            break
        heap_key[j] = heap_key[parent]
        heap_state[j] = heap_state[parent]
        if carries_g:
            heap_g[j] = heap_g[parent]
        j = parent
    heap_key[j] = key
    heap_state[j] = state
    if carries_g:
        heap_g[j] = g
    return (heap_key, heap_state, heap_g, carries_g), size + 1


@njit(cache=True, inline="always")
def _heap_pop(heap: _Heap, size: int) -> tuple[float, int, int]:
    """キー最小のエントリを取り出し、その`g`・状態と新しい要素数を返す。空で呼ばない。"""
    heap_key, heap_state, heap_g, carries_g = heap
    g = heap_g[0] if carries_g else heap_key[0]
    state = heap_state[0]
    size -= 1
    key = heap_key[size]
    last_state = heap_state[size]
    last_g = heap_g[size] if carries_g else key
    j = 0
    while True:
        child = 2 * j + 1
        if child >= size:
            break
        right = child + 1
        if right < size and heap_key[right] < heap_key[child]:
            child = right
        if not heap_key[child] < key:
            break
        heap_key[j] = heap_key[child]
        heap_state[j] = heap_state[child]
        if carries_g:
            heap_g[j] = heap_g[child]
        j = child
    heap_key[j] = key
    heap_state[j] = last_state
    if carries_g:
        heap_g[j] = last_g
    return g, state, size


def time_bin_of(travelled: float, bin_seconds: float, bin_count: int) -> int:
    """出発からの経過時間`travelled`（秒）が落ちる時刻ビン。範囲外は端のビンへ寄せる。区間の表示も経路を
    たどってこれで同じビンを選ぶ（探索と表示が別のビンを読むと、同じ区間の風が食い違う）。

    探索の中では同じ本体をJITした`_time_bin_of_kernel`を展開する。Pythonから呼ぶ側がJITの版を呼ぶと、
    プロセスで最初の呼び出しがイメージに焼いていないコンパイルを払う。
    """
    time_bin = int(travelled / bin_seconds)
    if time_bin >= bin_count:
        return bin_count - 1
    if time_bin < 0:
        return 0
    return time_bin


_time_bin_of_kernel = njit(cache=True, inline="always")(time_bin_of)


@njit(cache=True)
def _turn_expanded_dijkstra(
    indptr: np.ndarray,
    target_state: np.ndarray,
    turn_seconds: np.ndarray,
    edge_cost: np.ndarray,
    edge_seconds: np.ndarray,
    edge_length_m: np.ndarray,
    bin_seconds: float,
    entry_states: np.ndarray,
    cost_limit: float,
    capacity: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """状態＝有向区間・辺＝ターンの一対全Dijkstra（JITコンパイル）。

    `entry_states`（始点から出る区間、または目的地へ入る区間）をその区間自身のコストで
    種にし、コスト`cost_limit`を超えた時点で打ち切る。実距離と素の所要時間は緩和のたびに
    そのまま積むため、前任者を遡り直す積算が要らない。

    `edge_cost`・`edge_seconds`は`(時刻ビン, 状態)`。`_turn_expanded_astar`と同じ1ラベル法で、
    状態ごとにコスト最小の1本だけを保つ。
    """
    state_count = edge_length_m.shape[0]
    bin_count = edge_cost.shape[0]
    best = np.full(state_count, np.inf)
    arrival = np.full(state_count, np.inf)
    length = np.full(state_count, np.nan)
    predecessor = np.full(state_count, -1, dtype=np.int64)
    heap = _empty_heap(capacity, False)
    size = 0

    for i in range(entry_states.shape[0]):
        state = entry_states[i]
        g = edge_cost[0, state]
        if not np.isfinite(g) or g > cost_limit or g >= best[state]:
            continue
        best[state] = g
        arrival[state] = edge_seconds[0, state]
        length[state] = edge_length_m[state]
        heap, size = _heap_push(heap, size, g, state)

    while size > 0:
        g, state, size = _heap_pop(heap, size)
        if g > best[state]:
            continue
        travelled = arrival[state]
        time_bin = _time_bin_of_kernel(travelled, bin_seconds, bin_count)
        for entry in range(indptr[state], indptr[state + 1]):
            nxt = target_state[entry]
            cost = edge_cost[time_bin, nxt]
            if not np.isfinite(cost):
                continue
            wait = turn_seconds[entry]
            next_g = g + cost + wait
            if next_g > cost_limit or next_g >= best[nxt]:
                continue
            best[nxt] = next_g
            arrival[nxt] = travelled + edge_seconds[time_bin, nxt] + wait
            length[nxt] = length[state] + edge_length_m[nxt]
            predecessor[nxt] = state
            heap, size = _heap_push(heap, size, next_g, nxt)
    return best, predecessor, length, arrival


@dataclass
class TurnExpandedTree:
    """状態＝有向Edgeの一対全最短経路木。`state_*`は区間の番号順、
    `node_*`はNode index順。

    「起点Nodeのコスト0」という状態を持たない——状態の空間に
    「まだ走っていない」が無いため、起点Nodeの`node_cost`は「起点へ戻ってくるコスト」に
    なる。起点を0として扱いたい呼び出し元は自分で上書きする。
    """

    # 仮想始点から各状態への最小コスト。到達不能はinf。
    state_cost: np.ndarray
    # 木の親となる状態。始点の区間・到達不能は-1。
    predecessor: np.ndarray
    # 木に沿った実距離（m）の積算。到達不能はNaN。
    state_length_m: np.ndarray
    # 木に沿った所要時間（秒）の積算。到達不能はinf。
    state_seconds: np.ndarray
    # Nodeごとの最小コストと、そのコストでNodeへ入る状態（到達不能は-1）。
    node_cost: np.ndarray
    node_best_state: np.ndarray
    # `node_best_state`に対応する実距離（m）・所要時間（秒）。到達不能はNaN。
    node_length_m: np.ndarray
    node_seconds: np.ndarray
    # `predecessor`のPython list版（numpy配列への添字アクセスより、経路復元の
    # ループが速い）。既定値を持たせない——省略できると、渡し忘れた木が黙って
    # 「どの状態からも経路が1本も辿れない」ふるまいになる。
    predecessor_list: list[int] = field(repr=False, compare=False)


def build_turn_expanded_tree(
    structure: TurnExpandedStructure,
    edge_cost: np.ndarray,
    edge_length_m: np.ndarray,
    entry_state_indices: np.ndarray,
    node_count: int,
    *,
    reverse: bool = False,
    cost_limit: float = np.inf,
    edge_seconds: np.ndarray,
    bin_seconds: float = np.inf,
) -> TurnExpandedTree:
    """状態＝有向Edgeの一対全Dijkstra（numba、前任者付き）。

    `reverse=True`は遷移の向きだけを反転する（ターンの待ちは元の進行方向のまま）。
    「その区間から目的地まで」のコストが求まる。

    `edge_cost`は1次元（時刻に依存しない）か`(時刻ビン, 状態)`の2次元で、素の所要時間
    `edge_seconds`を同じ形で渡す。ビンが2本以上なら`bin_seconds`も渡す（`turn_expanded_shortest_path`と
    同じ契約）。**逆向きの木は時刻ビンを使えない**——目的地から遡るため各状態の到達時刻が決まらない。
    呼び出し元は1本のビンで呼ぶこと（`reverse=True`へ複数ビンを渡すと`ValueError`）。
    """
    state_count = structure.state_count
    cost_bins, seconds_bins = _time_bin_arrays(
        "build_turn_expanded_tree", edge_cost, edge_seconds, bin_seconds
    )
    if reverse and cost_bins.shape[0] > 1:
        # 逆向きの木の`arrival`は「そこから目的地までの残り時間」で、出発からの経過時間では
        # ない。ビンを引くとその残り時間で引かれ、例外もNaNも出ないまま時刻が反転した条件で
        # 評価した経路が返る。
        raise ValueError(
            "build_turn_expanded_tree(reverse=True) cannot use time bins: "
            f"got {cost_bins.shape[0]} bins (pass a single bin; the reverse tree has no arrival clock)"
        )
    if reverse:
        indptr, target_state, transition_seconds = structure.reverse_transitions()
    else:
        indptr, target_state, transition_seconds = (
            structure.indptr, structure.target_state, structure.turn_seconds
        )
    started = time.perf_counter()
    state_cost, predecessor, state_length_m, state_seconds = _turn_expanded_dijkstra(
        _kernel_array(indptr, np.int64), _kernel_array(target_state, np.int64),
        _kernel_array(transition_seconds, np.float64),
        _kernel_array(cost_bins, np.float64), _kernel_array(seconds_bins, np.float64),
        _kernel_array(edge_length_m, np.float64), float(bin_seconds),
        _kernel_array(entry_state_indices, np.int64), float(cost_limit),
        len(entry_state_indices) + _HEAP_INITIAL_SLACK,
    )
    dijkstra_ms = (time.perf_counter() - started) * 1000

    fold_started = time.perf_counter()
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
    node_seconds = np.full(node_count, np.nan)
    finite_best = best_states[np.isfinite(state_cost[best_states])]
    node_best_state[incoming[finite_best]] = finite_best
    node_cost[incoming[finite_best]] = state_cost[finite_best]
    node_length_m[incoming[finite_best]] = state_length_m[finite_best]
    node_seconds[incoming[finite_best]] = state_seconds[finite_best]

    logger.info(
        "turn_expanded_tree reverse=%s states=%d bins=%d dijkstra_ms=%.0f fold_ms=%.0f",
        reverse, state_count, cost_bins.shape[0], dijkstra_ms,
        (time.perf_counter() - fold_started) * 1000,
    )
    return TurnExpandedTree(
        state_cost=state_cost, predecessor=predecessor, state_length_m=state_length_m,
        state_seconds=state_seconds, node_cost=node_cost, node_best_state=node_best_state,
        node_length_m=node_length_m, node_seconds=node_seconds,
        predecessor_list=predecessor.tolist(),
    )


def _walk_predecessors(tree: TurnExpandedTree, state_index: int) -> list[int]:
    """`state_index`から木の始点まで前任者を辿った状態（＝Edge index）の列。"""
    edges: list[int] = []
    state = int(state_index)
    while state >= 0:
        edges.append(state)
        state = tree.predecessor_list[state]
    return edges


def turn_expanded_path_from_state(tree: TurnExpandedTree, state_index: int) -> list[int]:
    """前向き木で、始点→`state_index`の経路をEdge index列（進行順）で返す。状態がそのまま
    Edge indexのため、`(parent, current)`からEdgeを引き直す必要がない。"""
    edges = _walk_predecessors(tree, state_index)
    edges.reverse()
    return edges


def turn_expanded_path_from_state_to_source(tree: TurnExpandedTree, state_index: int) -> list[int]:
    """`reverse=True`で作った木で、`state_index`から木の始点（目的地）までの経路を進行順で
    返す。逆向きの木では前任者を辿ることが目的地へ近づくことに当たるため、反転しない。"""
    return _walk_predecessors(tree, state_index)


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
    # 同じ経路の所要時間（秒）。木が所要時間を積んでいなければNaN。
    seconds: np.ndarray
    # 繋いだときの前向き側・後ろ向き側の状態（Edge index）。繋げないNodeは-1。
    forward_state: np.ndarray
    backward_state: np.ndarray


def combine_forward_backward_at_nodes(
    structure: TurnExpandedStructure,
    forward: TurnExpandedTree,
    backward: TurnExpandedTree,
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
    total = forward.state_cost[source] + structure.turn_seconds + backward.state_cost[target]
    length = forward.state_length_m[source] + backward.state_length_m[target]
    # 繋ぎ目のターンの待ちも所要時間に入る（コストと同じ扱い）。
    seconds_total = forward.state_seconds[source] + structure.turn_seconds + backward.state_seconds[target]
    junction_node = structure.edge_to[source]

    cost = np.full(node_count, np.inf)
    length_m = np.full(node_count, np.nan)
    seconds = np.full(node_count, np.nan)
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
        seconds[best_nodes] = seconds_total[best]
        forward_state[best_nodes] = source[best]
        backward_state[best_nodes] = target[best]
    return NodeJunction(
        cost=cost, length_m=length_m, seconds=seconds,
        forward_state=forward_state, backward_state=backward_state,
    )


def _as_time_bins(caller: str, values: np.ndarray) -> np.ndarray:
    """1次元のEdge配列を`(1, 状態)`の時刻ビン形式へ揃える（2次元ならそのまま）。

    3次元以上は送出する。黙って`(1, n)`へ潰すと、後段のビン数の食い違いの検査もすり抜け、
    JITした探索が範囲外を読む。
    """
    array = np.asarray(values, dtype=np.float64)
    if array.ndim > 2:
        raise ValueError(f"{caller}: expected a 1-D or 2-D array, got {array.shape}")
    return array if array.ndim == 2 else array.reshape(1, -1)


def _time_bin_arrays(
    caller: str, edge_cost: np.ndarray, edge_seconds: np.ndarray, bin_seconds: float
) -> tuple[np.ndarray, np.ndarray]:
    """コスト配列と素の所要時間配列を`(時刻ビン, 状態)`へ揃え、時刻で引く契約を確かめる。

    ビンが2本以上あるとき、探索は出発からの経過時間でビンを選ぶ。そのためビンの幅が要り、
    欠けると全区間が先頭のビンに落ちて**時刻ごとの風が黙って効かなくなる**——例外もNaNも
    出さずに結果だけが変わる。

    2つの配列の形が違えば送出する。JITした探索は配列の境界を検査しないため、ビン数が
    食い違うと範囲外の読み出しになる。
    """
    cost_bins = _as_time_bins(caller, edge_cost)
    if cost_bins.shape[0] > 1:
        if not math.isfinite(bin_seconds) or bin_seconds <= 0:
            raise ValueError(
                f"{caller}: time-binned edge_cost needs a positive finite bin_seconds "
                f"(got {bin_seconds}; every state would fall into the first bin)"
            )
    seconds_bins = _as_time_bins(caller, edge_seconds)
    if seconds_bins.shape != cost_bins.shape:
        raise ValueError(
            f"{caller}: edge_seconds{seconds_bins.shape} does not match edge_cost{cost_bins.shape}"
        )
    return cost_bins, seconds_bins


@njit(cache=True)
def _turn_expanded_astar(
    indptr: np.ndarray,
    target_state: np.ndarray,
    turn_seconds: np.ndarray,
    edge_to: np.ndarray,
    edge_cost: np.ndarray,
    edge_seconds: np.ndarray,
    bin_seconds: float,
    node_heuristic: np.ndarray,
    origin_states: np.ndarray,
    goal_node: int,
    capacity: int,
) -> tuple[np.ndarray, int]:
    """状態＝有向区間・辺＝ターンのA*（JITコンパイル）。

    ヒープには`f = g + 目的地までの所要時間の下界`をキーとして、積んだ時点の`g`と一緒に
    積み、取り出したときに`g`が`best`より大きければ古いエントリとして捨てる。戻り値は
    前任者の配列と、目的地へ入った状態（到達不能なら-1）。

    `edge_cost`・`edge_seconds`は`(時刻ビン, 状態)`の2次元で、出発からの経過時間を
    `bin_seconds`で割ったビンの行を引く。時刻に依存しない探索はビン1本で呼ぶ。
    **状態ごとに保つラベルはコスト最小の1本だけ**（1ラベル法）——コストは時間そのものでは
    ないため、「コストは高いが早く着く」経路が後でコスト最小になる可能性を捨てる近似になる。
    """
    state_count = edge_to.shape[0]
    bin_count = edge_cost.shape[0]
    best = np.full(state_count, np.inf)
    arrival = np.full(state_count, np.inf)
    predecessor = np.full(state_count, -1, dtype=np.int64)
    heap = _empty_heap(capacity, True)
    size = 0

    for i in range(origin_states.shape[0]):
        state = origin_states[i]
        g = edge_cost[0, state]
        if not np.isfinite(g) or g >= best[state]:
            continue
        best[state] = g
        arrival[state] = edge_seconds[0, state]
        f = g + node_heuristic[edge_to[state]]
        heap, size = _heap_push(heap, size, f, state, g)

    goal_state = -1
    while size > 0:
        g, state, size = _heap_pop(heap, size)
        if g > best[state]:
            continue
        if edge_to[state] == goal_node:
            goal_state = state
            break
        travelled = arrival[state]
        time_bin = _time_bin_of_kernel(travelled, bin_seconds, bin_count)
        for entry in range(indptr[state], indptr[state + 1]):
            nxt = target_state[entry]
            cost = edge_cost[time_bin, nxt]
            if not np.isfinite(cost):
                continue
            wait = turn_seconds[entry]
            next_g = g + cost + wait
            if next_g >= best[nxt]:
                continue
            best[nxt] = next_g
            arrival[nxt] = travelled + edge_seconds[time_bin, nxt] + wait
            predecessor[nxt] = state
            next_f = next_g + node_heuristic[edge_to[nxt]]
            heap, size = _heap_push(heap, size, next_f, nxt, next_g)
    return predecessor, goal_state


def turn_expanded_shortest_path(
    structure: TurnExpandedStructure,
    edge_cost: np.ndarray,
    node_heuristic: np.ndarray,
    origin_states: np.ndarray,
    goal_node_index: int,
    edge_seconds: np.ndarray,
    bin_seconds: float = np.inf,
) -> list[int] | None:
    """起点から出る区間`origin_states`から`goal_node_index`までの最小コスト経路を、
    Edge index列（進行順）で返す。到達不能ならNone。

    **コストの単位は秒**（`edge_cost`は区間ごとの体感所要時間、ターンの待ちも秒）。
    `node_heuristic`はNodeごとの目的地までの所要時間の下界（秒）で、呼び出し元が
    「直線距離 ÷ 出せる最大速度」から作る——実経路は直線より長く、実際の速度は上限以下の
    ため下界になる。

    `edge_cost`は1次元（時刻に依存しない）か`(時刻ビン, 状態)`の2次元で、素の所要時間
    `edge_seconds`を同じ形で渡す——探索が出発からの経過時間を持ち回り、その時刻のビンから
    コストと所要時間を引く。ビンが2本以上なら幅`bin_seconds`も渡す。
    """
    cost_bins, seconds_bins = _time_bin_arrays(
        "turn_expanded_shortest_path", edge_cost, edge_seconds, bin_seconds
    )
    capacity = len(origin_states) + _HEAP_INITIAL_SLACK
    predecessor, goal_state = _turn_expanded_astar(
        _kernel_array(structure.indptr, np.int64), _kernel_array(structure.target_state, np.int64),
        _kernel_array(structure.turn_seconds, np.float64), _kernel_array(structure.edge_to, np.int64),
        _kernel_array(cost_bins, np.float64), _kernel_array(seconds_bins, np.float64), float(bin_seconds),
        _kernel_array(node_heuristic, np.float64),
        _kernel_array(origin_states, np.int64), int(goal_node_index), capacity,
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


def compile_search_kernels() -> None:
    """一対全木と2点間探索のJITを、最小の道路網で1回ずつ呼んでコンパイルする。

    `@njit(cache=True)`の結果はこのファイルの隣の`__pycache__`に残り、別のプロセスはそこから読む。
    イメージの組み立て（`backend/Dockerfile`）で呼び、入れ替えたコンテナの最初のルート生成が
    コンパイルを待たないようにする。探索の入口が引数の型を揃える（`_kernel_array`）ため、ここで
    作る入力は形が合えばよい。焼くのはここがPythonから呼ぶJITだけなので、本番の経路がPythonから呼ぶJITも
    この2本に限る（部品は探索の中へ展開し、Pythonからは素の関数を呼ぶ）。
    """
    lazy_graph = build_lazy_road_graph(np.array([0, 1]), np.array([1, 0]), 2)
    statics = build_search_graph_statics(lazy_graph, np.ones(2))
    structure = build_turn_expanded_structure(
        statics.csr, lazy_graph, np.zeros(2), np.zeros(2, dtype=np.int64), current_turn_cost(),
        np.zeros(2, dtype=bool), np.zeros(2, dtype=np.int64),
    )
    cost = np.ones((1, 2))
    origin_states = np.array([0])
    build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, origin_states, lazy_graph.node_count, edge_seconds=cost
    )
    turn_expanded_shortest_path(structure, cost, np.zeros(2), origin_states, 0, edge_seconds=cost)
