"""地図に出すものの最上位の束ね方。

所属は**種別**から決まる——レイヤーごとに所属を書くと、1つ足すたびに書き忘れても型が通る。
軸スタジオ由来の軸はここに載らない（運用で増減し、出すかは軸自身の設定が決める）。
"""

from typing import Literal, NamedTuple

from app.domain.display_palette import ORDERED_END_COLOR_NAMES
from app.domain.gsi_tiles import TERRAIN_MIN_ZOOM
from app.domain.landcover import LANDCOVER_CLASSES, LANDCOVER_RING_OUTER_M, LANDCOVER_TILE_MIN_ZOOM
from app.domain.place_search import ADDRESS_DICTIONARY_ATTRIBUTION
from app.domain.primary_attributes import PRIMARY_ATTRIBUTES
from app.domain.registry import DisplayAxisSpec
from app.domain.region import ROAD_TILE_MIN_ZOOM
from app.domain.weather_elements import WEATHER_ELEMENTS, WEATHER_LAYER_GROUPS, FrameRuleKind, forecast_reach


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


class LegendSharedRow(NamedTuple):
    label: str
    #: 凡例の行の（i）から開く説明。
    description: str


#: 行の宣言に当てはまらない道の受け皿の行。道の属性・評価軸・ルートのどの凡例でも同じ意味なので、名前と説明を
#: ここだけが持つ（鍵は画面が引く名前）。
LEGEND_SHARED_ROWS: dict[str, LegendSharedRow] = {
    "other": LegendSharedRow(
        "その他",
        "値は書かれているが、上のどの行にも当てはまらない道（まれな種類など）。",
    ),
    "notApplicable": LegendSharedRow(
        "該当なし",
        "この種類に当たらない道（例: トンネルの凡例では、トンネルでない道）。",
    ),
    "noData": LegendSharedRow(
        "データなし",
        "元にする地図のデータに値が無く、どの行にも分けられない道。道が無いのではなく、値が分からない。",
    ),
    "undetermined": LegendSharedRow(
        "向きで決まらない",
        "選んだ走行方位とほぼ直角に交わり、その向きでは値が決まらない道（勾配なら、登りか下りかが決まらない）。"
        "データが無いのではなく、走行方位を変えると色が付く。",
    ),
}

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

