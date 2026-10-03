"""動的気象で地図に描くものの宣言。画面（生成物経由）とプリウォーム（本番プロセス）の両方が読む。"""

from collections.abc import Sequence
from typing import Literal, NamedTuple

from app.domain.jma_tile_specs import (
    JMA_ELEMENTS,
    JMA_REFRESH_INTERVAL_SECONDS,
    JmaFrame,
    JmaTileSpec,
    TargetTimesReader,
    effective_max_zoom,
    jma_target_times_paths,
    jma_tile_spec,
    jma_url_template,
)

#: 動的気象の描き方の種類。配信元が描いた画像（`rasterTile`）・配信元の地物（`vectorTile`）・
#: 自前の格子の面（`gridFill`）・格子や地点の記号（`gridMark`）・配信元がGeoJSONで配る領域の輪郭線（`outline`）。
WeatherRenderKind = Literal["rasterTile", "vectorTile", "gridFill", "gridMark", "outline"]
_TILE_KINDS: frozenset[str] = frozenset({"rasterTile", "vectorTile"})

#: 選んだ時刻に対してどのコマを描くか。
#: - `nearest`: 範囲内で一番近いコマ。範囲の外の時刻には描かない（古いコマを出し続けない）。
#: - `latestObservation`: 観測だけが届く要素。観測は「今」より遅れて届くので、最新の観測から
#:   `window_minutes`先までは最新の観測を出し、それより先には描かない（先の観測は存在しない）。
#: - `current`: 「現在」の単一値。`window_minutes`が無ければ時刻によらず描き、あれば現在から
#:   その幅の間だけ描く（予報の意味そのものが「今後N時間」のもの）。
FrameRuleKind = Literal["nearest", "latestObservation", "current"]

#: 自前のMSM格子から描く要素が読む値。
GridValue = Literal["precipitation", "wind"]

#: 配信元が値の段ごとに色を焼き込んで配る要素の、その段の宣言（`domain/weather_display.py`。生成物
#: `weather-scales.json`の同じ名前の鍵）。
LevelScale = Literal["risk_levels", "thunder_activity", "tornado_potential"]


class FrameRule(NamedTuple):
    kind: FrameRuleKind
    window_minutes: int | None = None


_NEAREST = FrameRule("nearest")


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
    #: 全段が`JMA_ELEMENTS`にタイルの仕様を持ち、ソースのズーム範囲は1つなので段の間で一致する。
    #: 自前のMSM格子から描くものは空。
    jma_elements: tuple[str, ...]
    #: 画面で要素を呼ぶ名前（▶パネルで要素ごとに表示を切り替える行の名前）。同じ名前付き
    #: ソースの要素は同じ名前を持つ。
    label: str
    #: 選んだ時刻に対して描くコマの規則。同じ名前付きソースの要素は同じ規則を持つ
    #: （1つのソースの時刻の段は1本の時系列につながる）。
    frame_rule: FrameRule
    #: 自前のMSM格子から描く要素が読む値。配信元から取る要素はNone。
    grid_value: GridValue | None = None
    #: 地図がこの要素を塗る段。災害のチップは、同じ段で塗る要素の名前を見出しにして段を凡例に並べる。
    #: 段を持たない要素（記号・格子の塗り・輪郭線）と、凡例を別に持つ降水の要素はNone。
    level_scale: LevelScale | None = None


#: 並びが同じ段（面・線・記号）の中の重なり順になる。災害は面を下に、見落としやすい線（洪水）・
#: 点（落雷）を上に置き、大雨は土砂・浸水を統合した指標なので個別の2つより下に置く。
WEATHER_ELEMENTS: tuple[WeatherElement, ...] = (
    # 降水。60分先までは降水ナウキャスト、その先15時間先までは降水短時間予報を配信元のラスタで、
    # それ以降は自前の格子を塗る。どれが届くかは選んだ時刻で決まる。
    WeatherElement("precipitationNowcast", "main", "rasterTile", ("hrpns", "rasrf"), "降水", _NEAREST),
    WeatherElement("precipitationNowcast", "main", "gridFill", (), "降水", _NEAREST, "precipitation"),
    # 「今後3時間以内に大雨のおそれ」という予報なので、現在から3時間先の間だけ重ねる。
    WeatherElement(
        "precipitationNowcast",
        "linearRainband",
        "rasterTile",
        ("sjfcstmap",),
        "線状降水帯予測",
        FrameRule("current", 3 * 60),
    ),
    # 今まさに追跡中の線状降水帯の雨域（実況と30分先まで）。公式の既定の表示と同じく2つを同じ見た目で重ねる。
    WeatherElement(
        "precipitationNowcast", "linearRainbandArea", "outline", ("slmcs_unify",), "線状降水帯の雨域", _NEAREST
    ),
    WeatherElement(
        "precipitationNowcast",
        "linearRainbandAreaForecast",
        "outline",
        ("slmcs_unifyfcst",),
        "線状降水帯の雨域",
        _NEAREST,
    ),
    WeatherElement("windVector", "arrow", "gridMark", (), "風", _NEAREST, "wind"),
    # キキクルは「現在の危険度」だけを配るので、選んだ時刻によらず描く。
    WeatherElement(
        "disaster",
        "heavyRain",
        "rasterTile",
        ("rain_mesh",),
        "大雨キキクル",
        FrameRule("current"),
        level_scale="risk_levels",
    ),
    WeatherElement(
        "disaster",
        "landslide",
        "rasterTile",
        ("land",),
        "土砂災害キキクル",
        FrameRule("current"),
        level_scale="risk_levels",
    ),
    WeatherElement(
        "disaster",
        "inundation",
        "rasterTile",
        ("inund",),
        "浸水キキクル",
        FrameRule("current"),
        level_scale="risk_levels",
    ),
    WeatherElement(
        "disaster", "thunder", "rasterTile", ("thns",), "雷ナウキャスト", _NEAREST, level_scale="thunder_activity"
    ),
    WeatherElement(
        "disaster", "tornado", "rasterTile", ("trns",), "竜巻発生確度", _NEAREST, level_scale="tornado_potential"
    ),
    WeatherElement(
        "disaster",
        "flood",
        "vectorTile",
        ("flood",),
        "洪水キキクル[河川]",
        FrameRule("current"),
        level_scale="risk_levels",
    ),
    # 落雷は予測を持たない。遅れの幅は配信の遅れの実績値へ余裕を足した上限。
    WeatherElement("disaster", "liden", "gridMark", ("liden",), "落雷[発生地点]", FrameRule("latestObservation", 20)),
)


