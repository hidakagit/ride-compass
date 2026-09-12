"""改善計画T790段階1: 訪問状態数の実測。

状態＝交差点ノード（現行）と、状態＝有向区間＋ターンコスト＋到達時刻ラベル（再設計案）で
同じ起点→目的地を解き、探索が訪れる状態数を比べる。「探索時間＝訪問状態数×1状態あたりの
コスト」と分解したときの前者（実装基盤に依存しない量）を測るのが目的で、探索そのものの
速さを測るものではない（自前A*はPython実装のため現行のrustworkx C実装より遅い）。

グラフは辺基準へ展開せず、遷移は元のCSR構造から導いてターンの費用だけを方位差から求める。

時刻依存コストは段階1では模擬する（ビンごとに一定率を掛けた配列）。実データの風を入れるには
ビンごとに`_LegCostComposer.compose`をかけ直せばよく、探索側の構造は変わらない。

`benchmarks/`配下の他スクリプトと異なり実DB接続が必須（`DATABASE_URL`、backend/.env）。
必ず読み取り経路のみを通す（bench_t536と同じ仕組み。`T790_BENCH_ALLOW_UNSPLIT=1`で
無効化できるがdev機以外では使わない）。

使い方: `python -m benchmarks.bench_t790_turn_expanded`
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import math
import os
import time

import numpy as np

from app.domain.geo import bearing_between, haversine_distance_km, haversine_distance_km_array
from app.domain.graph import RoadGraphLike
from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

from app.domain.routing import (
    build_shortest_path_tree,
    find_nearest_node_indexed,
    shortest_path_node_ids_lazy,
)
from app.infrastructure.database import get_route_generation_session_factory
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.road_graph_engine import PREVIEW_BBOX_MARGIN_KM, _bbox_covering_points
from benchmarks._route_generation_service import refresh_axis_registry, route_generator_session

# dev DBのroad_edges範囲（BOX(139.601 35.552, 139.923 35.801)）に収まる20km級の区間。
ORIGIN = Coordinates(latitude=35.5617, longitude=139.7161)
DESTINATION = Coordinates(latitude=35.7528, longitude=139.7386)
DISTANCE_KM = 22.0
ASSUMED_SPEED_KMH = 20.0
ALLOW_UNSPLIT = os.environ.get("T790_BENCH_ALLOW_UNSPLIT", "0") == "1"

# ターン1回の時間損失（秒）。方位差で直進・左折・右折・Uターンを分ける暫定値で、段階1は
# 訪問状態数を測るのが目的のため較正はしない（較正はターンの費用を実装に入れる段階で行う）。
TURN_SECONDS_LEFT = 2.0
TURN_SECONDS_RIGHT = 12.0
TURN_SECONDS_UTURN = 60.0
STRAIGHT_MAX_DEG = 30.0

# 時刻依存コストの模擬。ビン幅と、ビンごとにコストへ掛ける率。
TIME_BIN_HOURS = 0.5
TIME_BIN_FACTORS = (1.00, 1.01, 1.02, 1.03, 1.04, 1.05)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("ridecompass.graph").setLevel(logging.INFO)


def _edge_bearings(
    graph: RoadGraphLike, edge_ids: list[str], edge_from: list[int], edge_to: list[int],
    node_lat: np.ndarray, node_lon: np.ndarray,
) -> list[float]:
    """各Edgeの方位（度）。`road_edges.bearing_deg`（折れ線から求めた実際の向き）を使い、
    欠損している分だけ両端のNode座標から補う。"""
    bearings: list[float] = []
    for index, edge_id in enumerate(edge_ids):
        edge = graph.edges.get(edge_id)
        value = edge.bearing_deg if edge is not None else None
        if value is None:
            tail, head = edge_from[index], edge_to[index]
            value = bearing_between(
                Coordinates(latitude=float(node_lat[tail]), longitude=float(node_lon[tail])),
                Coordinates(latitude=float(node_lat[head]), longitude=float(node_lon[head])),
            )
        bearings.append(float(value))
    return bearings


def _node_astar(
    indptr: list[int], indices: list[int], entry_edge: list[int], cost: list[float],
    origin_index: int, dest_index: int, heuristic: list[float],
) -> dict:
    """状態＝ノードのA*（現行と同じ状態の取り方）。訪問状態数を数えるための自前実装。"""
    best = [math.inf] * (len(indptr) - 1)
    best[origin_index] = 0.0
    prev_edge = [-1] * (len(indptr) - 1)
    prev_node = [-1] * (len(indptr) - 1)
    heap = [(heuristic[origin_index], 0.0, origin_index)]
    popped = 0
    pushed = 1
    started = time.perf_counter()
    while heap:
        _, g, u = heapq.heappop(heap)
        if g > best[u]:
            continue
        popped += 1
        if u == dest_index:
            break
        for entry in range(indptr[u], indptr[u + 1]):
            edge_index = entry_edge[entry]
            edge_cost = cost[edge_index]
            if edge_cost == math.inf:
                continue
            v = indices[entry]
            ng = g + edge_cost
            if ng < best[v]:
                best[v] = ng
                prev_edge[v] = edge_index
                prev_node[v] = u
                heapq.heappush(heap, (ng + heuristic[v], ng, v))
                pushed += 1
    elapsed_ms = (time.perf_counter() - started) * 1000

    path_edges: list[int] = []
    node = dest_index if dest_index >= 0 else origin_index
    while node != origin_index and prev_node[node] >= 0:
        path_edges.append(prev_edge[node])
        node = prev_node[node]
    path_edges.reverse()
    return {
        "popped": popped, "pushed": pushed, "elapsed_ms": elapsed_ms,
        "cost": best[dest_index] if dest_index >= 0 else math.inf, "path_edges": path_edges, "best": best,
    }


def _turn_seconds(from_bearing: float, to_bearing: float, is_uturn: bool) -> float:
    if is_uturn:
        return TURN_SECONDS_UTURN
    delta = (to_bearing - from_bearing + 180.0) % 360.0 - 180.0
    if abs(delta) <= STRAIGHT_MAX_DEG:
        return 0.0
    return TURN_SECONDS_LEFT if delta < 0 else TURN_SECONDS_RIGHT


def _turn_kind(from_bearing: float, to_bearing: float, is_uturn: bool) -> int:
    """経路の右左折を数えるための分類（1=左折 2=右折 3=Uターン 0=直進）。ターンの費用を
    入れない比較でも同じ基準で数えられるよう、費用とは別に判定する。"""
    if is_uturn:
        return 3
    delta = (to_bearing - from_bearing + 180.0) % 360.0 - 180.0
    if abs(delta) <= STRAIGHT_MAX_DEG:
        return 0
    return 1 if delta < 0 else 2


def _edge_astar(
    indptr: list[int], indices: list[int], entry_edge: list[int], cost_bins: list[list[float]],
    length_m: list[float], edge_from: list[int], edge_to: list[int], bearing: list[float],
    origin_index: int, dest_index: int, heuristic: list[float], speed_ms: float,
    turn_enabled: bool = True,
) -> dict:
    """状態＝有向区間・ラベル＝到達時刻のA*。ターンの費用は方位差から求め、コストは到達時刻の
    ビンで引き直す。グラフは辺基準へ展開せず、遷移は元のCSR構造から導く。"""
    edge_count = len(edge_from)
    best = [math.inf] * edge_count
    arrival_m = [math.inf] * edge_count
    prev_state = [-1] * edge_count
    turn_kind = [0] * edge_count  # 1=左折 2=右折 3=Uターン
    bin_count = len(cost_bins)
    bin_m = TIME_BIN_HOURS * 3600.0 * speed_ms

    heap: list[tuple[float, float, int]] = []
    for entry in range(indptr[origin_index], indptr[origin_index + 1]):
        edge_index = entry_edge[entry]
        edge_cost = cost_bins[0][edge_index]
        if edge_cost == math.inf:
            continue
        best[edge_index] = edge_cost
        arrival_m[edge_index] = length_m[edge_index]
        heapq.heappush(heap, (edge_cost + heuristic[indices[entry]], edge_cost, edge_index))

    popped = 0
    pushed = len(heap)
    goal_state = -1
    started = time.perf_counter()
    while heap:
        _, g, state = heapq.heappop(heap)
        if g > best[state]:
            continue
        popped += 1
        head = edge_to[state]
        if head == dest_index:
            goal_state = state
            break
        tail = edge_from[state]
        state_bearing = bearing[state]
        travelled = arrival_m[state]
        time_bin = int(travelled // bin_m)
        if time_bin >= bin_count:
            time_bin = bin_count - 1
        costs = cost_bins[time_bin]
        for entry in range(indptr[head], indptr[head + 1]):
            next_edge = entry_edge[entry]
            next_cost = costs[next_edge]
            if next_cost == math.inf:
                continue
            is_uturn = indices[entry] == tail
            seconds = _turn_seconds(state_bearing, bearing[next_edge], is_uturn) if turn_enabled else 0.0
            ng = g + next_cost + seconds * speed_ms
            if ng < best[next_edge]:
                best[next_edge] = ng
                arrival_m[next_edge] = travelled + length_m[next_edge]
                prev_state[next_edge] = state
                turn_kind[next_edge] = _turn_kind(state_bearing, bearing[next_edge], is_uturn)
                heapq.heappush(heap, (ng + heuristic[indices[entry]], ng, next_edge))
                pushed += 1
    elapsed_ms = (time.perf_counter() - started) * 1000

    path_edges: list[int] = []
    turns = {"left": 0, "right": 0, "uturn": 0}
    state = goal_state
    while state >= 0:
        path_edges.append(state)
        kind = turn_kind[state]
        if kind == 1:
            turns["left"] += 1
        elif kind == 2:
            turns["right"] += 1
        elif kind == 3:
            turns["uturn"] += 1
        state = prev_state[state]
    path_edges.reverse()
    return {
        "popped": popped, "pushed": pushed, "elapsed_ms": elapsed_ms,
        "cost": best[goal_state] if goal_state >= 0 else math.inf,
        "path_edges": path_edges, "turns": turns,
    }


def _path_length_km(path_edges: list[int], length_m: list[float]) -> float:
    return sum(length_m[edge_index] for edge_index in path_edges) / 1000.0


def _build_edge_expanded_csr(
    indptr: np.ndarray, indices: np.ndarray, entry_edge: np.ndarray, cost: np.ndarray,
    bearing: np.ndarray, edge_from: np.ndarray, edge_to: np.ndarray, origin_edges: np.ndarray,
    speed_ms: float, turn_enabled: bool,
) -> tuple[csr_matrix, int]:
    """有向区間を状態、ターンを辺として展開したCSRを組む（一対全木をscipyで張るため）。

    行=遷移元の有向区間、列=遷移先の有向区間、値=遷移先の区間コスト＋ターンの費用。最後の
    1行は仮想の始点で、起点から出る区間へその区間のコストで繋ぐ（複数の始点状態に別々の初期
    コストを与えるため）。0次フィルタで除外された区間（コストinf）への遷移は落とす。
    """
    edge_count = len(edge_to)
    out_start = indptr[edge_to]
    out_count = (indptr[edge_to + 1] - out_start).astype(np.int64)
    total = int(out_count.sum())
    row_start = np.zeros(edge_count + 1, dtype=np.int64)
    np.cumsum(out_count, out=row_start[1:])

    source = np.repeat(np.arange(edge_count, dtype=np.int64), out_count)
    entry_index = np.repeat(out_start.astype(np.int64), out_count) + (
        np.arange(total, dtype=np.int64) - np.repeat(row_start[:edge_count], out_count)
    )
    target = entry_edge[entry_index].astype(np.int64)
    target_head = indices[entry_index].astype(np.int64)

    if turn_enabled:
        delta = (bearing[target] - bearing[source] + 180.0) % 360.0 - 180.0
        is_uturn = target_head == edge_from[source]
        turn_seconds = np.where(
            is_uturn, TURN_SECONDS_UTURN,
            np.where(np.abs(delta) <= STRAIGHT_MAX_DEG, 0.0,
                     np.where(delta < 0, TURN_SECONDS_LEFT, TURN_SECONDS_RIGHT)),
        )
    else:
        turn_seconds = np.zeros(total)
    weight = cost[target] + turn_seconds * speed_ms

    keep = np.isfinite(weight)
    source = source[keep]
    target = target[keep]
    weight = weight[keep]
    origin_edges = origin_edges[np.isfinite(cost[origin_edges])]

    # 仮想始点（行番号edge_count）を末尾へ足す。
    source = np.concatenate([source, np.full(len(origin_edges), edge_count, dtype=np.int64)])
    target = np.concatenate([target, origin_edges.astype(np.int64)])
    weight = np.concatenate([weight, cost[origin_edges]])

    order = np.argsort(source, kind="stable")
    source = source[order]
    target = target[order]
    weight = weight[order]
    new_indptr = np.zeros(edge_count + 2, dtype=np.int64)
    np.cumsum(np.bincount(source, minlength=edge_count + 1), out=new_indptr[1:])
    matrix = csr_matrix((weight, target, new_indptr), shape=(edge_count + 1, edge_count + 1))
    return matrix, len(weight)


async def measure_one_to_all(context, lazy_graph, csr, cost_list, bearing, edge_from_list, edge_to_list,
                             origin_index: int, speed_ms: float) -> None:
    """一対全木（周回生成の基盤）を、状態＝ノードと状態＝有向区間で張り比べる。"""
    indptr = csr.indptr.astype(np.int64)
    indices = csr.indices.astype(np.int64)
    entry_edge = csr.entry_edge_index.astype(np.int64)
    cost_arr = np.asarray(cost_list, dtype=np.float64)
    bearing_arr = np.asarray(bearing, dtype=np.float64)
    edge_from_arr = np.asarray(edge_from_list, dtype=np.int64)
    edge_to_arr = np.asarray(edge_to_list, dtype=np.int64)
    origin_edges = entry_edge[indptr[origin_index]:indptr[origin_index + 1]]

    started = time.perf_counter()
    node_tree = build_shortest_path_tree(csr, cost_list, context.statics.edge_length_m, origin_index)
    node_tree_ms = (time.perf_counter() - started) * 1000
    node_reached = int(np.isfinite(node_tree.cost).sum())
    print(
        f"\n[一対全木 状態=ノード 現行 scipy] elapsed_ms={node_tree_ms:.0f} "
        f"states={csr.node_count} reached={node_reached}"
    )

    for turn_enabled in (False, True):
        started = time.perf_counter()
        matrix, transition_count = _build_edge_expanded_csr(
            indptr, indices, entry_edge, cost_arr, bearing_arr, edge_from_arr, edge_to_arr,
            origin_edges, speed_ms, turn_enabled,
        )
        build_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        distances = scipy_dijkstra(matrix, directed=True, indices=len(edge_to_arr))
        tree_ms = (time.perf_counter() - started) * 1000
        reached = int(np.isfinite(distances[:-1]).sum())
        memory_mb = (matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes) / 1024 / 1024
        label = "ターン費用あり" if turn_enabled else "ターン費用なし"
        print(
            f"[一対全木 状態=有向区間 {label}] build_ms={build_ms:.0f} dijkstra_ms={tree_ms:.0f} "
            f"states={len(edge_to_arr)} transitions={transition_count} reached={reached} "
            f"csr_mb={memory_mb:.1f}"
        )
        if not turn_enabled:
            # ターンの費用が無ければ、有向区間の木から導いたNodeごとの最小コストは
            # ノードの木と一致するはず（実装の正しさの確認）。
            per_node = np.full(csr.node_count, np.inf)
            np.minimum.at(per_node, edge_to_arr, distances[:-1])
            both = np.isfinite(per_node) & np.isfinite(node_tree.cost)
            if both.any():
                diff = np.abs(per_node[both] - node_tree.cost[both])
                signed = per_node[both] - node_tree.cost[both]
                worse = int((signed > 1e-6).sum())
                better = int((signed < -1e-6).sum())
                print(
                    f"  ノードの木との一致: 共通到達Node={int(both.sum())} "
                    f"最大差={diff.max():.3f} 平均差={diff.mean():.5f} "
                    f"有向区間の方が高い={worse}件 低い={better}件"
                )
                if worse or better:
                    index = int(np.argmax(np.abs(signed)))
                    node_index = int(np.flatnonzero(both)[index])
                    print(
                        f"  最大差のNode index={node_index} "
                        f"有向区間={per_node[node_index]:.1f} ノード={node_tree.cost[node_index]:.1f} "
                        f"入次数={int((edge_to_arr == node_index).sum())}"
                    )


async def main() -> None:
    straight_km = haversine_distance_km(ORIGIN, DESTINATION)
    print(f"origin={ORIGIN} destination={DESTINATION} straight_km={straight_km:.1f} (T790段階1)")
    # 目的地指定のprepareが使うbboxは起点・目的地の外接矩形＋固定マージンで、周回の円形bbox
    # （`assert_read_only_path`が見るもの）とは別。実際に触る範囲で未splitを判定する。
    bbox = _bbox_covering_points([ORIGIN, DESTINATION], PREVIEW_BBOX_MARGIN_KM)
    async with get_route_generation_session_factory()() as session:
        up_to_date = await RoadGraphRepository(session).is_split_up_to_date(bbox)
    print(f"bbox={bbox} is_split_up_to_date={up_to_date}")
    if not up_to_date and not ALLOW_UNSPLIT:
        raise SystemExit(
            "対象bboxが未split（再構築＝書き込み経路に入る）のため中断しました。"
            "T790_BENCH_ALLOW_UNSPLIT=1（本番では使わない）を指定してください。"
        )
    await refresh_axis_registry()

    async with route_generator_session(RoutePreference()) as generator:
        engine = generator._engine  # noqa: SLF001 （ベンチはprepare済みcontextを直接使う）
        prepare_started = time.perf_counter()
        context = await engine.prepare(ORIGIN, DISTANCE_KM, waypoints=[DESTINATION])
        prepare_ms = (time.perf_counter() - prepare_started) * 1000
        if context is None:
            raise SystemExit("prepareがcontextを返しませんでした（道路データ未整備）")

        lazy_graph = context.lazy_graph
        csr = context.statics.csr
        node_count = csr.node_count
        edge_count = len(lazy_graph.edge_ids)
        print(f"prepare_ms={prepare_ms:.0f} nodes={node_count} directed_edges={edge_count}")

        cost_list = context.legs[0].cost_list
        length_m = context.statics.edge_length_m

        def _has_finite_exit(node_id: str) -> bool:
            """0次フィルタを通る出口を持つNodeか。行き止まり・全除外のNodeへスナップすると
            探索が即座に打ち切られるため、起点・目的地ともこの条件で選び直す。"""
            index = lazy_graph.node_id_to_index[node_id]
            return any(
                cost_list[csr.entry_edge_index[entry]] != math.inf
                for entry in range(csr.indptr[index], csr.indptr[index + 1])
            )

        origin_node = find_nearest_node_indexed(context.node_index, ORIGIN, predicate=_has_finite_exit)
        dest_node = find_nearest_node_indexed(context.node_index, DESTINATION, predicate=_has_finite_exit)
        if origin_node is None or dest_node is None:
            raise SystemExit("起点または目的地をグラフの通行可能なNodeへスナップできませんでした")
        origin_index = lazy_graph.node_id_to_index[origin_node]
        dest_index = lazy_graph.node_id_to_index[dest_node]

        # 目的地側が起点と連結していない小さな塊へスナップされることがあるため、起点からの
        # 全探索で到達できたNodeの中から目的地に最も近いものを選び直す（本番の
        # `select_via_nodes`が前向き木で行う補正と同じ扱い）。
        reach = _node_astar(
            csr.indptr.tolist(), csr.indices.tolist(), csr.entry_edge_index.tolist(),
            cost_list, origin_index, -1, [0.0] * node_count,
        )
        reachable_cost = reach["best"]
        straight_m = haversine_distance_km_array(context.node_lat, context.node_lon, DESTINATION) * 1000.0
        masked = np.where(np.isfinite(reachable_cost), straight_m, np.inf)
        corrected_index = int(np.argmin(masked))
        if corrected_index != dest_index:
            print(
                f"目的地を到達可能なNodeへ補正: 直線距離{masked[corrected_index]:.0f}m "
                f"（到達可能Node数={int(np.isfinite(reachable_cost).sum())}/{node_count}）"
            )
            dest_index = corrected_index
            dest_node = lazy_graph.index_to_node_id[dest_index]

        origin_out = csr.indptr[origin_index + 1] - csr.indptr[origin_index]
        dest_in = sum(1 for v in csr.indices.tolist() if v == dest_index)
        origin_coord = context.graph.nodes[origin_node]
        dest_coord = context.graph.nodes[dest_node]
        print(
            f"origin_node={origin_node} ({origin_coord.latitude:.4f},{origin_coord.longitude:.4f}) "
            f"out_degree={origin_out} / dest_node={dest_node} "
            f"({dest_coord.latitude:.4f},{dest_coord.longitude:.4f}) in_degree={dest_in}"
        )
        finite_out = sum(
            1 for entry in range(csr.indptr[origin_index], csr.indptr[origin_index + 1])
            if cost_list[csr.entry_edge_index[entry]] != math.inf
        )
        print(f"起点から出る有限コストのEdge数={finite_out}（0次フィルタで全て除外されていないか）")

        edge_from_arr = np.zeros(edge_count, dtype=np.int64)
        edge_to_arr = np.zeros(edge_count, dtype=np.int64)
        for (tail, head), edge_index in lazy_graph.edge_index_by_node_pair.items():
            edge_from_arr[edge_index] = tail
            edge_to_arr[edge_index] = head

        heuristic = (haversine_distance_km_array(context.node_lat, context.node_lon, DESTINATION) * 1000.0).tolist()
        edge_from_list = edge_from_arr.tolist()
        edge_to_list = edge_to_arr.tolist()
        bearing = _edge_bearings(
            context.graph, lazy_graph.edge_ids, edge_from_list, edge_to_list, context.node_lat, context.node_lon
        )
        indptr = csr.indptr.tolist()
        indices = csr.indices.tolist()
        entry_edge = csr.entry_edge_index.tolist()
        length_list = np.asarray(length_m).tolist()
        speed_ms = ASSUMED_SPEED_KMH / 3.6
        cost_bins = [[c * factor for c in cost_list] for factor in TIME_BIN_FACTORS]

        started = time.perf_counter()
        reference_path = shortest_path_node_ids_lazy(
            lazy_graph, origin_node, dest_node,
            cost_list.__getitem__, heuristic.__getitem__,
        )
        rustworkx_ms = (time.perf_counter() - started) * 1000
        reference_edges = len(reference_path) - 1 if reference_path else 0
        print(f"\n[現行 rustworkx A*] elapsed_ms={rustworkx_ms:.0f} path_edges={reference_edges}")

        node_result = _node_astar(
            indptr, indices, entry_edge, cost_list, origin_index, dest_index, heuristic
        )
        print(
            f"[状態=ノード 自前A*] popped={node_result['popped']} pushed={node_result['pushed']} "
            f"elapsed_ms={node_result['elapsed_ms']:.0f} "
            f"path_edges={len(node_result['path_edges'])} "
            f"path_km={_path_length_km(node_result['path_edges'], length_list):.2f} "
            f"cost={node_result['cost']:.0f}"
        )
        print(f"  訪問割合: popped/nodes={node_result['popped'] / node_count:.2%}")

        edge_result = _edge_astar(
            indptr, indices, entry_edge, cost_bins, length_list,
            edge_from_list, edge_to_list, bearing,
            origin_index, dest_index, heuristic, speed_ms,
        )
        print(
            f"[状態=有向区間 自前A*] popped={edge_result['popped']} pushed={edge_result['pushed']} "
            f"elapsed_ms={edge_result['elapsed_ms']:.0f} "
            f"path_edges={len(edge_result['path_edges'])} "
            f"path_km={_path_length_km(edge_result['path_edges'], length_list):.2f} "
            f"cost={edge_result['cost']:.0f} turns={edge_result['turns']}"
        )
        print(f"  訪問割合: popped/directed_edges={edge_result['popped'] / edge_count:.2%}")
        if node_result["popped"]:
            print(f"  訪問状態数の比: 有向区間/ノード={edge_result['popped'] / node_result['popped']:.2f}倍")

        plain_result = _edge_astar(
            indptr, indices, entry_edge, cost_bins, length_list,
            edge_from_list, edge_to_list, bearing,
            origin_index, dest_index, heuristic, speed_ms, turn_enabled=False,
        )
        print(
            f"[状態=有向区間 ターン費用なし] popped={plain_result['popped']} "
            f"elapsed_ms={plain_result['elapsed_ms']:.0f} "
            f"path_edges={len(plain_result['path_edges'])} "
            f"path_km={_path_length_km(plain_result['path_edges'], length_list):.2f} "
            f"cost={plain_result['cost']:.0f} turns={plain_result['turns']}"
        )

        await measure_one_to_all(
            context, lazy_graph, csr, cost_list, bearing, edge_from_list, edge_to_list,
            origin_index, speed_ms,
        )


if __name__ == "__main__":
    asyncio.run(main())