#: 地図へ常に出す出典（HTML）。路面の色・評価・ルートの計算・常設の表示（ヘッダーの天気・警戒度バッジ）へ常に使う
#: データで、どのレイヤーを表示しているかと関係なく出典が要る（レイヤーのソースに付けると、そのレイヤーを消したとき
#: 出典も消える）。公共データ利用規約（PDL1.0）とCC BY 4.0は出典とは別に加工した旨を求め、標高からは勾配を、事故の点から
#: は区間ごとの件数を、アメダスの観測からは雨の材料を、アメダスと推計気象分布からは天気を、区域の境界は簡略化して、配信タイルは欠けたズームを隣の
#: ズームから補い降水の色を塗り替えて、MSMの格子は地点・時刻へ補間して使っている。気象レイヤーの出典もここが持つ（気象庁のデータは常設の表示
#: で常に使うため）。住所の辞書は地点の検索で常に使い、文言は同梱のREADMEが決めたもの。立ち寄り先は出典を1か所にまとめるためここに置く。基礎地図は配信元のTileJSONが出典を持つので
#: 入れない（入れると2回並ぶ）。データ源を足したら、利用条件（docs/architecture/data-sources.md）と合わせてここも見る。
ALWAYS_SHOWN_ATTRIBUTIONS: tuple[str, ...] = (
    '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">'
    "OpenStreetMap contributors</a>",
    '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noreferrer">'
    "地理院タイル(標高タイル)</a>を加工して作成",
    "交通事故統計情報[警察庁]を加工して作成",
    '<a href="https://www.jma.go.jp/" target="_blank" rel="noreferrer">気象庁ホームページ</a>'
    "(アメダス・警報・キキクル・ナウキャスト等)と気象庁"
    '「<a href="https://www.data.jma.go.jp/developer/gis.html" target="_blank" rel="noreferrer">'
    "予報区等GISデータ</a>」を加工して作成",
    "気象庁メソ数値予報モデル(MSM)を加工して作成。"
    '配布: <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Weather data by Open-Meteo.com</a>'
    ' (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>)',
    '暑さ指数: 出典 <a href="https://www.wbgt.env.go.jp/" target="_blank" rel="noreferrer">環境省熱中症予防情報サイト</a>',
    '土地被覆: <a href="https://livingatlas.arcgis.com/landcover/" target="_blank" rel="noreferrer">'
    "Esri, Impact Observatory, Microsoft</a> (CC BY 4.0)",
    ADDRESS_DICTIONARY_ATTRIBUTION,
    # Overture の地点は出どころごとに表示が要る（公式の文書 https://docs.overturemaps.org/attribution/ ）。
    # Foursquare の行は Apache 2.0 で、ライセンスの写し・変えた旨・NOTICE の全文を渡す（frontend/public/licenses/）。
    '立ち寄り先: <a href="https://overturemaps.org/" target="_blank" rel="noreferrer">Overture Maps Foundation</a>'
    "の地点を、種類を選び近くの同じ店をまとめて加工。"
    "Data from Meta, Microsoft, PinMeTo, DAC "
    '(<a href="https://cdla.dev/permissive-2-0/" target="_blank" rel="noreferrer">CDLA Permissive 2.0</a>), '
    "AllThePlaces "
    '(<a href="https://creativecommons.org/publicdomain/zero/1.0/" target="_blank" rel="noreferrer">CC0 1.0</a>), '
    "Foursquare (Copyright 2024 Foursquare Labs, Inc. All rights reserved. Available under "
    '<a href="/licenses/apache-2.0.txt" target="_blank" rel="noreferrer">Apache 2.0</a>. '
    "Foursquare data was transformed to the Overture schema. "
    '<a href="/licenses/foursquare-places-NOTICE.txt" target="_blank" rel="noreferrer">NOTICE</a>)',
    # ジャパンサーチのサイトポリシーの出典の記載例（編集・加工して使う場合）の形。
    '寺社: ジャパンサーチ「<a href="https://jpsearch.go.jp/database/bunka" target="_blank" rel="noreferrer">'
    "文化遺産オンライン（文化庁・国立情報学研究所）</a>」のメタデータを改変して利用（所有者で寺社ごとにまとめた）",
)


def _static_layer_ids() -> tuple[str, ...]:
    """地図へ出す一次属性（線・点は行の定義を持つもの、面は幾何が面のもの）＋描き方の派生。"""
    shown = [attr.attr_id for attr in PRIMARY_ATTRIBUTES if attr.display_axes or attr.geometry == "area"]
    return (*shown, HILLSHADE_LAYER_ID)


#: 地図に載るものの名前。軸スタジオ由来の軸は実行時に増えるためここには現れない。
_MAP_LAYER_IDS: tuple[str, ...] = (*_static_layer_ids(), *WEATHER_LAYER_GROUPS, ROUTE_LAYER_ID)


#: 説明の文の差し込み口の名前。どれも軸カタログ（実行時の応答）から来る値で、画面が埋める。
#: `axes`はそのレイヤーの元データを材料に持つ公開中の評価の名前、`accidentYears`は事故の収録年、
#: `routeLenses`はルートの色分けで選べるもの（公開中の評価と総合難易度）。
LayerTextSlotName = Literal["axes", "accidentYears", "routeLenses"]


class LayerTextSlot(NamedTuple):
    """説明の文の差し込み口。値が空なら、前後の文（`before`・`after`）ごと出さない——評価軸が1つも無いのに
    「評価軸の材料です」と書かない、収録年が届く前に空の[]を出さない。"""

    name: LayerTextSlotName
    before: str = ""
    after: str = ""


#: 説明の文。地図で何が見えるかの文と、軸カタログから差し込む部分を並べる（設計原則「1つの値の中で混ざるときは、
#: 部分ごとに問う」）。
LayerText = tuple[str | LayerTextSlot, ...]


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
    #: 名前。一次属性を描くレイヤーは書かない——属性の名前をそのまま使う（`map_layer_label`）。
    label: str | None = None
    #: チップの下の短い名前（チップの幅は文字数で決まるので、長い名前はここで縮める）。無ければ名前。
    chip_label: str | None = None
    #: ONにすると何が出るかの短い説明（チップのtitle）。地図に載るものは必ず持つ（`MAP_LAYERS`）。
    #: 軸スタジオ由来の軸の説明は軸から作る。
    description: LayerText = ()
    #: 表示の設定パネルで項目の(i)が出す、descriptionより詳しい説明。
    panel_hint: LayerText = ()


