"""地図に出すものの最上位の束ね方。

所属は**種別**から決まる——レイヤーごとに所属を書くと、1つ足すたびに書き忘れても型が通る。
軸スタジオ由来の軸はここに載らない（運用で増減し、出すかは軸自身の設定が決める）。
"""

from typing import Literal, NamedTuple

from app.domain.jma_tile_specs import (
    JMA_TILE_SPECS,
    JmaTileSpec,
    PathGroup,
    effective_max_zoom,
    jma_path_group,
    jma_target_time_files,
)
from app.domain.material_catalog import PRIMARY_ATTRIBUTES


class OverlayGroup(NamedTuple):
    key: str
    label: str


class LayerCategory(NamedTuple):
    key: str
    #: 属するグループの`key`。
    group: str


#: 並びがそのままチップの並び順になる。
MAP_OVERLAY_GROUPS: tuple[OverlayGroup, ...] = (
    OverlayGroup("road", "道路"),
    OverlayGroup("environment", "環境"),
    OverlayGroup("spot", "スポット"),
)

#: レイヤーの絵がどこから来るか。取得状態（読み込み中・空・失敗）の判定はここから導く。
MAP_LAYER_DATA_SOURCES: tuple[str, ...] = (
    "roadTiles",
    "accidentTiles",
    "poiTiles",
    "gsiRelief",
    "gsiTerrain",
    "landcoverRaster",
    "ownFetch",
)

#: 値の性質。生データか、計算した推定か、時刻で中身が変わるか。
#: 評価軸は"composite"で、地図チップには出さない。
MAP_LAYER_DATA_NATURES: tuple[str, ...] = ("raw", "composite", "dynamic")

#: レイヤーの種別と、属するグループ。**種別を1つ足すときは必ず所属も決まる**。
MAP_LAYER_CATEGORIES: tuple[LayerCategory, ...] = (
    LayerCategory("roadCondition", "road"),
    LayerCategory("terrain", "environment"),
    LayerCategory("weather", "environment"),
    LayerCategory("disaster", "environment"),
    LayerCategory("trafficSafety", "spot"),
    LayerCategory("amenity", "spot"),
)


#: 描き直しの種類。`dynamic`は選択中ルートにひもづくもの、`static`はそれ以外。
#: **値が時間で変わるかとは別軸**——降水は中身が変わるがルートとは無関係なので`static`。
MAP_LAYER_KINDS: tuple[str, ...] = ("static", "dynamic")

#: 動的気象の描き方の種類。配信元が描いた画像（`rasterTile`）・配信元の地物（`vectorTile`）・
#: 自前の格子の面（`gridFill`）・格子や地点の記号（`gridMark`）。
WeatherRenderKind = Literal["rasterTile", "vectorTile", "gridFill", "gridMark"]
_TILE_KINDS: frozenset[str] = frozenset({"rasterTile", "vectorTile"})


class WeatherElement(NamedTuple):
    """動的気象で地図に描くもの1つ。**ここへ1件足すと要素が1つ増える**（画面は描き方だけを持つ）。"""

    #: チップid。1つのチップが複数の要素をまとめて出す。
    group: str
    #: チップの中の名前付きソース。同じ名前を描き方違いで複数の要素が名乗ってよい
    #: （届いた中身の種類がどちらを出すかを決める）。
    source: str
    kind: WeatherRenderKind
    #: 気象庁の配信要素id（配信元のパス`.../surf/<id>/`）を、**時刻の段の順**（近い時刻から）に並べる
    #: ——1つの名前付きソースが、選んだ時刻によって別の配信要素から届くことがある。タイルで描くものは
    #: 全段が`JMA_TILE_SPECS`に仕様を持ち、ソースのズーム範囲は1つなので段の間で一致する。
    #: 自前のMSM格子から描くものは空。
    jma_elements: tuple[str, ...]
    #: 画面で要素を呼ぶ名前（▶パネルで要素ごとに表示を切り替える行の名前）。同じ名前付き
    #: ソースの要素は同じ名前を持つ。
    label: str


