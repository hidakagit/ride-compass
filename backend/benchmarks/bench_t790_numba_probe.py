"""改善計画T790段階1: 時刻依存の一対全木をnumbaで書いた場合の実効速度を測る。

`bench_t790_turn_expanded.py`が`T790_DUMP`で書き出した配列だけを読み、DB接続もアプリの依存も
無い状態でPython版とnumba版を同じ入力に対して走らせて比べる。優先度キューはnumpy配列の
バイナリヒープとして自前で持つ（numbaは`heapq`を使えない）。

**numbaはこのリポジトリの依存に入っていない**（`requirements.txt`に無い）。実行するには
numbaを入れた環境が要る——開発機なら使い捨てのvenv、本番VMなら使い捨てコンテナへ
`pip install numba`してから走らせる（本番イメージは変えない）。

使い方: `python benchmarks/bench_t790_numba_probe.py <T790_DUMPで書き出したnpz>`
"""
import heapq
import math
import sys
import time

import numpy as np
from numba import njit

TIME_BIN_FACTORS = (1.00, 1.01, 1.02, 1.03, 1.04, 1.05)
TIME_BIN_HOURS = 0.5
SPEED_KMH = 20.0
TURN_LEFT_S = 2.0
TURN_RIGHT_S = 12.0
TURN_UTURN_S = 60.0
STRAIGHT_MAX_DEG = 30.0