def _tile_layer(
    attr_id: str,
    category: str,
    *,
    description: LayerText,
    panel_hint: LayerText,
    chip_label: str | None = None,
) -> MapLayerSpec:
    """タイルで配る一次属性のレイヤー。情報源は属性自身が宣言するタイルの系統。"""
    tile_kind = next(attr.tile_kind for attr in PRIMARY_ATTRIBUTES if attr.attr_id == attr_id)
    assert tile_kind is not None, attr_id
    return MapLayerSpec(
        tile_kind, category, chip_label=chip_label, description=description, panel_hint=panel_hint
    )


def _first_axis(attr_id: str) -> DisplayAxisSpec:
    """一次属性の先頭の見方（色を決める軸）。"""
    return next(attr for attr in PRIMARY_ATTRIBUTES if attr.attr_id == attr_id).display_axes[0]


def _point_kind_list(attr_id: str) -> str:
    """説明へ差し込む点の種別名の並び（凡例と同じ、先頭の軸の行）。区切りが読点なのは、名前が中黒を含むため。"""
    return "、".join(category.label for category in _first_axis(attr_id).categories)


def _row_label(attr_id: str, key: str) -> str:
    """説明へ差し込む凡例の行の名前（先頭の軸の行）。"""
    return next(category.label for category in _first_axis(attr_id).categories if category.key == key)


def ordered_ends_text(axis: DisplayAxisSpec) -> str:
    """順序のある分類の色の向きの文。並びの先頭の行ほど濃く、末尾の行ほど明るく塗る（`display_palette.py: ordered_colors`）
    ので、両端の行の名前と色の呼び名から組む。"""
    if axis.palette != "ordered":
        raise ValueError(f"{axis.key}は順序のある分類ではない")
    dark, light = ORDERED_END_COLOR_NAMES
    return f"「{axis.categories[0].label}」ほど{dark}、「{axis.categories[-1].label}」ほど{light}"


def size_text(attr_id: str) -> str:
    """大きさで示す見方の文。半径を宣言した軸の、半径の最も大きい行の名前から組む。"""
    attribute = next(attr for attr in PRIMARY_ATTRIBUTES if attr.attr_id == attr_id)
    axis = next(
        axis for axis in attribute.display_axes if all(category.radius_px is not None for category in axis.categories)
    )
    return size_sentence(axis)


def size_sentence(axis: DisplayAxisSpec) -> str:
    """半径を宣言した軸の、半径の最も大きい行を名指す文。どの行も同じ半径なら、大きさで示していないので落とす。"""
    radii = {category.radius_px for category in axis.categories}
    if None in radii or len(radii) < 2:
        raise ValueError(f"{axis.key}は行ごとに違う半径を宣言していない")
    largest = max(axis.categories, key=lambda category: category.radius_px or 0)
    return f"{largest.label}は円を大きく表示します。"


#: 面で塗らない土地被覆の分類（区間インスペクタの割合には出る）。
_UNPAINTED_LANDCOVER = "・".join(cls.label for cls in LANDCOVER_CLASSES if not cls.painted)


def _window_hours(source: str) -> str:
    """名前付きソースを重ねる幅（「今」から何時間先まで）。要素の描くコマの規則が宣言する値。"""
    minutes = next(element.frame_rule.window_minutes for element in WEATHER_ELEMENTS if element.source == source)
    if minutes is None:
        raise ValueError(f"{source}は重ねる幅を宣言していない")
    return f"{minutes / 60:g}"


_LINEAR_RAINBAND_HOURS = _window_hours("linearRainband")


def _source_jma_elements(source: str) -> tuple[str, ...]:
    """名前付きソースが段に並べる配信要素（同じソースを名乗る要素をすべて合わせる）。"""
    return tuple(e for element in WEATHER_ELEMENTS if element.source == source for e in element.jma_elements)


#: 降水の段の境目（配信の宣言の、予測が届く先）。降水は近い段から高解像度降水ナウキャスト・降水短時間予報と継ぐ。
_NOWCAST_REACH, _SHORT_RANGE_REACH = (forecast_reach(e) for e in _source_jma_elements("main"))
_RAINBAND_AREA_REACH = forecast_reach(*_source_jma_elements("linearRainbandAreaForecast"))


