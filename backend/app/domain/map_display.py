"""地図に出すものの最上位の束ね方。

所属は**種別**から決まる——レイヤーごとに所属を書くと、1つ足すたびに書き忘れても型が通る。
軸スタジオ由来の軸はここに載らない（運用で増減し、出すかは軸自身の設定が決める）。
"""

from typing import NamedTuple

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

#: 気象のまとまり。1つのチップが複数の配信要素（面・線・記号）をまとめて出す。
WEATHER_LAYER_GROUPS: tuple[str, ...] = ("precipitationNowcast", "windVector", "disaster")

#: 利用者が作った線。属性でも配信でもないので、ここだけが名前を持つ。
ROUTE_LAYER_ID = "route"

#: 陰影は属性ではなく標高の別の描き方。源泉に属性として現れないのが正しい。
HILLSHADE_LAYER_ID = "hillshade"


def _static_layer_ids() -> tuple[str, ...]:
    """地図へ出す一次属性（線・点は行の定義を持つもの、面は幾何が面のもの）＋描き方の派生。"""
    shown = [
        attr.attr_id
        for attr in PRIMARY_ATTRIBUTES
        if attr.display_axes or attr.geometry == "area"
    ]
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


#: 面の濃さ。下限は「最も薄い階級が背景に対してΔE（CIE76）15以上」、上限は面の下にある
#: 土地の塗りが潰れない範囲。**上下から挟まれている**ので片側だけを見て動かさない。
AREA_OPACITY = 0.55

#: 陰影。北西からの斜め光（真上からだと起伏が出ない）。`igor`は傾きのarctanに比例する
#: ——既定の`standard`はsinに比例し、平野部の数度では実効の濃さが0.03を下回って見えない。
HILLSHADE_ILLUMINATION_DEG = 315
HILLSHADE_METHOD = "igor"
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
