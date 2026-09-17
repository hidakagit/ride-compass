"""土地被覆の事前集計バッチが共有するラスタ読み出し。

way単位（`precompute_way_landcover.py`）と区間単位（`precompute_edge_landcover.py`）は
母集団だけが違い、「線 → リング → 画素ヒストグラム → 割合」の手順は同一である。ここを
共有しないと、片方だけリング径・無効画素の扱いが変わったときに単位ごとの値が静かに
食い違う（同じ道の同じ場所に別の割合が出る）。

`benchmarks/bench_t919_edge_landcover.py`もここを呼ぶ——計測が別の数え方をすると、
測った差が実装で再現しない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, box
from shapely.geometry.base import BaseGeometry

from app.domain.landcover import LandcoverPercentages, class_percentages
from app.infrastructure.proj_data import pin_bundled_proj_data

# ファイル名から年次マップの年を抽出する。配布元で命名が2通りある
# （docs/tasks/T624.md「データ取得」参照）。
#   AWS S3 `s3://io-10m-annual-lulc/`  : 54S_2024.tif（年だけ）
#   Azure Blob / Planetary Computer    : 54S_20250101-20260101.tif（期間表記）
# どちらも`_`の直後の4桁が年で、期間表記はその後ろへ続く。
_DATA_VERSION_FROM_FILENAME_RE = re.compile(r"_(\d{4})(?:\d{4}-\d{8})?\.")


def infer_data_version_from_filename(path: str) -> str | None:
    match = _DATA_VERSION_FROM_FILENAME_RE.search(Path(path).name)
    return match.group(1) if match else None


def build_ring(line: LineString, inner_m: float, outer_m: float) -> BaseGeometry:
    """道路centerline（ラスタと同じ投影CRS）から、外側`outer_m`m・内側`inner_m`mの
    リングを作る。道路面自体の画素を除くため中心線をそのまま使わず内側を刳り貫く
    （理由はdocs/tasks/T624.md論点1「道路自身の画素を除くリング形状にする理由」参照）。"""
    return line.buffer(outer_m).difference(line.buffer(inner_m))


def count_pixels_in_ring(dataset, ring: BaseGeometry) -> dict[int, int] | None:
    """開いているラスタ`dataset`（`ring`と同じCRS）から、`ring`内画素のクラス値
    ヒストグラムを返す。`ring`がラスタ範囲と重ならない場合はNone（このデータセットの
    対象外、呼び出し元が他のラスタを試すか諦める）。

    PROJデータの固定（`pin_bundled_proj_data`）は`RasterSource.__init__`が済ませている
    前提（線×ラスタごとに呼ぶとその回数だけstat syscallを発行するだけになる）。"""
    # このモジュールはALGORITHM_VERSION参照のためだけにderived_data_freshness.py経由でも
    # importされうる。そちらから読めなくならないよう、ラスタ処理の依存はここでのみ読み込む
    # （モジュール冒頭でimportしない）。`RasterSource`が使うpyprojは
    # requirements-batch.txt限定で、本番webイメージには無い。
    import rasterio.errors
    import rasterio.features

    if ring.is_empty:
        return {}
    try:
        window = rasterio.features.geometry_window(dataset, [ring])
    except rasterio.errors.WindowError:
        return None
    if window.width <= 0 or window.height <= 0:
        return None
    data = dataset.read(1, window=window)
    if data.size == 0:
        return None
    window_transform = dataset.window_transform(window)
    mask = rasterio.features.geometry_mask([ring], out_shape=data.shape, transform=window_transform, invert=True)
    values, counts = np.unique(data[mask], return_counts=True)
    return {int(value): int(count) for value, count in zip(values, counts)}


class NoValueReason(Enum):
    """割合を出せなかった理由。呼び出し元はこれを内訳として数える。

    `PARTIAL_COVERAGE`（ラスタ境界またぎ）と`OUT_OF_RANGE`を分けるのは、前者がラスタの
    追加で解消できるため。
    """

    OUT_OF_RANGE = "out_of_range"
    PARTIAL_COVERAGE = "partial_coverage"
    LOW_PIXELS = "low_pixels"


@dataclass(frozen=True, slots=True)
class RingMeasurement:
    """1本の線ぶんの測定結果。`percentages`がNoneのとき`reason`が理由を持つ。"""

    percentages: LandcoverPercentages | None
    reason: NoValueReason | None


class RasterSource:
    """1つのラスタファイル（開いたままの`rasterio.DatasetReader`）と、
    EPSG:4326からそのラスタのCRSへの変換器を束ねる。"""

    def __init__(self, path: str):
        # count_pixels_in_ringと同じ理由でここでのみimportする。
        pin_bundled_proj_data()
        import pyproj
        import rasterio

        self.dataset = rasterio.open(path)
        self._bounds = box(*self.dataset.bounds)
        self._transformer = pyproj.Transformer.from_crs("EPSG:4326", self.dataset.crs, always_xy=True)

    def to_raster_crs(self, line_wgs84: LineString) -> LineString:
        return LineString(self._transformer.itransform(line_wgs84.coords))

    def contains(self, ring: BaseGeometry) -> bool:
        """`ring`（このラスタのCRS）が範囲へ完全に収まるか。

        一部だけ重なるラスタで割合を出すと、重なった側の土地被覆だけで100%を分け合う
        「もっともらしい値」になり、NULLではないため鮮度台帳にも欠損として現れない。
        画素数ではなく矩形の包含で判定するのは、リング形状のラスタライズ誤差に
        依存させないため。"""
        return self._bounds.contains(ring)

    def intersects(self, ring: BaseGeometry) -> bool:
        return self._bounds.intersects(ring)

    def close(self) -> None:
        self.dataset.close()


def measure_ring(
    sources: list[RasterSource], line_wgs84: LineString, inner_m: float, buffer_m: float
) -> RingMeasurement:
    """線1本ぶんの割合を、リングを完全に含む最初のラスタから出す。

    どのラスタもリングを完全には覆えなかった場合、部分的にでも重なるラスタがあったか
    （ラスタ境界をまたぐ線）で理由を分ける。
    """
    partially_covered = False
    for source in sources:
        ring = build_ring(source.to_raster_crs(line_wgs84), inner_m, buffer_m)
        if not source.contains(ring):
            partially_covered = partially_covered or source.intersects(ring)
            continue
        counts = count_pixels_in_ring(source.dataset, ring)
        if counts is None:
            continue
        percentages = class_percentages(counts)
        if percentages is None:
            return RingMeasurement(None, NoValueReason.LOW_PIXELS)
        return RingMeasurement(percentages, None)
    return RingMeasurement(
        None, NoValueReason.PARTIAL_COVERAGE if partially_covered else NoValueReason.OUT_OF_RANGE
    )