def _label_list(labels: list[str]) -> str:
    """名前の並び。同じ名前を名乗る要素（描き方違いの同じ名前付きソース）は1つにする。"""
    return "・".join(dict.fromkeys(labels))


#: 災害の要素を、描くコマの規則ごとに言う語（短い説明・長い説明）。並びが説明の並びになる。
_DISASTER_FRAME_RULE_WORDING: dict[FrameRuleKind, tuple[str, str]] = {
    "nearest": ("時刻に連動", "は時刻スライダーに連動し、実況[直近]から{reach}先までを切り替えて確認できます。"),
    "latestObservation": ("直近の観測", "は観測だけのため、最新の観測より先の時刻には出ません。"),
    "current": (
        "現在の危険度のみ",
        "は色分けした現在の危険度で、「現在の危険度」単一値のみの配信のため時刻スライダーには連動しません。",
    ),
}

def _disaster_by_frame_rule() -> list[tuple[str, str, str]]:
    """災害の要素の名前を、描くコマの規則ごとにまとめた並び（要素の無い規則は出さない）。長い説明の`{reach}`には、
    その規則の要素の予測が届く先を入れる。"""
    rows = []
    for kind, (brief, detail) in _DISASTER_FRAME_RULE_WORDING.items():
        elements = [element for element in WEATHER_ELEMENTS if element.group == "disaster" and element.frame_rule.kind == kind]
        if not elements:
            continue
        if "{reach}" in detail:
            detail = detail.format(reach=forecast_reach(*(e for element in elements for e in element.jma_elements)))
        rows.append((_label_list([element.label for element in elements]), brief, detail))
    return rows


_DISASTER_BY_FRAME_RULE = _disaster_by_frame_rule()


