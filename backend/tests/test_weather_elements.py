"""`domain/weather_elements.py`——動的気象の要素の、タイルの仕様・配信の段・段をつないだ時系列の最初のコマ。

入口は`weather_element_tile`・`weather_element_deliveries`・`stage_first_frames`・`forecast_reach`。前半は要素を架空のもので作り、
配信要素の宣言`JMA_ELEMENTS`（本番の正本を持つ宣言のデータ）へは架空の配信要素を足して与える。
後半は差し替えず、本番の宣言`WEATHER_ELEMENTS`の全要素が画面で1つの意味に読めることを見る（型では守れない、
要素どうしの組の不変条件）。

ここで見ないもの:
- 配信要素ごとのズーム・パス・時刻一覧の読み方 → `test_jma_tile_specs.py`
"""

import pytest

from app.domain import weather_elements
from app.domain.jma_tile_specs import JmaElement, JmaFrame, JmaTileSpec
from app.domain.weather_elements import (
    WEATHER_ELEMENTS,
    FrameRule,
    WeatherDelivery,
    WeatherElement,
    forecast_reach,
    stage_first_frames,
    weather_element_deliveries,
    weather_element_tile,
)

DECLARED = {
    "t_even10": JmaElement("nowc", ("targetTimes_N1.json", "targetTimes_N2.json"), "nowcast", JmaTileSpec("even", 10)),
    "t_even11": JmaElement("rasrf", ("targetTimes.json",), "latestFullRun", JmaTileSpec("even", 11)),
    "t_even12": JmaElement("risk", ("targetTimes.json",), "latest", JmaTileSpec("even", 12)),
    "t_vector": JmaElement("risk", ("targetTimes.json",), "latest", JmaTileSpec("even", 10, vector_layer="lines")),
    "t_points": JmaElement("nowc", ("targetTimes_N3.json",), "nowcast", data_delay_minutes=10),
    "t_reach45": JmaElement("nowc", ("targetTimes_N3.json",), "nowcast", forecast_minutes=45),
    "t_reach45b": JmaElement("nowc", ("targetTimes_N3.json",), "nowcast", forecast_minutes=45),
    "t_reach120": JmaElement("rasrf", ("targetTimes.json",), "latestFullRun", forecast_minutes=120),
}


@pytest.fixture
def _declared(monkeypatch):
    for element_id, element in DECLARED.items():
        monkeypatch.setitem(weather_elements.JMA_ELEMENTS, element_id, element)


def _element(kind, jma_elements, grid_value=None) -> WeatherElement:
    return WeatherElement("group", "source", kind, tuple(jma_elements), "架空", FrameRule("nearest"), grid_value)


def test_an_element_not_drawn_from_tiles_has_no_tile_spec():
    assert weather_element_tile(_element("gridFill", ())) is None


@pytest.mark.usefixtures("_declared")
def test_stages_sharing_one_zoom_range_give_the_first_stage_spec():
    """最大ズームは偶奇へ下げた後で比べる（10と11はどちらも10まで）。"""
    element = _element("rasterTile", ["t_even10", "t_even11"])
    assert weather_element_tile(element) == DECLARED["t_even10"].tile


@pytest.mark.usefixtures("_declared")
@pytest.mark.parametrize(
    ("kind", "jma_elements"),
    [
        ("rasterTile", ()),
        ("rasterTile", ["t_even10", "t_even12"]),
        ("vectorTile", ["t_vector", "t_even10"]),
        ("rasterTile", ["t_even10", "t_points"]),
    ],
    ids=["no_delivery", "max_zooms_differ", "vector_layers_differ", "stage_not_delivered_as_tiles"],
)
def test_a_tile_element_whose_stages_cannot_share_one_source_is_refused(kind, jma_elements):
    with pytest.raises(ValueError):
        weather_element_tile(_element(kind, jma_elements))


@pytest.mark.usefixtures("_declared")
def test_each_stage_is_delivered_with_its_listings_template_reader_refresh_and_delay():
    deliveries = weather_element_deliveries(_element("outline", ["t_even11", "t_points"]))

    assert deliveries == [
        WeatherDelivery(
            "t_even11",
            ("bosai/jmatile/data/rasrf/targetTimes.json",),
            "bosai/jmatile/data/rasrf/{basetime}/{member}/{validtime}/surf/t_even11/{z}/{x}/{y}.png",
            "latestFullRun",
            weather_elements.JMA_REFRESH_INTERVAL_SECONDS["rasrf"],
            0,
        ),
        WeatherDelivery(
            "t_points",
            ("bosai/jmatile/data/nowc/targetTimes_N3.json",),
            "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/t_points/data.geojson?id=t_points",
            "nowcast",
            weather_elements.JMA_REFRESH_INTERVAL_SECONDS["nowc"],
            10,
        ),
    ]


