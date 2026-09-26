"""土地被覆クラス別割合（`edge_materials.lc_*`・`way_materials.lc_*`）の算出。

Esri×Impact Observatory Sentinel-2 10m Annual LULCの画素値ヒストグラム（バッチが
道路centerline周囲のリングから集計したクラス別画素数）を、クラスごとの割合(%)へ
変換するだけの純関数群。どのクラスが「遮蔽」でどのクラスが「開放」かという判断は
一切行わない——その判断は評価軸（`domain/axis_definitions.py: AXIS_DEFINITIONS`）の
`terms`（重み付き線形結合）が表現する。材料段階で分類を固定すると、軸定義を見ただけでは
何が難易度に寄与しているか分からなくなるため。
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import create_model

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

#: 土地被覆を数える帯。中心線からこの距離までを見て、路面そのものの幅は除く。
#: 材料の値を決める量であり、材料の説明文もこの値を読む。
LANDCOVER_RING_OUTER_M = 100.0
LANDCOVER_RING_INNER_M = 10.0

# これ未満の有効画素数は「値なし」（行を作らない）。統計的に安定した割合と呼べる
# 最低限の画素数（10m画素×20 = 2,000m2程度）。
MIN_VALID_PIXELS = 20


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

#: (割合列の名前, クラス値)。割合を出す対象は`LANDCOVER_CLASSES`が決め、ここはそれを
#: SQLの列順（クラス値の昇順）へ並べ替えただけのもの。並びを表示順から切り離すのは、
#: 表示順を変えただけで焼き込み済みの列順が動かないようにするため。
PERCENT_CLASSES: tuple[tuple[str, int], ...] = tuple(
    sorted(((cls.percent_field, cls.value) for cls in LANDCOVER_CLASSES), key=lambda pair: pair[1])
)


def landcover_key(percent_field: str) -> str:
    """割合列の名前（`crops_percent`）から、材料の列（`lc_crops`）・集計SQLの別名が使うクラスの鍵（`crops`）。"""
    return percent_field.removesuffix("_percent")


def landcover_tile_property(percent_field: str) -> str:
    """材料の`tile_property`と、路面タイルへ焼き込む列の名前（`crops_pct`）。両者が同じ名前で初めて地図が塗れる。"""
    return f"{landcover_key(percent_field)}_pct"

#: 材料の割合列（`lc_*`）＋`lc_valid_pixels`と1対1のモデル。**クラスの宣言から作る**
#: ——手で並べると、宣言したクラスに対応する項目が無いまま集計だけが走り、その列の
#: 割合がどこへも入らない（SQLは列を吐き、読む側はその名前を知らない）。
class _LandcoverValidPixels(StrictModel):
    valid_pixels: int


_PERCENT_FIELDS: dict[str, Any] = {name: (float, ...) for name, _ in PERCENT_CLASSES}

LandcoverPercentages = create_model(
    "LandcoverPercentages",
    __base__=_LandcoverValidPixels,
    **_PERCENT_FIELDS,
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


def class_percentages_sql(counts: str) -> str:
    """クラスごとの画素数から割合(%)を出すSQL。

    `counts`は`(osm_way_id, segment_index, cls, n)`を返す関係。有効画素数
    （No Data・Cloudsを除いた合計）が`MIN_VALID_PIXELS`未満の区間は返らない——
    帯がラスタの外へ大きくはみ出た・雲に覆われていた等、統計として信頼できないため。
    """
    invalid = ", ".join(str(v) for v in sorted(LULC_INVALID_VALUES))
    tally = ",\n           ".join(
        f"sum(n) FILTER (WHERE cls = {value}) AS {landcover_key(name)}"
        for name, value in PERCENT_CLASSES)
    percents = ",\n       ".join(
        f"100.0 * coalesce({landcover_key(name)}, 0) / valid_pixels AS {name}"
        for name, _ in PERCENT_CLASSES)
    return f"""
WITH counted AS ({counts}),
agg AS (
    SELECT osm_way_id, segment_index,
           sum(n) FILTER (WHERE cls NOT IN ({invalid}))::int AS valid_pixels,
           {tally}
    FROM counted GROUP BY osm_way_id, segment_index)
SELECT osm_way_id, segment_index, valid_pixels,
       {percents}
FROM agg WHERE valid_pixels >= {MIN_VALID_PIXELS}
"""