#: `_MAP_LAYER_IDS`の1つずつの宣言。並びがチップの並び（種別の中の順）になる。**過不足は生成の時点で落ちる**（`MAP_LAYERS`）。
_LAYER_SPECS: dict[str, MapLayerSpec] = {
    "elevation": MapLayerSpec(
        "gsiRelief",
        "terrain",
        description=("国土地理院の色別標高図を重ねる",),
        panel_hint=("国土地理院の色別標高図を重ねる",),
    ),
    # 標高図（何mか）と区別できる名前にする（坂の在りかだけを塗る）。
    HILLSHADE_LAYER_ID: MapLayerSpec(
        "gsiTerrain",
        "terrain",
        label="起伏",
        description=("斜面に陰影を付ける[平地は塗らない]",),
        panel_hint=("国土地理院の標高データから斜面の陰影を作る。平らな所は塗らないため、下の地図の色が残る",),
    ),
    # 塗らないのは、広い範囲を単色で覆って基礎地図を隠すわりに何も足さない分類だけ（`LandcoverClass.painted`）。
    "landcover": MapLayerSpec(
        "landcoverRaster",
        "terrain",
        description=(f"周囲の緑・水辺・農地を面で重ねる{f'[{_UNPAINTED_LANDCOVER}は塗らない]' if _UNPAINTED_LANDCOVER else ''}",),
        panel_hint=(
            "衛星画像から分類した10m四方ごとの土地の使われ方です。1区画に1種類だけが入るため、"
            f"評価軸が使う「道路の周囲{LANDCOVER_RING_OUTER_M:g}mの割合」とは違い、混ざらずそのまま見えます。"
            + (
                f"{_UNPAINTED_LANDCOVER}は塗りません——広い範囲を単色で覆い、基礎地図を隠すだけになるためです。"
                f"地図の道を押して開く内訳には{_UNPAINTED_LANDCOVER}も出ます。"
                if _UNPAINTED_LANDCOVER
                else ""
            ),
        ),
    ),
    "highway": _tile_layer(
        "highway",
        "roadCondition",
        chip_label="道路種別",
        description=(f"道路の種類を色で表示[{ordered_ends_text(_first_axis('highway'))}]",),
        panel_hint=(
            "OSMのhighwayタグを区分にまとめて色分けしています。"
            f"「{_first_axis('highway').categories[0].label}」が最も濃く、下位の道ほど明るい色です。"
            "ほかの道路のレイヤーと一緒に表示すると、同じ道に線を横へ並べて描きます。",
        ),
    ),
    "surface": _tile_layer(
        "surface",
        "roadCondition",
        chip_label="路面",
        description=("路面の材質を色で表示[舗装・砂利・土など]",),
        panel_hint=(
            "OSMのsurfaceタグ[路面の材質]を区分にまとめて色分けしています。"
            f"タグの無い道は「{LEGEND_SHARED_ROWS["noData"].label}」、区分に当てはまらない値の道は「{LEGEND_SHARED_ROWS["other"].label}」で出します"
            f"[{LEGEND_SHARED_ROWS["noData"].label}は未舗装という意味ではありません]。",
        ),
    ),
    "tracktype": _tile_layer(
        "tracktype",
        "roadCondition",
        chip_label="等級",
        description=(f"農道・林道の路面の等級を色で表示[{ordered_ends_text(_first_axis('tracktype'))}]",),
        panel_hint=(
            "OSMのtracktypeタグ[農道・林道の路面の固さの等級]を色分けしています。路面の材質[surfaceタグ]とは別のタグで、"
            "材質のタグが無い農道・林道にも付いていることがあります。"
            f"タグの無い道は「{LEGEND_SHARED_ROWS["noData"].label}」です。",
        ),
    ),
    "tunnel": _tile_layer(
        "tunnel",
        "roadCondition",
        description=("トンネル区間[OSMのtunnelタグ]を色分け表示",),
        panel_hint=("OSMのtunnelタグが該当する区間です。", LayerTextSlot("axes", "評価軸", "の材料の1つです。")),
    ),
    "oneway": _tile_layer(
        "oneway",
        "roadCondition",
        description=("来た道を戻れない区間を色分け表示",),
        panel_hint=(
            "その向きにしか通れない区間です。上下線が分かれているだけの道[逆方向が数m隣にある]"
            "は除いてあります。ルート探索は既に一方通行の向きを守っており[逆走経路自体が"
            "生成されません]、このレイヤーは表示のみで評価には影響しません。",
        ),
    ),
    "stop_poi": _tile_layer(
        "stop_poi",
        "trafficSafety",
        description=(f"{_point_kind_list('stop_poi')}の位置を種別ごとに色分け表示",),
        panel_hint=(
            f"{_point_kind_list('stop_poi')}の位置です。",
            LayerTextSlot("axes", "評価軸", "が近傍のこれらを数えて算出しているものを、種別ごとの色分けで直接確認できます。"),
        ),
    ),
    # 種別ごとの鮮度の差を書く根拠は docs/modules/frontend/static-map-layers.md「点で示すもの」。
    "supply_poi": _tile_layer(
        "supply_poi",
        "amenity",
        chip_label="補給休憩",
        description=(f"{_point_kind_list('supply_poi')}の位置を種別ごとに色分け表示",),
        panel_hint=(
            f"{_point_kind_list('supply_poi')}の位置です。自販機は飲み物が買えると分かって"
            f"いるものだけを「{_row_label('supply_poi', 'vending_drinks')}」として出し、売っているものが分からないものは"
            f"「{_row_label('supply_poi', 'vending_unknown')}」として区別します[たばこ・切符の機械は出しません]。"
            f"{_row_label('supply_poi', 'convenience')}はOverture Mapsの地点のうちチェーンの店を、ほかはOSMのデータを出します。"
            "どれも閉店・撤去にデータが追いついていないことがあります。現地の状況と異なる場合があることをご留意ください。",
        ),
    ),
    "accident_point": _tile_layer(
        "accident_point",
        "trafficSafety",
        chip_label="事故",
        description=(
            "警察庁交通事故統計オープンデータ",
            LayerTextSlot("accidentYears", "[", "]"),
            "の発生地点を表示",
        ),
        panel_hint=(
            "警察庁が公開する交通事故統計オープンデータ[本票",
            LayerTextSlot("accidentYears", "、"),
            f"]の発生地点です。{size_text('accident_point')}",
        ),
    ),
    # 降水短時間予報より先は数値予報モデル（MSM）の計算値なので「予報」と呼ばない
    # （docs/architecture/data-sources.md「気象業務法の予報業務許可」節）。
    "precipitationNowcast": MapLayerSpec(
        "ownFetch",
        "weather",
        data_nature="dynamic",
        label="降水ナウキャスト",
        chip_label="降水",
        description=(
            "気象庁の降水ナウキャスト・降水短時間予報・線状降水帯予測マップ・線状降水帯の雨域と、数値予報モデルが計算した降水量を重ねて表示"
            f"[実況〜{_NOWCAST_REACH}先は5分刻み、{_NOWCAST_REACH}〜{_SHORT_RANGE_REACH}先は気象庁の降水短時間予報、"
            "以降は気象庁の数値予報モデルMSMの計算値を1時間刻みで、予報ではなく誤差を含みうる。"
            f"線状降水帯予測マップは現在〜{_LINEAR_RAINBAND_HOURS}時間先、線状降水帯の雨域は"
            f"実況〜{_RAINBAND_AREA_REACH}先の間だけ追加で重畳]",
        ),
        panel_hint=(
            "気象庁の高解像度降水ナウキャストです。ONにすると地図上に時刻スライダーが現れ、"
            f"実況[直近]から{_NOWCAST_REACH}先までの雨雲の分布を切り替えて確認できます。{_NOWCAST_REACH}より先は、"
            f"同じ気象庁の降水短時間予報へ自動的に切り替わり、{_SHORT_RANGE_REACH}先まで"
            "確認できます——こちらは実況の外挿ではなく数値予報モデルによる予測のため、先に"
            f"なるほど不確実性が増します。{_SHORT_RANGE_REACH}より先は、風と同じ仕組み[気象庁の数値予報モデルMSMが"
            "格子点ごとに計算した降水量]で、格子を降水強度に応じた色で塗る表示へさらに切り替わり、"
            "1〜3日先まで確認できます[降水短時間予報よりも粗い5kmメッシュのモデルの計算値で、予報ではなく"
            f"誤差を含みえます]。加えて、現在〜{_LINEAR_RAINBAND_HOURS}時間先の"
            f"間だけ、気象庁の線状降水帯予測マップを重ねて表示します[今後{_LINEAR_RAINBAND_HOURS}時間以内に大雨の"
            "おそれがある領域を赤で示すもので、予測は格子単位のため矩形に見えます。"
            "今まさに発生している線状降水帯の雨域を示すものではありません]。"
            f"今まさに発生している線状降水帯は、実況から{_RAINBAND_AREA_REACH}先までの間、その雨域を赤い輪郭線で重ねます"
            "[気象庁が線状降水帯を解析しているときだけ出ます]。"
            f"非公式の内部APIを利用している実況・{_NOWCAST_REACH}先までの"
            "部分・線状降水帯予測マップ・線状降水帯の雨域は、取得に失敗することがあります。",
        ),
    ),
    # 道路の色分け（向かい風・追い風）と見分けられる名前にする。
    "windVector": MapLayerSpec(
        "ownFetch",
        "weather",
        data_nature="dynamic",
        label="風[矢印]",
        chip_label="風",
        description=("気象庁の数値予報モデルMSMが計算した風向・風速を矢印で表示[1〜3日先まで。予報ではなく誤差を含みうる]",),
        panel_hint=(
            "気象庁MSM[メソ数値予報モデル、5kmメッシュ]が計算した風向・風速を格子点で矢印表示します。"
            "モデルの計算値で、予報ではなく、誤差を含みえます。"
            "矢印の向きが風向、長さ・太さ・色の濃淡が風速の強さを表します。ごく弱い風の地点は"
            "矢印を表示しません。ONにすると地図上に時刻スライダーが現れ、1時間刻みで切り替えられます"
            "[先まで見られる範囲は配信中の計算値の長さによって1〜3日の間で変わります]。",
            LayerTextSlot(
                "axes",
                "走行方位に対する向かい風/追い風の強さは、道路の色分けで評価軸",
                "を選ぶと別途確認できます。",
            ),
        ),
    ),
    # 予兆が出てからONにするのでは手遅れになるため既定ONにする。危険度が出ている間は広い範囲が
    # 塗られ、他の面レイヤー（緑と水・標高図）も基礎地図の色も覆われるが、危険度ゼロの領域は
    # 配信元のタイルが透明なので、影響が出るのは警戒度が上がっている間だけ。そのときは防災の
    # 情報を優先する（利用者はチップをOFFにすれば戻せる）。回避するしかない危険なので、評価軸には入れず表示だけにする。
    # 要素の名前と、時刻に対する振る舞いは要素の宣言から組み立てる。段の数と名前は凡例に並ぶので文に書かない。
    "disaster": MapLayerSpec(
        "ownFetch",
        "disaster",
        data_nature="dynamic",
        default_on=True,
        label="災害",
        chip_label="災害",
        description=(
            f"気象庁の{'・'.join(labels for labels, _, _ in _DISASTER_BY_FRAME_RULE)}をまとめて表示"
            f"[{'、'.join(f'{labels}は{brief}' for labels, brief, _ in _DISASTER_BY_FRAME_RULE)}]",
        ),
        panel_hint=(
            "気象庁の防災情報をまとめて表示します。"
            + "".join(labels + detail for labels, _, detail in _DISASTER_BY_FRAME_RULE)
            + "平常時は危険度ゼロの領域が透明のため、ONのままでも地図の見た目は"
            "変わりません。非公式の内部APIを利用しているため、取得に失敗することがあります。",
        ),
    ),
    # 候補を出したら見えている必要がある（探索の結果そのもの）。
    ROUTE_LAYER_ID: MapLayerSpec(
        "ownFetch",
        None,
        kind="dynamic",
        default_on=True,
        label="ルート",
        description=("選択中ルート沿いの情報", LayerTextSlot("routeLenses", "[", "]"), "を色分け表示"),
    ),
}