def _frames(*validtimes: str) -> list[JmaFrame]:
    return [JmaFrame("base", "none", validtime) for validtime in validtimes]


@pytest.mark.parametrize(
    ("stages", "first_validtimes"),
    [
        ([_frames("01", "02"), _frames("02", "03", "04")], ["01", "03"]),
        ([_frames("01", "05"), _frames("02", "03"), _frames("04", "06")], ["01", None, "06"]),
    ],
    ids=["next_stage_continues_after_the_last_frame_before", "covered_stage_does_not_move_the_join"],
)
def test_each_stage_starts_after_the_last_frame_of_the_stages_before(stages, first_validtimes):
    first_frames = stage_first_frames(stages)
    assert [None if frame is None else frame.validtime for frame in first_frames] == first_validtimes


def test_気象の要素はチップ_名前付きソース_描き方の組で一意() -> None:
    """同じ組が2件あると、画面では同じソース・レイヤーへ畳まれて片方が黙って消える。"""
    keys = [(element.group, element.source, element.kind) for element in WEATHER_ELEMENTS]
    assert len(keys) == len(set(keys))


def test_同じ名前付きソースの気象の要素は同じ呼び名を持つ() -> None:
    """画面は名前付きソース1つを1行として呼ぶ。描き方違いの要素で名前が違うと、どちらを出すか決まらない。"""
    labels: dict[tuple[str, str], str] = {}
    for element in WEATHER_ELEMENTS:
        assert labels.setdefault((element.group, element.source), element.label) == element.label, (
            f"{element.group}/{element.source}"
        )


def test_タイルで描く気象の要素は配信元の仕様を持つ() -> None:
    """仕様が無いと画面はズーム範囲を知らずにソースを作ることになる。"""
    tiled = [element for element in WEATHER_ELEMENTS if element.kind in ("rasterTile", "vectorTile")]
    assert tiled, "タイルで描く気象の要素が1つも無い"
    for element in tiled:
        tile = weather_element_tile(element)
        assert tile is not None, f"{element.group}/{element.source}"
        if element.kind == "vectorTile":
            assert tile.vector_layer is not None, f"{element.group}/{element.source} のベクタのレイヤー名が無い"


def test_配信元から取る段はすべて時刻一覧のファイルを持つ() -> None:
    """ファイルが無いと画面は時刻一覧を取りに行けない。"""
    for element in WEATHER_ELEMENTS:
        for delivery in weather_element_deliveries(element):
            assert delivery.target_times_paths, f"{element.group}/{element.source} の {delivery.element_id}"


def test_どの要素も時刻の読み方を持つ() -> None:
    """配信元から取る段は時刻一覧の読み方を、自前の格子から描く要素は読む値を持つ。無いと画面は
    その要素のコマを作れない（配信元の段の読み方は宣言が持ち、宣言が無ければ上のテストの`weather_element_deliveries`が落ちる）。"""
    for element in WEATHER_ELEMENTS:
        name = f"{element.group}/{element.source}"
        if element.jma_elements:
            assert element.grid_value is None, f"{name} は配信元から取るのに格子の値を持つ"
        else:
            assert element.grid_value is not None, f"{name} は読む格子の値を持たない"


def test_同じ名前付きソースの気象の要素は同じコマの規則を持つ() -> None:
    """1つのソースの時刻の段は1本の時系列につながる。規則が違うと、どの規則でコマを選ぶか決まらない。"""
    rules: dict[tuple[str, str], object] = {}
    for element in WEATHER_ELEMENTS:
        key = (element.group, element.source)
        assert rules.setdefault(key, element.frame_rule) == element.frame_rule, f"{element.group}/{element.source}"


def test_配信元から取る気象の要素はチップと名前付きソースで一意() -> None:
    """画面のデータ層は（チップ, 名前付きソース）から配信要素idを引く。2件あるとどちらを取るか決まらない。"""
    keys = [(element.group, element.source) for element in WEATHER_ELEMENTS if element.jma_elements]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(("element_ids", "words"), [(("t_reach45", "t_reach45b"), "45分"), (("t_reach120",), "2時間")])
def test_the_reach_of_the_forecast_is_told_from_the_declared_minutes(_declared, element_ids, words):
    """地図の説明・凡例の「実況〜N分先」は配信の宣言の値から作る。宣言を変えて文が追従しないと、届かない先まで出ると書く。"""
    assert forecast_reach(*element_ids) == words


@pytest.mark.parametrize("element_ids", [("t_reach45", "t_reach120"), ("t_reach45", "t_points")], ids=["届く先が違う", "予測の無い要素"])
def test_the_reach_is_refused_for_elements_that_do_not_reach_alike(_declared, element_ids):
    """1つの語で言えない並びに、どちらかの届く先を書かない。"""
    with pytest.raises(ValueError, match="そろっていない"):
        forecast_reach(*element_ids)