def weather_element_tile(element: WeatherElement) -> JmaTileSpec | None:
    """タイルで描く要素の配信元仕様。タイルで描かない要素はNone。

    段ごとに仕様が違っても、1つのソースが持てるズーム範囲とベクタのレイヤー名は1つだけなので、
    食い違えば`ValueError`。タイルで配らない配信要素を段に持つときも`ValueError`。"""
    if element.kind not in _TILE_KINDS:
        return None
    if not element.jma_elements:
        raise ValueError(f"タイルで描く要素に配信要素idが無い: {element.group}/{element.source}")
    specs = [jma_tile_spec(element_id) for element_id in element.jma_elements]
    shapes = {(spec.min_zoom, effective_max_zoom(spec), spec.vector_layer) for spec in specs}
    if len(shapes) > 1:
        raise ValueError(f"時刻の段の間でタイルのズーム範囲が食い違う: {element.group}/{element.source} {shapes}")
    return specs[0]


class WeatherDelivery(NamedTuple):
    """配信元から取る時刻の段1つ。"""

    element_id: str
    #: その要素の行が載る時刻一覧の、配信元のパス。
    target_times_paths: tuple[str, ...]
    #: コマの配信元のパスのテンプレート（`jma_tile_specs.jma_url_template`）。
    url_template: str
    reader: TargetTimesReader
    refresh_interval_seconds: int
    #: 配信の遅れ（`domain/jma_tile_specs.py: JmaElement.data_delay_minutes`）。
    data_delay_minutes: int


def weather_element_deliveries(element: WeatherElement) -> list[WeatherDelivery]:
    """配信元から取る段（近い時刻から）。自前のMSM格子から描く要素は空。

    宣言の無い配信要素は`KeyError`。"""
    deliveries = []
    for element_id in element.jma_elements:
        declared = JMA_ELEMENTS[element_id]
        deliveries.append(
            WeatherDelivery(
                element_id,
                jma_target_times_paths(element_id),
                jma_url_template(element_id),
                declared.reader,
                JMA_REFRESH_INTERVAL_SECONDS[declared.path_group],
                declared.data_delay_minutes,
            )
        )
    return deliveries


def stage_first_frames(stage_frames: Sequence[Sequence[JmaFrame]]) -> list[JmaFrame | None]:
    """時刻の段（近い時刻から、各段のコマは`validtime`の順）を1本の時系列へつないだとき、各段が最初に描くコマ。
    時系列に1コマも残らない段はNone。

    各段は前の段までの最後のコマより後の時刻だけを継ぎ、途中の段が空なら、その前の段の直後から次の段が継ぐ。
    画面も同じつなぎ方で時系列を作る。同じコマになることは、場面ごとの段とこの関数の答えを
    `scripts/cross_language_expectations.py: jma_expectations`が表にして配り、画面のテストが通す。"""
    first_frames: list[JmaFrame | None] = []
    last_validtime = ""
    for frames in stage_frames:
        continuing = [frame for frame in frames if frame.validtime > last_validtime]
        first_frames.append(continuing[0] if continuing else None)
        last_validtime = max([last_validtime, *(frame.validtime for frame in continuing)])
    return first_frames


#: 気象のまとまり（チップ）。要素の宣言から導く——並びは最初に現れた順。
WEATHER_LAYER_GROUPS: tuple[str, ...] = tuple(dict.fromkeys(element.group for element in WEATHER_ELEMENTS))
