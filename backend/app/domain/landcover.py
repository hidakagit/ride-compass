"""土地被覆クラス別割合（`way_landcover`）の算出。

Esri×Impact Observatory Sentinel-2 10m Annual LULCの画素値ヒストグラム（バッチが
道路centerline周囲のリングから集計したクラス別画素数）を、クラスごとの割合(%)へ
変換するだけの純関数群。どのクラスが「遮蔽」でどのクラスが「開放」かという判断は
一切行わない——その判断は評価軸（`domain/axis_definitions.py: AXIS_DEFINITIONS`）の
`terms`（重み付き線形結合）が表現する。材料段階で分類を固定すると、軸定義を見ただけでは
何が難易度に寄与しているか分からなくなるため（docs/tasks/T624.md「方針転換」参照）。
"""

from datetime import datetime
from typing import Mapping

from pydantic import BaseModel

LULC_WATER = 1
LULC_TREES = 2
LULC_FLOODED_VEG = 4
LULC_CROPS = 5
LULC_BUILT = 7
LULC_BARE = 8
LULC_SNOW_ICE = 9
LULC_CLOUDS = 10
LULC_RANGELAND = 11

# No Data(0)・Clouds(10)は分母（有効画素数）から除外する。
LULC_INVALID_VALUES = frozenset({0, LULC_CLOUDS})

# これ未満の有効画素数は「値なし」（行を作らない）。統計的に安定した割合と呼べる
# 最低限の画素数（10m画素×20 = 2,000m2程度）。
MIN_VALID_PIXELS = 20


class LandcoverPercentages(BaseModel):
    """`way_landcover`の割合8列＋`valid_pixels`と1対1のモデル。"""

    valid_pixels: int
    water_percent: float
    trees_percent: float
    flooded_veg_percent: float
    crops_percent: float
    built_percent: float
    bare_percent: float
    snow_ice_percent: float
    rangeland_percent: float


def class_percentages(counts: Mapping[int, int]) -> LandcoverPercentages | None:
    """クラス値→画素数のヒストグラムから、クラスごとの割合(%)を算出する。

    有効画素数（No Data・Clouds以外の合計）が`MIN_VALID_PIXELS`未満の場合はNone
    （ウィンドウがラスタ範囲外に大きくはみ出た・雲に覆われていた等、統計的に
    信頼できない場合の「値なし」表現）。
    """
    valid_pixels = sum(count for value, count in counts.items() if value not in LULC_INVALID_VALUES)
    if valid_pixels < MIN_VALID_PIXELS:
        return None

    def percent(value: int) -> float:
        return 100 * counts.get(value, 0) / valid_pixels

    return LandcoverPercentages(
        valid_pixels=valid_pixels,
        water_percent=percent(LULC_WATER),
        trees_percent=percent(LULC_TREES),
        flooded_veg_percent=percent(LULC_FLOODED_VEG),
        crops_percent=percent(LULC_CROPS),
        built_percent=percent(LULC_BUILT),
        bare_percent=percent(LULC_BARE),
        snow_ice_percent=percent(LULC_SNOW_ICE),
        rangeland_percent=percent(LULC_RANGELAND),
    )


class WayLandcover(BaseModel):
    """`way_landcover`テーブル1行分（`LandcoverPercentages`にosm_way_id・系譜情報を
    足した完全な行表現）。`EdgeMaterialBundle.landcover`（`domain/attributes.py`）の
    型としても使う（`ElevationAttribute`と同じ「材料値＋系譜情報を1つのモデルで持つ」
    構成）。"""

    osm_way_id: int
    percentages: LandcoverPercentages
    data_source: str
    data_version: str
    computed_at: datetime
    source_osm_import_run_id: int | None = None
    algorithm_version: str | None = None
