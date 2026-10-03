"""`domain/weather_elements.py`——動的気象の要素の、タイルの仕様・配信の段・段をつないだ時系列の最初のコマ。

入口は`weather_element_tile`・`weather_element_deliveries`・`stage_first_frames`。要素は架空のものを作り、
配信要素の宣言`JMA_ELEMENTS`（本番の正本を持つ宣言のデータ）へは架空の配信要素を足して与える。

ここで見ないもの:
- 本番の要素の宣言`WEATHER_ELEMENTS`そのものの不変条件と、そこから導くまとまり → `test_map_display.py`
  （全要素のタイルの仕様と配信の段は、プリウォームと生成物の書き出しがimport・生成の時点で引く）
- 配信要素ごとのズーム・パス・時刻一覧の読み方 → `test_jma_tile_specs.py`
"""

import pytest

from app.domain import weather_elements
from app.domain.jma_tile_specs import JmaElement, JmaFrame, JmaTileSpec
from app.domain.weather_elements import (
    FrameRule,
    WeatherDelivery,
    WeatherElement,
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
}


@pytest.fixture
def _declared(monkeypatch):
    for element_id, element in DECLARED.items():
        monkeypatch.setitem(weather_elements.JMA_ELEMENTS, element_id, element)


def _element(kind, jma_elements, grid_value=None) -> WeatherElement:
    return WeatherElement("group", "source", kind, tuple(jma_elements), "架空", FrameRule("nearest"), grid_value)


@pytest.mark.usefixtures("_declared")
@pytest.mark.parametrize(
    ("kind", "jma_elements"),
    [("gridFill", ()), ("gridMark", ("t_points",)), ("outline", ("t_points",))],
)
def test_elements_not_drawn_from_tiles_have_no_tile_spec(kind, jma_elements):
    assert weather_element_tile(_element(kind, jma_elements)) is None


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
    ids=["no_delivery", "zoom_ranges_differ", "vector_layers_differ", "stage_not_delivered_as_tiles"],
)
def test_a_tile_element_whose_stages_cannot_share_one_source_is_refused(kind, jma_elements):
    with pytest.raises(ValueError):
        weather_element_tile(_element(kind, jma_elements))


@pytest.mark.usefixtures("_declared")
def test_each_stage_is_delivered_with_its_listings_template_reader_refresh_and_delay():
    deliveries = weather_element_deliveries(_element("outline", ["t_even10", "t_points"]))

    assert deliveries == [
        WeatherDelivery(
            "t_even10",
            ("bosai/jmatile/data/nowc/targetTimes_N1.json", "bosai/jmatile/data/nowc/targetTimes_N2.json"),
            "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/t_even10/{z}/{x}/{y}.png",
            "nowcast",
            weather_elements.JMA_REFRESH_INTERVAL_SECONDS["nowc"],
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


@pytest.mark.usefixtures("_declared")
def test_each_stage_refreshes_at_the_interval_of_its_own_path_group():
    deliveries = weather_element_deliveries(_element("rasterTile", ["t_even10", "t_even11", "t_even12"]))
    assert [delivery.refresh_interval_seconds for delivery in deliveries] == [
        weather_elements.JMA_REFRESH_INTERVAL_SECONDS[group] for group in ("nowc", "rasrf", "risk")
    ]


def test_an_element_drawn_from_its_own_grid_has_no_delivery():
    assert weather_element_deliveries(_element("gridFill", (), "precipitation")) == []


def test_an_undeclared_delivery_is_refused():
    with pytest.raises(KeyError):
        weather_element_deliveries(_element("rasterTile", ["t_undeclared"]))


def _frames(*validtimes: str) -> list[JmaFrame]:
    return [JmaFrame("base", "none", validtime) for validtime in validtimes]


@pytest.mark.parametrize(
    ("stages", "first_validtimes"),
    [
        ([], []),
        ([_frames("01", "02")], ["01"]),
        ([_frames("01", "02"), _frames("02", "03", "04")], ["01", "03"]),
        ([_frames("01", "05"), _frames("02", "03")], ["01", None]),
        ([_frames("01", "02"), [], _frames("02", "03")], ["01", None, "03"]),
        ([_frames("01", "05"), _frames("02", "03"), _frames("04", "06")], ["01", None, "06"]),
        ([[], _frames("01")], [None, "01"]),
    ],
    ids=[
        "no_stages",
        "one_stage",
        "next_stage_continues_after_the_last_frame_before",
        "stage_covered_by_the_stages_before",
        "empty_stage_is_skipped",
        "covered_stage_does_not_move_the_join",
        "first_stage_empty",
    ],
)
def test_each_stage_starts_after_the_last_frame_of_the_stages_before(stages, first_validtimes):
    first_frames = stage_first_frames(stages)
    assert [None if frame is None else frame.validtime for frame in first_frames] == first_validtimes
