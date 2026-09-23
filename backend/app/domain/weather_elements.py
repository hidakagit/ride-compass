"""動的気象で地図に描くものの宣言。画面（生成物経由）とプリウォーム（本番プロセス）の両方が読む。"""

from typing import Literal, NamedTuple

from app.domain.jma_tile_specs import (
    JMA_TILE_SPECS,
    JmaTileSpec,
    PathGroup,
    effective_max_zoom,
    jma_path_group,
    jma_target_time_files,
)

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
