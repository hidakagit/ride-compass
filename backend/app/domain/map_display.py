"""地図に出すものの最上位の束ね方。

所属は**種別**から決まる——レイヤーごとに所属を書くと、1つ足すたびに書き忘れても型が通る。
軸スタジオ由来の軸はここに載らない（運用で増減し、出すかは軸自身の設定が決める）。
"""

from typing import NamedTuple

from app.domain.gsi_tiles import TERRAIN_MIN_ZOOM
from app.domain.landcover import LANDCOVER_TILE_MIN_ZOOM
from app.domain.material_catalog import PRIMARY_ATTRIBUTES
from app.domain.region import ROAD_TILE_MIN_ZOOM
from app.domain.weather_elements import WEATHER_LAYER_GROUPS


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

class MapLayerDataSource(NamedTuple):
    key: str
    #: このズーム未満では配信されない（ONにしても地図には何も出ない）。無いものはNone。
    min_zoom: int | None = None


#: タイルで配る一次属性の系統（`tile_version_service.py: TILE_SHAPES`の名前）。
#: 情報源の名前にそのまま使う——世代が届くまで要求できないのは、この名前の情報源だけ。
_TILE_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(attr.tile_kind for attr in PRIMARY_ATTRIBUTES if attr.tile_kind is not None)
)

