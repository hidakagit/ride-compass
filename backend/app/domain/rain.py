"""雨の材料。アメダスの毎正時の1時間雨量を観測所ごとに履歴で持ち、そこから区間ごとに引く。

窓の長さの一覧（`RAIN_WINDOW_HOURS`）がこの材料群の唯一の宣言で、材料id・材料カタログの行・
持つ履歴の長さはここから導く。値は観測どおりの量（mm・時間）で、どこからを「濡れている」と
みなすかのしきい値は軸の側が決める。

何mm以上を雨と数えるかは、天気の「降っていない」の境（`weather.PRECIPITATION_MIN_MM`）と同じ事実として
そちらを読む。雨量計は0.5mm刻みなので、観測された雨はすべて当たる。
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.domain.weather import PRECIPITATION_MIN_MM

RAIN_WINDOW_HOURS: tuple[int, ...] = (1, 3, 4, 6, 12, 24, 48, 72)
#: 観測所ごとに持つ1時間雨量の本数。最も長い窓と、止んでからの時間の上限を兼ねる。
RAIN_HISTORY_HOURS = max(RAIN_WINDOW_HOURS)

HOURS_SINCE_RAIN = "hours_since_rain"


def rain_window_material_id(hours: int) -> str:
    return f"rain_{hours}h_mm"


RAIN_MATERIAL_IDS: tuple[str, ...] = (
    *(rain_window_material_id(hours) for hours in RAIN_WINDOW_HOURS),
    HOURS_SINCE_RAIN,
)

# 最寄りを絞り込む格子の1辺（度）。観測所の間隔（十数km）より十分小さければ、ほとんどの格子で候補が1か所に絞れる。
_NEAREST_CELL_DEG = 0.01
# 先に観測所を絞る粗い格子の1辺が、細かい格子の何個ぶんか（粗い格子は細かい格子をちょうど含む）。
_COARSE_CELLS = 16
# 1回に距離を並べる格子・地点の数。格子×観測所・地点×候補の距離を一度に作らないための刻み。
_CELL_CHUNK = 512
_POINT_CHUNK = 65536


@dataclass(frozen=True)
class StationRainMaterials:
    """観測所ごとの雨の材料の値（`RAIN_MATERIAL_IDS`→観測所の並びの配列、値が無ければNaN）。"""

    #: 最も新しい1時間の終わり（JSTの正時）。
    latest_hour: datetime
    latitudes: np.ndarray
    longitudes: np.ndarray
    values: dict[str, np.ndarray]


def rain_material_values(hourly_mm: np.ndarray) -> dict[str, np.ndarray]:
    """(観測所, 時刻)の1時間雨量から材料の値を求める。時刻は古い順に`RAIN_HISTORY_HOURS`本で、
    最後の列が直近の1時間。欠測はNaN。

    窓の雨量は、窓の中に欠測の1時間が1つでもあれば値を持たない（0として足すと少なく見せる）。
    止んでからの時間は、直近の1時間に雨があれば0、k時間前の1時間が最後の雨ならk。
    さかのぼって雨を見つける前に欠測に当たれば値を持たず、全部さかのぼって雨が無ければ
    `RAIN_HISTORY_HOURS`（それ以上）になる。
    """
    values ={rain_window_material_id(hours): hourly_mm[:, -hours:].sum(axis=1) for hours in RAIN_WINDOW_HOURS}
    newest_first = hourly_mm[:, ::-1]
    rained = newest_first >= PRECIPITATION_MIN_MM
    missing = np.isnan(newest_first)
    first_rain = np.where(rained.any(axis=1), rained.argmax(axis=1), RAIN_HISTORY_HOURS)
    first_missing = np.where(missing.any(axis=1), missing.argmax(axis=1), RAIN_HISTORY_HOURS)
    hours_since = first_rain.astype(float)
    hours_since[first_missing < first_rain] = np.nan
    values[HOURS_SINCE_RAIN] = hours_since
    return values


def rain_material_columns(
    stations: StationRainMaterials, latitudes: np.ndarray, longitudes: np.ndarray
) -> dict[str, np.ndarray]:
    """各地点の雨の材料の値（`RAIN_MATERIAL_IDS`→地点の並びの配列）。地点に最も近い雨量計の値で、
    その雨量計が欠測ならNaN（次に近い雨量計では埋めない）。地図の配信とルートの評価が同じここを通る。"""
    nearest = nearest_point_indices(latitudes, longitudes, stations.latitudes, stations.longitudes)
    return {material_id: values[nearest] for material_id, values in stations.values.items()}


def _unit_vectors(latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    phi, lam = np.radians(latitudes), np.radians(longitudes)
    return np.stack([np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)], axis=-1)


def nearest_point_indices(
    latitudes: np.ndarray, longitudes: np.ndarray, point_latitudes: np.ndarray, point_longitudes: np.ndarray
) -> np.ndarray:
    """各地点（`latitudes`/`longitudes`）に球面の距離で最も近い点（`point_*`）の番号。

    単位球上の位置ベクトルの内積が大きいほど近い（大円の距離と順位が同じ）。探索範囲は数百万区間になるため、
    全地点×全点の距離は作らない: 地点を緯度・経度の格子に分け、格子ごとに「格子の中のどこから見ても
    最寄りになりうる点」だけを候補に残してから、地点ごとに候補の中で比べる。候補は、粗い格子で全点から
    絞ったものを、細かい格子でさらに絞る（どちらの段でも、最寄りの点は候補から落ちない）。
    """
    latitudes = np.asarray(latitudes, dtype=float)
    longitudes = np.asarray(longitudes, dtype=float)
    if len(latitudes) == 0:
        return np.empty(0, dtype=np.intp)
    points = _unit_vectors(np.asarray(point_latitudes, dtype=float), np.asarray(point_longitudes, dtype=float))
    rows, columns, cell_of = _occupied_cells(
        np.floor(latitudes / _NEAREST_CELL_DEG).astype(np.int64),
        np.floor(longitudes / _NEAREST_CELL_DEG).astype(np.int64),
    )
    coarse_rows, coarse_columns, _ = _occupied_cells(rows // _COARSE_CELLS, columns // _COARSE_CELLS)
    near = np.unique(
        _candidates_per_cell(coarse_rows, coarse_columns, _NEAREST_CELL_DEG * _COARSE_CELLS, points)
    )
    candidates = near[_candidates_per_cell(rows, columns, _NEAREST_CELL_DEG, points[near])]
    result = candidates[cell_of, 0]
    # 候補が1つの格子の地点はそれで決まる。残りの地点だけを候補の中で比べる。
    undecided = np.flatnonzero((candidates != candidates[:, :1]).any(axis=1)[cell_of])
    for start in range(0, len(undecided), _POINT_CHUNK):
        rows_here = undecided[start:start + _POINT_CHUNK]
        chosen = candidates[cell_of[rows_here]]
        here = _unit_vectors(latitudes[rows_here], longitudes[rows_here])
        closeness = np.einsum("nkc,nc->nk", points[chosen], here)
        result[rows_here] = chosen[np.arange(len(chosen)), np.argmax(closeness, axis=1)]
    return result


def _occupied_cells(rows: np.ndarray, columns: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """地点の格子の番号（行・列）から、地点のある格子の行・列と、各地点がそのどれに入るかを返す。"""
    row_min, column_min = rows.min(), columns.min()
    width = int(columns.max() - column_min) + 1
    dense = (rows - row_min) * width + (columns - column_min)
    size = int(dense.max()) + 1
    if size > 4 * len(dense):
        # 地点の数に比べて範囲が広いときは、範囲の大きさの配列を作らずに並べ替えで数える。
        occupied, cell_of = np.unique(dense, return_inverse=True)
    else:
        present = np.zeros(size, dtype=bool)
        present[dense] = True
        occupied = np.flatnonzero(present)
        position = np.zeros(size, dtype=np.intp)
        position[occupied] = np.arange(len(occupied))
        cell_of = position[dense]
    return occupied // width + row_min, occupied % width + column_min, cell_of


def _candidates_per_cell(rows: np.ndarray, columns: np.ndarray, size_deg: float, points: np.ndarray) -> np.ndarray:
    """1辺`size_deg`の格子（行・列の番号）ごとに、格子の中の地点の最寄りになりうる点（単位ベクトル`points`）の
    番号（格子×候補の幅）。幅に足りない分は格子の最初の候補で埋める（同じ点を2度比べても選ぶ点は変わらない）。

    格子の中の地点は格子の中心から弦で格子の1辺（ラジアン）以内にあるため、中心から最も近い点までの
    弦の長さをdとすると、格子の中の地点の最寄りは中心から弦でd＋2辺以内の点に限られる（三角不等式）。
    """
    centers = _unit_vectors((rows + 0.5) * size_deg, (columns + 0.5) * size_deg)
    # 浮動小数の丸め（内積から弦へ戻す引き算の桁落ち）で候補を落とさないよう、わずかに広げる。
    # 広げても候補が増えるだけで、選ばれる点は変わらない。
    reach = 2.0 * np.radians(size_deg) + 1e-9
    cells, stations = [], []
    for start in range(0, len(centers), _CELL_CHUNK):
        # 単位ベクトルどうしの弦の長さの2乗は 2 − 2×内積。
        chords = np.sqrt(np.maximum(0.0, 2.0 - 2.0 * (centers[start:start + _CELL_CHUNK] @ points.T)))
        cell, station = np.nonzero(chords <= chords.min(axis=1, keepdims=True) + reach)
        cells.append(cell + start)
        stations.append(station)
    cell, station = np.concatenate(cells), np.concatenate(stations)
    counts = np.bincount(cell, minlength=len(centers))
    first = np.cumsum(counts) - counts
    candidates = np.repeat(station[first][:, None], counts.max(), axis=1)
    candidates[cell, np.arange(len(cell)) - first[cell]] = station
    return candidates
