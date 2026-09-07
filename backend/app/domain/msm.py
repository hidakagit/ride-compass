"""気象庁MSM（メソ数値予報モデル）格子の幾何と補間。

外部I/Oを持たない純関数のみを置く。実データの同期・読み出しは
`infrastructure/msm_client.py`が担う。

MSMは緯度・経度方向で間隔の異なる等間隔格子（緯度0.05度・経度0.0625度）のため、
任意地点の値は周囲4格子点からの双一次補間で求める。
"""

import re
from dataclasses import dataclass

import numpy as np

# 配信元メタ情報のcrs_wktが持つ範囲指定。WKTのBBOXは南・西・北・東の順に並ぶ。
_BBOX_PATTERN = re.compile(r"BBOX\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]")


def parse_bbox(crs_wkt: str) -> tuple[float, float, float, float]:
    """crs_wktから(南緯, 西経, 北緯, 東経)を取り出す。見つからなければValueError。"""
    match = _BBOX_PATTERN.search(crs_wkt)
    if match is None:
        raise ValueError("crs_wktにBBOXがありません")
    south, west, north, east = (float(value) for value in match.groups())
    return south, west, north, east


@dataclass(frozen=True)
class MsmGrid:
    """MSM格子の幾何。

    原点・間隔は配信元メタ情報のbboxと実データ配列の形状から導出する。定数として
    書き写すと、配信元が格子を変更したときにここだけ古い値が残り、全地点の値が
    エラーにならないまま静かにずれる。
    """

    lat_min: float
    lon_min: float
    d_lat: float
    d_lon: float
    n_lat: int
    n_lon: int

    @classmethod
    def from_bbox_and_shape(cls, bbox: tuple[float, float, float, float], n_lat: int, n_lon: int) -> "MsmGrid":
        south, west, north, east = bbox
        if n_lat < 2 or n_lon < 2:
            raise ValueError("格子の形状が不正です")
        return cls(
            lat_min=south,
            lon_min=west,
            d_lat=(north - south) / (n_lat - 1),
            d_lon=(east - west) / (n_lon - 1),
            n_lat=n_lat,
            n_lon=n_lon,
        )

    def contains(self, latitudes: np.ndarray, longitudes: np.ndarray) -> bool:
        lat_max = self.lat_min + self.d_lat * (self.n_lat - 1)
        lon_max = self.lon_min + self.d_lon * (self.n_lon - 1)
        return bool(
            np.all(latitudes >= self.lat_min)
            and np.all(latitudes <= lat_max)
            and np.all(longitudes >= self.lon_min)
            and np.all(longitudes <= lon_max)
        )

    def slice_bounds(self, latitudes: np.ndarray, longitudes: np.ndarray) -> tuple[int, int, int, int]:
        """与えた地点群を補間するのに必要な部分ブロックの索引範囲(i0, i1, j0, j1)を返す。

        双一次補間は各地点の右上側の格子点も参照するため、上端側へ1つ余分に取る。
        """
        if not self.contains(latitudes, longitudes):
            raise ValueError("MSM格子の範囲外の地点が含まれています")
        i0 = int(np.floor((latitudes.min() - self.lat_min) / self.d_lat))
        i1 = min(int(np.floor((latitudes.max() - self.lat_min) / self.d_lat)) + 2, self.n_lat)
        j0 = int(np.floor((longitudes.min() - self.lon_min) / self.d_lon))
        j1 = min(int(np.floor((longitudes.max() - self.lon_min) / self.d_lon)) + 2, self.n_lon)
        return i0, i1, j0, j1


def interpolate_points(
    block: np.ndarray, grid: MsmGrid, i0: int, j0: int, latitudes: np.ndarray, longitudes: np.ndarray
) -> np.ndarray:
    """部分ブロック（形状[緯度, 経度, 時刻]）から地点ごとの時系列を双一次補間で取り出す。

    `i0`・`j0`は`block`が全体格子のどこから切り出されたかを示す索引（`slice_bounds`の戻り値）。
    戻り値の形状は[地点数, 時刻数]。
    """
    fi = (latitudes - grid.lat_min) / grid.d_lat - i0
    fj = (longitudes - grid.lon_min) / grid.d_lon - j0
    ai = np.clip(np.floor(fi).astype(int), 0, block.shape[0] - 2)
    aj = np.clip(np.floor(fj).astype(int), 0, block.shape[1] - 2)
    wi = (fi - ai)[:, None]
    wj = (fj - aj)[:, None]
    return (
        block[ai, aj] * (1.0 - wi) * (1.0 - wj)
        + block[ai + 1, aj] * wi * (1.0 - wj)
        + block[ai, aj + 1] * (1.0 - wi) * wj
        + block[ai + 1, aj + 1] * wi * wj
    )


def wind_speed_and_direction(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """東西成分・南北成分[m/s]から風速[m/s]と風向[度]を求める。

    風向は「風が吹いてくる方位」（北=0、東=90）で返す。気象分野の慣行であり、
    ルート評価・地図表示ともにこの定義を前提にしている。
    """
    speed = np.hypot(u, v)
    direction = (np.degrees(np.arctan2(u, v)) + 180.0) % 360.0
    return speed, direction
