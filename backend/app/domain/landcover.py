"""土地被覆クラス別割合（`way_landcover`）の算出。

Esri×Impact Observatory Sentinel-2 10m Annual LULCの画素値ヒストグラム（バッチが
道路centerline周囲のリングから集計したクラス別画素数）を、クラスごとの割合(%)へ
変換するだけの純関数群。どのクラスが「遮蔽」でどのクラスが「開放」かという判断は
一切行わない——その判断は評価軸（`domain/axis_definitions.py: AXIS_DEFINITIONS`）の
`terms`（重み付き線形結合）が表現する。材料段階で分類を固定すると、軸定義を見ただけでは
何が難易度に寄与しているか分からなくなるため（docs/tasks/T624.md「方針転換」参照）。
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from app.domain.strict_model import StrictModel

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


class LandcoverPercentages(StrictModel):
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


class LandcoverRecord(StrictModel):
    """土地被覆の派生行のうち、単位（way／区間）に依らない部分。

    割合そのものと系譜情報を持つ。鍵だけが単位ごとに違うため、鍵を足したものが
    `WayLandcover`・`EdgeLandcover`になる。
    """

    #: Noneは「計算済み・値なし」（ラスタ範囲外・境界またぎ・有効画素不足）。行が無い場合と
    #: 材料としての扱いは同じ（どちらも欠損）で、増分実行がやり直さないために行を残す。
    percentages: LandcoverPercentages | None
    data_source: str
    data_version: str
    computed_at: datetime
    source_osm_import_run_id: int | None = None
    algorithm_version: str | None = None
    #: 「値なし」と確定させたときのラスタ構成の指紋（`percentages`がNoneの行でのみ意味を持つ）。
    source_raster_set: str | None = None


class WayLandcover(LandcoverRecord):
    """`way_landcover`テーブル1行分。バッチ（`precompute_way_landcover.py`）の書き込みと、
    区間インスペクタ（`domain/axis_inspector.py`）のWay1本ぶんの入力に使う。評価経路の
    材料はこの行から配線済みクラスの割合だけを取り出したもの（`EdgeMaterialBundle`の
    `landcover_percents`）で、系譜情報は運ばない。"""

    osm_way_id: int


class EdgeLandcover(LandcoverRecord):
    """`edge_landcover`テーブル1行分。鍵は向きに依らない区間の同定子（way＋両端ノードの
    小さい方・大きい方）で、`road_edges`のforward/backwardは同じ1行を共有する。"""

    osm_way_id: int
    node_lo: str
    node_hi: str


@dataclass(frozen=True)
class LandcoverClass:
    """土地被覆1クラスの表示上の定義。

    ラスタの画素値・`LandcoverPercentages`の割合列・表示名・色を1組で持つ。地図タイルの
    塗り（`infrastructure/landcover_raster.py`）も、凡例と区間インスペクタの表示名
    （frontendへは`scripts/export_openapi.py`が`landcover-classes.json`として書き出す）も、
    このレジストリだけを見る。
    """

    #: ラスタの画素値。
    value: int
    #: `LandcoverPercentages`の対応する割合列の名前。
    percent_field: str
    label: str
    #: 地図へ塗る色。配信元の公式配色をそのまま使わない——建物が鮮やかな赤で、この
    #: アプリでは赤が「難易度が高い」を表す色として既に使われているため、市街地が
    #: 常時その色で覆われると他の赤の意味が薄れる。色相は自然な連想（水=青・樹木=緑）を
    #: 保ちつつ、下の道路・地名が読める彩度に落とす。
    color: str
    #: 地図の面レイヤーで塗るか。Falseでも区間インスペクタの割合には出る（数値は他の
    #: クラスに薄められない）。塗らないのは、**そのクラスが広い範囲を単色で覆ってしまい、
    #: 基礎地図を隠すわりに何も足さない**場合に限る。
    painted: bool = True


#: 表示順。割合の大きくなりやすいクラスから並べ、同率のときの並びもこれで決まる。
#: `LULC_INVALID_VALUES`（No Data・Clouds）は表示対象を持たないため含まない。
LANDCOVER_CLASSES: tuple[LandcoverClass, ...] = (
    # 建物は塗らない。既定の現在地（都心）では画素の85〜95%がこのクラスで、塗ると画面
    # 全体が単色で覆われ基礎地図が濁るだけになる（関東本土全体では中央値3%で、都心だけが
    # 極端に偏る）。建物があることは基礎地図から分かる。色は区間インスペクタの内訳が使う
    # ——他のクラスと違って無彩色なのは、数値の表でも「地」として読ませるため。
    LandcoverClass(LULC_BUILT, "built_percent", "建物", "#9AA0A6", painted=False),
    LandcoverClass(LULC_TREES, "trees_percent", "樹木", "#4C8C4A"),
    LandcoverClass(LULC_CROPS, "crops_percent", "農地", "#E0C066"),
    LandcoverClass(LULC_RANGELAND, "rangeland_percent", "草地", "#C3B78F"),
    LandcoverClass(LULC_WATER, "water_percent", "水面", "#4A7FB5"),
    LandcoverClass(LULC_FLOODED_VEG, "flooded_veg_percent", "湿地", "#7FB99B"),
    LandcoverClass(LULC_BARE, "bare_percent", "裸地", "#C4B4A3"),
    LandcoverClass(LULC_SNOW_ICE, "snow_ice_percent", "雪氷", "#D8E6F0"),
)

# 地図タイルとして配信するズーム範囲。
#
# 上限は元データの分解能（10m画素がz14でほぼ1画素1画素に対応する）で、それ以上は
# MapLibreが拡大して見せる。下限は読み取りコストではなく見え方で決めている——配布元の
# GeoTIFFは縮小画像を同梱しており、広い範囲を覆うタイルも間引いて読めば安く作れる
# （東京付近の1タイルでz6=97ms・z10=30ms・z14=14ms、開発機実測）。ラスタが覆うのは
# UTMゾーン1枚ぶんで、これより広い表示では面が画面の一部を塗るだけになり読み取れない。
LANDCOVER_TILE_MIN_ZOOM = 6
LANDCOVER_TILE_MAX_ZOOM = 14


def raster_set_fingerprint(raster_paths: list[str]) -> str:
    """ラスタ構成の指紋（ファイル名の集合から決まる短い文字列）。

    土地被覆の派生物は、どのラスタを開いていたかに従属する。「値なし」はその構成で
    そう確定したという意味しか持たず、ラスタを1枚足せば境界またぎ・範囲外だった場所は
    値を持ちうる。指紋を派生物の鍵へ入れておけば、構成が変わった時点で古い結果が
    使われなくなる。順序には依存させない（同じ集合をどの順で渡しても同じ指紋になる）。
    """
    joined = "\n".join(sorted(Path(path).name for path in raster_paths))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