#: 並びが同じ段（面・線・記号）の中の重なり順になる。災害は面を下に、見落としやすい線（洪水）・
#: 点（落雷）を上に置き、大雨は土砂・浸水を統合した指標なので個別の2つより下に置く。
WEATHER_ELEMENTS: tuple[WeatherElement, ...] = (
    # 降水。60分先までは降水ナウキャスト、その先15時間先までは降水短時間予報を配信元のラスタで、
    # それ以降は自前の格子を塗る。どれが届くかは選んだ時刻で決まる。
    WeatherElement("precipitationNowcast", "main", "rasterTile", ("hrpns", "rasrf"), "降水"),
    WeatherElement("precipitationNowcast", "main", "gridFill", (), "降水"),
    WeatherElement("precipitationNowcast", "linearRainband", "rasterTile", ("sjfcstmap",), "線状降水帯予測"),
    WeatherElement("windVector", "arrow", "gridMark", (), "風"),
    WeatherElement("disaster", "heavyRain", "rasterTile", ("rain_mesh",), "大雨キキクル"),
    WeatherElement("disaster", "landslide", "rasterTile", ("land",), "土砂災害キキクル"),
    WeatherElement("disaster", "inundation", "rasterTile", ("inund",), "浸水キキクル"),
    WeatherElement("disaster", "thunder", "rasterTile", ("thns",), "雷ナウキャスト"),
    WeatherElement("disaster", "tornado", "rasterTile", ("trns",), "竜巻発生確度"),
    WeatherElement("disaster", "flood", "vectorTile", ("flood",), "洪水キキクル（河川）"),
    WeatherElement("disaster", "liden", "gridMark", ("liden",), "落雷（発生地点）"),
)


def weather_element_tile(element: WeatherElement) -> JmaTileSpec | None:
    """タイルで描く要素の配信元仕様。タイルで描かない要素はNone。

    段ごとに仕様が違っても、1つのソースが持てるズーム範囲とベクタのレイヤー名は1つだけなので、
    食い違えば`ValueError`。"""
    if element.kind not in _TILE_KINDS:
        return None
    if not element.jma_elements:
        raise ValueError(f"タイルで描く要素に配信要素idが無い: {element.group}/{element.source}")
    specs = [JMA_TILE_SPECS[element_id] for element_id in element.jma_elements]
    shapes = {(spec.min_zoom, effective_max_zoom(spec), spec.vector_layer) for spec in specs}
    if len(shapes) > 1:
        raise ValueError(f"時刻の段の間でタイルのズーム範囲が食い違う: {element.group}/{element.source} {shapes}")
    return specs[0]


def weather_element_deliveries(element: WeatherElement) -> list[tuple[str, PathGroup, tuple[str, ...]]]:
    """配信元から取る段ごとの（配信要素id, パスの系統, 時刻一覧のファイル）。自前のMSM格子から描く要素は空。"""
    return [
        (element_id, jma_path_group(element_id), jma_target_time_files(element_id))
        for element_id in element.jma_elements
    ]


def weather_element_attribution(element: WeatherElement) -> str:
    return "気象庁" if element.jma_elements else "気象庁MSM"


#: 気象のまとまり（チップ）。要素の宣言から導く——並びは最初に現れた順。
WEATHER_LAYER_GROUPS: tuple[str, ...] = tuple(dict.fromkeys(element.group for element in WEATHER_ELEMENTS))

#: 利用者が作った線。属性でも配信でもないので、ここだけが名前を持つ。
ROUTE_LAYER_ID = "route"

#: 陰影は属性ではなく標高の別の描き方。源泉に属性として現れないのが正しい。
HILLSHADE_LAYER_ID = "hillshade"


def _static_layer_ids() -> tuple[str, ...]:
    """地図へ出す一次属性（線・点は行の定義を持つもの、面は幾何が面のもの）＋描き方の派生。"""
    shown = [attr.attr_id for attr in PRIMARY_ATTRIBUTES if attr.display_axes or attr.geometry == "area"]
    return (*shown, HILLSHADE_LAYER_ID)


#: 地図に載るものの名前。軸スタジオ由来の軸は実行時に増えるためここには現れない。
MAP_LAYER_IDS: tuple[str, ...] = (*_static_layer_ids(), *WEATHER_LAYER_GROUPS, ROUTE_LAYER_ID)


#: 利用者が作った線の太さ（px）。役割ごとに違うのは、同じ道の上へ重ねたときに
#: どれが手前かを太さで読ませるため。
ROUTE_LINE_WIDTHS_PX: dict[str, float] = {
    "candidate": 2.5,
    "selectedHalo": 10,
    "splice": 3,
    "spliceSelected": 5,
    "composite": 7,
    "slot": 4,
    "detail": 6,
}

