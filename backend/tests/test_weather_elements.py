"""`domain/weather_elements.py`——動的気象で地図に描くものの宣言。

前半は`stage_first_frames`（時刻の段を1本の時系列へつないだときに各段が最初に描くコマ）。時刻は"HHMM"で書く
（つなぎ方は時刻の文字列の大小だけを見る）。後半は、宣言`WEATHER_ELEMENTS`が画面で1つの意味に読めること。
"""

from app.domain.jma_tile_specs import JmaFrame
from app.domain.weather_elements import (
    WEATHER_ELEMENTS,
    stage_first_frames,
    weather_element_deliveries,
    weather_element_tile,
)


def _frames(*validtimes: str) -> list[JmaFrame]:
    return [JmaFrame(validtime, "none", validtime) for validtime in validtimes]


def test_each_stage_continues_after_the_last_frame_of_the_stages_before():
    stages = [_frames("0900", "1000"), _frames("1000", "1100"), _frames("0930", "1200")]

    assert [frame and frame.validtime for frame in stage_first_frames(stages)] == ["0900", "1100", "1200"]


def test_a_stage_covered_by_the_stages_before_draws_nothing():
    stages = [_frames("0900", "1000"), _frames("0930")]

    assert [frame and frame.validtime for frame in stage_first_frames(stages)] == ["0900", None]


def test_after_an_empty_stage_the_next_continues_from_the_stage_before_it():
    stages = [_frames("0900"), [], _frames("0900", "1000")]

    assert [frame and frame.validtime for frame in stage_first_frames(stages)] == ["0900", None, "1000"]


def test_no_frames_in_any_stage():
    assert stage_first_frames([[], []]) == [None, None]


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
    その要素のコマを作れない（配信元の段の読み方が無ければ`weather_element_deliveries`が落ちる）。"""
    for element in WEATHER_ELEMENTS:
        name = f"{element.group}/{element.source}"
        if element.jma_elements:
            assert weather_element_deliveries(element), name
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