def map_layer_label(layer_id: str, spec: MapLayerSpec) -> str:
    """レイヤーの名前。一次属性を描くレイヤーは属性の名前で、どちらも無ければ生成の時点で落とす。"""
    if spec.label is not None:
        return spec.label
    attribute = next((attr for attr in PRIMARY_ATTRIBUTES if attr.attr_id == layer_id), None)
    if attribute is None:
        raise ValueError(f"地図レイヤー'{layer_id}'に名前が無い（一次属性でもない）")
    return attribute.label


def _map_layers() -> tuple[tuple[str, MapLayerSpec], ...]:
    """宣言を`_MAP_LAYER_IDS`と突き合わせる。名前の重なり（一次属性・気象のグループ・ルートが同じ名前）・
    宣言の過不足・説明の書き忘れは、どれも生成の時点で落とす。"""
    if sorted(_MAP_LAYER_IDS) != sorted(_LAYER_SPECS):
        raise ValueError(f"地図レイヤーの宣言が名前と合わない: {sorted(_MAP_LAYER_IDS)} / {sorted(_LAYER_SPECS)}")
    undescribed = [layer_id for layer_id, spec in _LAYER_SPECS.items() if not spec.description]
    if undescribed:
        raise ValueError(f"地図レイヤーに説明が無い: {undescribed}")
    return tuple(_LAYER_SPECS.items())