def python_tree(indptr, indices, entry_edge, cost_bins, length_m, edge_from, edge_to,
                bearing, origin_index, bin_m, speed_ms):
    """自前Python版（bench側と同じ構造。heapqを使う）。"""
    indptr = indptr.tolist()
    indices = indices.tolist()
    entry_edge = entry_edge.tolist()
    bins = [row.tolist() for row in cost_bins]
    length = length_m.tolist()
    efrom = edge_from.tolist()
    eto = edge_to.tolist()
    brg = bearing.tolist()
    n = len(eto)
    bin_count = len(bins)
    best = [math.inf] * n
    arrival = [math.inf] * n
    heap = []
    for entry in range(indptr[origin_index], indptr[origin_index + 1]):
        e = entry_edge[entry]
        c = bins[0][e]
        if c == math.inf:
            continue
        best[e] = c
        arrival[e] = length[e]
        heapq.heappush(heap, (c, e))
    popped = 0
    while heap:
        g, state = heapq.heappop(heap)
        if g > best[state]:
            continue
        popped += 1
        head = eto[state]
        tail = efrom[state]
        b = brg[state]
        travelled = arrival[state]
        time_bin = int(travelled // bin_m)
        if time_bin >= bin_count:
            time_bin = bin_count - 1
        costs = bins[time_bin]
        for entry in range(indptr[head], indptr[head + 1]):
            nxt = entry_edge[entry]
            c = costs[nxt]
            if c == math.inf:
                continue
            delta = (brg[nxt] - b + 180.0) % 360.0 - 180.0
            if indices[entry] == tail:
                seconds = TURN_UTURN_S
            elif abs(delta) <= STRAIGHT_MAX_DEG:
                seconds = 0.0
            elif delta < 0:
                seconds = TURN_LEFT_S
            else:
                seconds = TURN_RIGHT_S
            ng = g + c + seconds * speed_ms
            if ng < best[nxt]:
                best[nxt] = ng
                arrival[nxt] = travelled + length[nxt]
                heapq.heappush(heap, (ng, nxt))
    return np.asarray(best), popped


@njit(cache=True)
def numba_tree(indptr, indices, entry_edge, cost_bins, length_m, edge_from, edge_to,
               bearing, origin_index, bin_m, speed_ms, capacity):
    """numba版。優先度キューはnumpy配列のバイナリヒープとして自前で持つ（heapqは使えない）。"""
    n = edge_to.shape[0]
    bin_count = cost_bins.shape[0]
    best = np.full(n, np.inf)
    arrival = np.full(n, np.inf)
    heap_key = np.empty(capacity, dtype=np.float64)
    heap_val = np.empty(capacity, dtype=np.int64)
    size = 0

    for entry in range(indptr[origin_index], indptr[origin_index + 1]):
        e = entry_edge[entry]
        c = cost_bins[0, e]
        if not np.isfinite(c):
            continue
        best[e] = c
        arrival[e] = length_m[e]
        i = size
        heap_key[i] = c
        heap_val[i] = e
        while i > 0:
            parent = (i - 1) // 2
            if heap_key[parent] <= heap_key[i]:
                break
            tk = heap_key[parent]; heap_key[parent] = heap_key[i]; heap_key[i] = tk
            tv = heap_val[parent]; heap_val[parent] = heap_val[i]; heap_val[i] = tv
            i = parent
        size += 1

    popped = 0
    while size > 0:
        g = heap_key[0]
        state = heap_val[0]
        size -= 1
        heap_key[0] = heap_key[size]
        heap_val[0] = heap_val[size]
        i = 0
        while True:
            left = 2 * i + 1
            right = left + 1
            smallest = i
            if left < size and heap_key[left] < heap_key[smallest]:
                smallest = left
            if right < size and heap_key[right] < heap_key[smallest]:
                smallest = right
            if smallest == i:
                break
            tk = heap_key[smallest]; heap_key[smallest] = heap_key[i]; heap_key[i] = tk
            tv = heap_val[smallest]; heap_val[smallest] = heap_val[i]; heap_val[i] = tv
            i = smallest

        if g > best[state]:
            continue
        popped += 1
        head = edge_to[state]
        tail = edge_from[state]
        b = bearing[state]
        travelled = arrival[state]
        time_bin = int(travelled // bin_m)
        if time_bin >= bin_count:
            time_bin = bin_count - 1
        for entry in range(indptr[head], indptr[head + 1]):
            nxt = entry_edge[entry]
            c = cost_bins[time_bin, nxt]
            if not np.isfinite(c):
                continue
            delta = (bearing[nxt] - b + 180.0) % 360.0 - 180.0
            if indices[entry] == tail:
                seconds = TURN_UTURN_S
            elif abs(delta) <= STRAIGHT_MAX_DEG:
                seconds = 0.0
            elif delta < 0:
                seconds = TURN_LEFT_S
            else:
                seconds = TURN_RIGHT_S
            ng = g + c + seconds * speed_ms
            if ng < best[nxt]:
                best[nxt] = ng
                arrival[nxt] = travelled + length_m[nxt]
                i = size
                heap_key[i] = ng
                heap_val[i] = nxt
                while i > 0:
                    parent = (i - 1) // 2
                    if heap_key[parent] <= heap_key[i]:
                        break
                    tk = heap_key[parent]; heap_key[parent] = heap_key[i]; heap_key[i] = tk
                    tv = heap_val[parent]; heap_val[parent] = heap_val[i]; heap_val[i] = tv
                    i = parent
                size += 1
    return best, popped


def main() -> None:
    data = np.load(sys.argv[1])
    indptr = data["indptr"].astype(np.int64)
    indices = data["indices"].astype(np.int64)
    entry_edge = data["entry_edge"].astype(np.int64)
    cost = data["cost"]
    length_m = data["length_m"]
    edge_from = data["edge_from"]
    edge_to = data["edge_to"]
    bearing = data["bearing"]
    origin_index = int(data["origin_index"])
    cost_bins = np.vstack([cost * factor for factor in TIME_BIN_FACTORS])
    speed_ms = SPEED_KMH / 3.6
    bin_m = TIME_BIN_HOURS * 3600.0 * speed_ms
    transitions = int((indptr[edge_to + 1] - indptr[edge_to]).sum())
    capacity = transitions + 64
    print(f"states={len(edge_to)} transitions={transitions}")

    started = time.perf_counter()
    py_best, py_popped = python_tree(indptr, indices, entry_edge, cost_bins, length_m,
                                     edge_from, edge_to, bearing, origin_index, bin_m, speed_ms)
    py_ms = (time.perf_counter() - started) * 1000
    print(f"[Python] popped={py_popped} elapsed_ms={py_ms:.0f} 1状態あたり={py_ms * 1000 / py_popped:.2f}us")

    started = time.perf_counter()
    nb_best, nb_popped = numba_tree(indptr, indices, entry_edge, cost_bins, length_m,
                                    edge_from, edge_to, bearing, origin_index, bin_m, speed_ms, capacity)
    compile_ms = (time.perf_counter() - started) * 1000
    print(f"[numba] 初回（コンパイル込み） elapsed_ms={compile_ms:.0f}")

    best_ms = math.inf
    for _ in range(3):
        started = time.perf_counter()
        nb_best, nb_popped = numba_tree(indptr, indices, entry_edge, cost_bins, length_m,
                                        edge_from, edge_to, bearing, origin_index, bin_m, speed_ms, capacity)
        best_ms = min(best_ms, (time.perf_counter() - started) * 1000)
    print(f"[numba] popped={nb_popped} elapsed_ms={best_ms:.0f} "
          f"1状態あたり={best_ms * 1000 / nb_popped:.3f}us 速度比={py_ms / best_ms:.1f}倍")

    both = np.isfinite(py_best) & np.isfinite(nb_best)
    diff = np.abs(py_best[both] - nb_best[both])
    print(f"一致: 共通到達={int(both.sum())} 最大差={diff.max():.6f} "
          f"到達数 python={int(np.isfinite(py_best).sum())} numba={int(np.isfinite(nb_best).sum())}")


if __name__ == "__main__":
    main()