#: レイヤーの絵がどこから来るか。取得状態（読み込み中・空・失敗）の判定はここから導く。
#: 最小ズームは配信の性質なので情報源の側で持つ——レイヤーごとに書くと、同じタイルを
#: 読むレイヤーの1つだけ書き忘れても型が通り、そのチップだけ案内が出ない。
MAP_LAYER_DATA_SOURCES: tuple[MapLayerDataSource, ...] = (
    *(MapLayerDataSource(kind, ROAD_TILE_MIN_ZOOM) for kind in _TILE_KINDS),
    MapLayerDataSource("gsiRelief"),
    MapLayerDataSource("gsiTerrain", TERRAIN_MIN_ZOOM),
    MapLayerDataSource("landcoverRaster", LANDCOVER_TILE_MIN_ZOOM),
    MapLayerDataSource("ownFetch"),
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

#: 利用者が作った線。属性でも配信でもないので、ここだけが名前を持つ。
ROUTE_LAYER_ID = "route"

#: 陰影は属性ではなく標高の別の描き方。源泉に属性として現れないのが正しい。
HILLSHADE_LAYER_ID = "hillshade"

#: 地図へ常に出す出典（HTML）。路面の色・評価・ルートの計算へ常に使うデータで、どのレイヤーを表示しているかと
#: 関係なく出典が要る（レイヤーのソースに付けると、そのレイヤーを消したとき出典も消える）。地理院・警察庁の利用規約は
#: 出典とは別に加工した旨を求め、標高からは勾配を、事故の点からは区間ごとの件数を導いている。基礎地図は配信元の
#: TileJSONが出典を持つので入れない（入れると2回並ぶ）。データ源を足したら、利用条件（docs/architecture/data-sources.md）
#: と合わせてここも見る。
ALWAYS_SHOWN_ATTRIBUTIONS: tuple[str, ...] = (
    '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">'
    "OpenStreetMap contributors</a>",
    '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noreferrer">'
    "地理院タイル(標高タイル)</a>を加工して作成",
    "交通事故統計情報（警察庁）を加工して作成",
    '土地被覆: <a href="https://livingatlas.arcgis.com/landcover/" target="_blank" rel="noreferrer">'
    "Esri, Impact Observatory, Microsoft</a> (CC BY 4.0)",
)


def _static_layer_ids() -> tuple[str, ...]:
    """地図へ出す一次属性（線・点は行の定義を持つもの、面は幾何が面のもの）＋描き方の派生。"""
    shown = [attr.attr_id for attr in PRIMARY_ATTRIBUTES if attr.display_axes or attr.geometry == "area"]
    return (*shown, HILLSHADE_LAYER_ID)


#: 地図に載るものの名前。軸スタジオ由来の軸は実行時に増えるためここには現れない。
MAP_LAYER_IDS: tuple[str, ...] = (*_static_layer_ids(), *WEATHER_LAYER_GROUPS, ROUTE_LAYER_ID)


class MapLayerSpec(NamedTuple):
    #: 絵の出所（`MAP_LAYER_DATA_SOURCES`の`key`）。
    data_source: str
    #: 種別（`MAP_LAYER_CATEGORIES`の`key`）。どのグループにも属さないもの（ルート）はNone。
    category: str | None
    kind: str = "static"
    data_nature: str = "raw"
    #: 利用者の操作を待たずに表示するか。**性質で決める**——明示的にONにして初めて出るのが
    #: 地図レイヤーの原則で、既定ONの根拠になるのは防災級の情報と、探索の結果そのものだけ。
    default_on: bool = False


def _tile_layer(attr_id: str, category: str) -> MapLayerSpec:
    """タイルで配る一次属性のレイヤー。情報源は属性自身が宣言するタイルの系統。"""
    tile_kind = next(attr.tile_kind for attr in PRIMARY_ATTRIBUTES if attr.attr_id == attr_id)
    assert tile_kind is not None, attr_id
    return MapLayerSpec(tile_kind, category)


#: `MAP_LAYER_IDS`の1つずつの宣言。**足りないと生成の時点で落ちる**（`MAP_LAYERS`）。
_LAYER_SPECS: dict[str, MapLayerSpec] = {
    "elevation": MapLayerSpec("gsiRelief", "terrain"),
    HILLSHADE_LAYER_ID: MapLayerSpec("gsiTerrain", "terrain"),
    "landcover": MapLayerSpec("landcoverRaster", "terrain"),
    "highway": _tile_layer("highway", "roadCondition"),
    "surface": _tile_layer("surface", "roadCondition"),
    "tunnel": _tile_layer("tunnel", "roadCondition"),
    "oneway": _tile_layer("oneway", "roadCondition"),
    "stop_poi": _tile_layer("stop_poi", "trafficSafety"),
    "supply_poi": _tile_layer("supply_poi", "amenity"),
    "accident_point": _tile_layer("accident_point", "trafficSafety"),
    "precipitationNowcast": MapLayerSpec("ownFetch", "weather", data_nature="dynamic"),
    "windVector": MapLayerSpec("ownFetch", "weather", data_nature="dynamic"),
    # 予兆が出てからONにするのでは手遅れになるため既定ONにする。危険度が出ている間は広い範囲が
    # 塗られ、他の面レイヤー（緑と水・標高図）も基礎地図の色も覆われるが、危険度ゼロの領域は
    # 配信元のタイルが透明なので、影響が出るのは警戒度が上がっている間だけ。そのときは防災の
    # 情報を優先する（利用者はチップをOFFにすれば戻せる）。
    "disaster": MapLayerSpec("ownFetch", "disaster", data_nature="dynamic", default_on=True),
    # 候補を出したら見えている必要がある（探索の結果そのもの）。
    ROUTE_LAYER_ID: MapLayerSpec("ownFetch", None, kind="dynamic", default_on=True),
}

#: 地図に載るものの宣言（`MAP_LAYER_IDS`の順）。
MAP_LAYERS: tuple[tuple[str, MapLayerSpec], ...] = tuple(
    (layer_id, _LAYER_SPECS[layer_id]) for layer_id in MAP_LAYER_IDS
)

#: 軸スタジオ由来の軸のレイヤー。どちらも路面タイルの道へ色を塗る。ramp軸はタイルへ焼き込んだ
#: 一次属性を合成した値（composite）、専用配信の軸は時刻で変わる値（dynamic）を読む。
AXIS_LAYER_SPECS: dict[str, MapLayerSpec] = {
    "ramp": MapLayerSpec("road_surface", None, data_nature="composite"),
    "dedicated": MapLayerSpec("road_surface", None, data_nature="dynamic"),
}


#: 利用者が作った線の太さ（px）。役割ごとに違うのは、同じ道の上へ重ねたときに
#: どれが手前かを太さで読ませるため。
ROUTE_LINE_WIDTHS_PX: dict[str, float] = {
    "candidate": 2.5,
    "selectedHalo": 10,
    "splice": 3,
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

ROUTE_LINE_OPACITIES: dict[str, float] = {"selectedHalo": 0.25, "splice": 0.75}

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