#: 地図に載るものの宣言（`_LAYER_SPECS`の順）。
MAP_LAYERS: tuple[tuple[str, MapLayerSpec], ...] = _map_layers()

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
    "detail": 6,
}

#: 縁取りは線の両側へ一定を足す。**個別に書かない**——線の太さを変えたときに縁取りだけ
#: 古い値で残ると、線が縁からはみ出す。
CASING_MARGIN_PX = 4
ROUTE_CASING_WIDTHS_PX: dict[str, float] = {
    role: ROUTE_LINE_WIDTHS_PX[role] + CASING_MARGIN_PX for role in ("composite", "detail")
}

#: 線の濃さ（役割ごと）。候補の参考線は選んだ候補より薄くする。
ROUTE_LINE_OPACITIES: dict[str, float] = {
    "selectedHalo": 0.25,
    "splice": 0.75,
    "candidate": 0.65,
    "arrowHalo": 0.95,
}

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
#: `igor`は傾きの大きさを`exaggeration * 2`倍してから角度へ直す。上限の1にする。
HILLSHADE_EXAGGERATION = 1
#: 陰影の濃さは影・光の色のalphaで渡す（hillshadeは不透明度のプロパティを持たない）。傾きが0の画素は
#: 影も光も出ないため、上げても平地は濁らない。
HILLSHADE_SHADOW_COLOR = f"rgba(60, 50, 40, {AREA_OPACITY})"
HILLSHADE_HIGHLIGHT_COLOR = f"rgba(255, 252, 245, {AREA_OPACITY})"
#: 標高の強調。**タイルの値は実際の標高のままで、読み方（復元式の係数）へ掛ける**
#: ——タイル側を書き換えると、同じタイルを別の倍率で読み直せなくなる。
#: 上げるほど緩い斜面が読めるが、上げすぎると急斜面との差が潰れる。
TERRAIN_EXAGGERATION = 5

