import math
from typing import Annotated, NamedTuple, Protocol

import numpy as np
from pydantic import Field

EARTH_RADIUS_KM = 6371.0

# 緯度・経度の値の範囲。モデルの欄にもHTTPのクエリにもこの型で書く。クエリでは既定値に`Query()`を
# 置かない——置くとFastAPIがこの型の範囲を読まず、範囲の外の値が黙って通る。
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
# 走行方位（度、北=0から時計回り）。方位を受ける入口（地図の配信・区間インスペクタ）はこの型で書く。範囲の検査は
# NaN・無限大も断る。
BearingDeg = Annotated[float, Field(ge=0, lt=360)]


class LatLon(Protocol):
    """緯度経度を持つ任意の型（`Coordinates`等）を受け付ける構造的型。

    型ヒントを`Coordinates`（Pydantic）固定にすると、グラフ構築や最近傍探索のような
    ホットパスで、既に手元にある生の緯度経度ペアやNodeオブジェクトから
    わざわざ`Coordinates`を構築し直す無駄が生じる。

    読み取り専用のプロパティとして宣言するのは、凍結したdataclassや
    NamedTuple（`LatLonPoint`）も満たせるようにするため。
    """

    @property
    def latitude(self) -> float: ...

    @property
    def longitude(self) -> float: ...


class LatLonPoint(NamedTuple):
    """`LatLon`を満たす最小実装。Pydanticのバリデーションコストを
    避けたい内部計算専用（`Coordinates`は入力検証が必要なAPI境界向けに残す）。
    """

    latitude: float
    longitude: float


# 緯度1度あたりの概算距離（km、地球を球とみなす近似）。空間索引のバケット分割・打ち切り
# 判定・矩形マージンの見積もりという「目安」用途にのみ使う。実際の距離計算は常に
# haversine_distance_kmで正確に行う。
KM_PER_DEGREE_LATITUDE = 111.0


def km_per_degree_longitude(latitude: float) -> float:
    """緯度`latitude`での経度1度あたりの概算距離（km、`KM_PER_DEGREE_LATITUDE`と同じ目安用途）。

    極では`cos`が0へ落ちるため下限を置く——この値で割る側（矩形のマージン・索引のセル幅）が
    ゼロ除算にならないように。
    """
    return KM_PER_DEGREE_LATITUDE * max(math.cos(math.radians(latitude)), 1e-6)


#: `degrees_covering_m`の箱が距離の判定を覆う緯度の上限（度）。これより極に近い所では箱が距離より狭くなり、
#: 前置フィルタが黙って取りこぼす。
COVERED_LATITUDE_LIMIT = 60.0


def degrees_covering_m(radius_m: float) -> float:
    """半径`radius_m`（m）の円を、緯度`COVERED_LATITUDE_LIMIT`までどこでも覆う度の幅。SQLの前置フィルタ
    （`ST_Expand`の箱）を距離の判定より必ず広くするために使う。

    経度1度は緯度1度より短いので、上限の緯度での経度1度で割れば経度・緯度のどちらの向きも覆う。
    """
    return radius_m / (km_per_degree_longitude(COVERED_LATITUDE_LIMIT) * 1000.0)

#: 16方位の呼び名（0=北から時計回り）。8方位の呼び名はこの1つおきで、別に持たない——
#: 片方だけ直すと、同じ向きを場所によって違う名前で出す。
SIXTEEN_POINT_LABELS = [
    "北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
    "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西",
]
COMPASS_LABELS = SIXTEEN_POINT_LABELS[::2]


def compass_label(bearing_deg: float) -> str:
    """任意の角度（0=北、時計回り）を方位の呼び名に変換する。区分の幅は呼び名の数から決まる。

    区分の境界は上の区分へ倒す（half-up）。組み込みの`round`は偶数丸めのため使わない。
    画面も同じ角度を名付けるので、境界を含む入力とこの関数の答えを
    `scripts/cross_language_expectations.py: geo_expectations`が表にして配り、画面のテストが通す。
    """
    count = len(COMPASS_LABELS)
    index = math.floor((bearing_deg % 360) / (360 / count) + 0.5) % count
    return COMPASS_LABELS[index]


def bearing_between(origin: LatLon, destination: LatLon) -> float:
    """originからdestinationを見た初期方位角（0=北、時計回り、0-360）を球面三角法で求める。

    同じ地点どうしは向きが定まらず、例外にせず0（北）を返す（`atan2(0, 0)`）。"""
    return float(bearing_between_array(origin, np.asarray(destination.latitude), np.asarray(destination.longitude)))


def bearing_between_array(origin: LatLon, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """`bearing_between`を多数の点へまとめて求める。originから`(lat, lon)`の各点を見た初期方位角
    （0=北、時計回り、0-360）を配列で返す。式はここ1本で、1点の`bearing_between`もこれを通す。"""
    lat1 = math.radians(origin.latitude)
    lat2 = np.radians(lat)
    dlon = np.radians(lon - origin.longitude)

    x = np.sin(dlon) * np.cos(lat2)
    y = math.cos(lat1) * np.sin(lat2) - math.sin(lat1) * np.cos(lat2) * np.cos(dlon)

    return np.degrees(np.arctan2(x, y)) % 360


def haversine_distance_km(a: LatLon, b: LatLon) -> float:
    """2地点間の球面距離（km）。"""
    return float(haversine_distance_km_array(np.asarray(a.latitude), np.asarray(a.longitude), b))


def haversine_distance_km_array(lat: np.ndarray, lon: np.ndarray, target: LatLon) -> np.ndarray:
    """`haversine_distance_km`を多数の地点へまとめて求める。式はここ1本で、2地点の
    `haversine_distance_km`もこれを通す。

    `lat`/`lon`は複数地点の緯度経度配列（同一形状）、`target`は単一の目的地。
    A*ヒューリスティック（`node_heuristic`）が、レグごとに目的地が変わるたびグラフ上の
    全Nodeとの距離を1回のnumpy演算で求め直すために使う。
    """
    lat1 = np.radians(lat)
    lon1 = np.radians(lon)
    lat2 = math.radians(target.latitude)
    lon2 = math.radians(target.longitude)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * math.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(h))


# 最寄りを絞り込む格子の1辺（度）。観測所の間隔（十数km）より十分小さければ、ほとんどの格子で候補が1か所に絞れる。
_NEAREST_CELL_DEG = 0.01
# 先に観測所を絞る粗い格子の1辺が、細かい格子の何個ぶんか（粗い格子は細かい格子をちょうど含む）。
_COARSE_CELLS = 16
# 1回に距離を並べる格子・地点の数。格子×観測所・地点×候補の距離を一度に作らないための刻み。
_CELL_CHUNK = 512
_POINT_CHUNK = 65536


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
    内積は1の近くで浮動小数の刻みが粗く、約10cmより近い差は区別しない（同じ距離として先に並んだ点を選ぶ）。
    点は1つ以上要る（無いときの答えは呼び手が決める。1地点の口`nearest_point_index`はNone）。
    """
    if len(point_latitudes) == 0:
        raise ValueError("最寄りを選ぶ点が1つも無い")
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


def nearest_point_index(
    latitude: float, longitude: float, point_latitudes: np.ndarray, point_longitudes: np.ndarray
) -> int | None:
    """1地点に球面の距離で最も近い点（`point_*`）の番号。点が無ければNone。同じ距離の点が並べば
    先に並んだ点を選ぶ。"""
    if len(point_latitudes) == 0:
        return None
    return int(
        nearest_point_indices(np.array([latitude]), np.array([longitude]), point_latitudes, point_longitudes)[0]
    )
