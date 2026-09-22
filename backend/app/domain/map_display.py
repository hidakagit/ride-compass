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