#: 縁取りは線の両側へ一定を足す。**個別に書かない**——線の太さを変えたときに縁取りだけ
#: 古い値で残ると、線が縁からはみ出す。
CASING_MARGIN_PX = 4
ROUTE_CASING_WIDTHS_PX: dict[str, float] = {
    role: ROUTE_LINE_WIDTHS_PX[role] + CASING_MARGIN_PX for role in ("composite", "slot", "detail")
}

ROUTE_LINE_OPACITIES: dict[str, float] = {"selectedHalo": 0.25, "splice": 0.85}

#: 破線の刻み。実線との違いが読める最小の組み合わせ。
ROUTE_SPLICE_DASH: tuple[float, ...] = (2, 1.5)

#: 進行方向の矢印。大きさはズームに追従させる——固定ピクセルだと、拡大するほど
#: 周囲の道路だけが太くなり矢印が相対的に小さく見える。
ROUTE_ARROW_SPACING_PX = 80
ROUTE_ARROW_HALO_SCALE = 1.5
ROUTE_ARROW_SIZE_BY_ZOOM: tuple[tuple[float, float], ...] = ((10, 0.6), (13, 0.8), (16, 1.2), (19, 1.6))


#: 難易度（0〜100）の段の境界。軸が宣言していないときに使う。**値ではなく等分の規則**
#: ——無次元の得点には目盛りの手掛かりが無いので、3等分する。符号付き材料の段は
#: 軸の折れ線から導く（`domain/dynamic_way_values.py`）ので、ここには持たない。
DEFAULT_DIFFICULTY_BOUNDARIES: tuple[float, ...] = (33, 66)


#: 面の濃さ。下限は「最も薄い階級が背景に対してΔE（CIE76）15以上」、上限は面の下にある
#: 土地の塗りが潰れない範囲。**上下から挟まれている**ので片側だけを見て動かさない。
AREA_OPACITY = 0.55

#: 陰影。北西からの斜め光（真上からだと起伏が出ない）。`igor`は傾きのarctanに比例する
#: ——既定の`standard`はsinに比例し、平野部の数度では実効の濃さが0.03を下回って見えない。
HILLSHADE_ILLUMINATION_DEG = 315
HILLSHADE_METHOD = "igor"
#: 標高の強調。**タイルの値は実際の標高のままで、読み方（復元式の係数）へ掛ける**
#: ——タイル側を書き換えると、同じタイルを別の倍率で読み直せなくなる。
#: 上げるほど緩い斜面が読めるが、上げすぎると急斜面との差が潰れる。
TERRAIN_EXAGGERATION = 5

#: 気象の記号。風は速さで大きさを変え、`WIND_FULL_SCALE_MS`で上限に達する。
WEATHER_MARK_HALO_WIDTH_PX = 1.5
WIND_ICON_SCALE_RANGE: tuple[float, float] = (0.9, 2.6)
WIND_FULL_SCALE_MS = 15
LIGHTNING_ICON_SCALE = 0.8


#: 道の線。太さは意味を運ばない（意味は色だけ）ので、分類の線はすべて同じ太さ。
#: 横に分ける間隔は太さより狭くして隣どうしをわずかに重ねる——離すと1本の道が複数に見える。
ROAD_LINE_WIDTH_PX = 3
ROAD_TRACK_OFFSET_STEP_PX = 2
#: 分類がある道は濃く、無い道は薄く（消さずに薄くする）。
ROAD_KNOWN_OPACITY = 0.8
ROAD_UNKNOWN_OPACITY = 0.15
#: 詳細を見ている1本の強調。元の線が上に乗ったままになる太さにする。
ROAD_INSPECTED_WIDTH_PX = 8

#: 点。重大度は色ではなく大きさで示す（当事者の色と取り合わないため）。
POINT_RADIUS_PX = 4
POINT_FATAL_RADIUS_PX = 6
POINT_NON_FATAL_RADIUS_PX = 3
POINT_STROKE_WIDTH_PX = 1
POINT_OPACITY = 0.9
#: 事故は面的に多く、同じ濃さだと停止要因の点が埋もれる。
ACCIDENT_POINT_OPACITY = 0.75