#: 気象の記号。風は速さで大きさを変え、`WIND_FULL_SCALE_MS`で上限に達する。
WEATHER_MARK_HALO_WIDTH_PX = 1.5
WIND_ICON_SCALE_RANGE: tuple[float, float] = (0.9, 2.6)
WIND_FULL_SCALE_MS = 15
LIGHTNING_ICON_SCALE = 0.8
#: 記号を拡大する曲線（ズーム→倍率）。**気象の記号はどれも同じ曲線で拡大する**——家族ごとに別の曲線を使うと、
#: 同じ地図の中で拡大の速さが食い違う。`icon-size`は既定で画面上の固定ピクセルなので、曲線が無いと拡大するほど
#: 周囲の道路・建物だけが大きく描かれ、記号が相対的に小さくなる。初期表示のズーム（13）を倍率1に置く。
MARK_SIZE_BY_ZOOM: tuple[tuple[float, float], ...] = ((10, 0.75), (13, 1), (16, 1.5), (19, 2))
#: 洪水の川筋の太さ（ズーム→px）。低いズームで目立たせすぎず、拡大するほど個々の川筋を追えるようにする。
FLOOD_LINE_WIDTH_BY_ZOOM: tuple[tuple[float, float], ...] = ((6, 1.5), (10, 3), (14, 5))
#: 線状降水帯の雨域の輪郭線の太さ（px）と、下に敷く縁取りの太さ。配信元の公式の画面の描画定義の値
#: （`strokeWidth`と、縁取りはその+2）で、ズームによらない。
RAINBAND_OUTLINE_WIDTH_PX = 4
RAINBAND_OUTLINE_CASING_WIDTH_PX = RAINBAND_OUTLINE_WIDTH_PX + 2


#: 道の線。太さは意味を運ばない（意味は色だけ）ので、分類の線はすべて同じ太さ。
#: 横に分ける間隔は太さより狭くして隣どうしをわずかに重ねる——離すと1本の道が複数に見える。
ROAD_LINE_WIDTH_PX = 3
ROAD_TRACK_OFFSET_STEP_PX = 2
#: 分類がある道は濃く、値が無い・分類の外の道は薄く（消さずに薄くする）。薄い側も、基礎地図の地色に対して灰の線が
#: コントラスト比1.5を割らない濃さにする——割ると、道があるのに線が無いように見える。
ROAD_KNOWN_OPACITY = 0.8
ROAD_UNKNOWN_OPACITY = 0.6
#: 評価軸の下敷き（材料の線と一緒に出すときの太い帯）。材料の線より手前の段に重なるので、材料の線の色を隠さない薄さにする。
ROAD_UNDERLAY_OPACITY = 0.15
#: 詳細を見ている1本の強調。元の線が上に乗ったままになる太さにする。
ROAD_INSPECTED_WIDTH_PX = 8

#: 値が無い（不明・データなし）線の破線の刻み（線の太さを1とする長さ）。道の線・評価軸の線・ルートの線で共有する。
#: 乗り換え帯の破線（`ROUTE_SPLICE_DASH`）より細かく刻み、操作の状態と見分けられるようにする。
NO_DATA_DASH: tuple[float, ...] = (1, 2)

#: 丸い点の既定の半径。行ごとの大きさは表示の行（`DisplayCategorySpec.radius_px`）が持つ。
POINT_RADIUS_PX = 4
POINT_STROKE_WIDTH_PX = 1
#: 絵記号で描く点（行が`glyph`を持つ軸）の一辺。丸い点より大きくし、中の絵を読める大きさにする。
POINT_ICON_SIZE_PX = 20
POINT_OPACITY = 0.9


def _point_opacities() -> dict[str, float]:
    """地図に点で出す一次属性（点の幾何・行の定義・タイルの系統を持つもの）ごとの不透明度。行が宣言しなければ既定。"""
    return {
        attr.attr_id: POINT_OPACITY if attr.point_opacity is None else attr.point_opacity
        for attr in PRIMARY_ATTRIBUTES
        if attr.geometry == "point" and attr.display_axes and attr.tile_kind is not None
    }


#: 一次属性 → 点の不透明度。画面は点のレイヤーごとに自分の名前で引く。
POINT_OPACITY_BY_ATTR: dict[str, float] = _point_opacities()
