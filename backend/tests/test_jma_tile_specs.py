"""`domain/jma_tile_specs.py`——気象庁の配信要素ごとの、タイルのズーム・配信元のパス・時刻一覧の読み方。

入口は、ズーム（`effective_max_zoom`・`has_native_tile`・`source_zoom_for_interpolation`・`jma_tile_spec`）、
配信元のパス（`jma_target_times_paths`・`jma_url_template`・`jma_tile_path`と読み戻しの`read_jma_tile_path`・
404の意味`is_final_absence`）、時刻一覧の行をコマにする`read_target_times`と、要素の宣言`JmaElement`の検証。

要素の宣言`JMA_ELEMENTS`は配信元の設定ファイルの写し（本番の正本を持つ宣言のデータ）なので中身に踏み込まず、
架空の要素へ差し替える。期待するパスの形は配信元のURL（`https://www.jma.go.jp/bosai/jmatile/data/...`）である。

ここで見ないもの:
- 動的気象の要素の段をつなぐこと・段ごとの配信の組み立て → `test_weather_elements.py`
- 時刻一覧の応答を行へ解くこと・取得とキャッシュ → `test_jma_tile_client.py`
- 画面が同じ読み方・同じパスになること → `scripts/cross_language_expectations.py: jma_expectations`の表を通す画面のテスト
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain import jma_tile_specs as specs
from app.domain.jma_tile_specs import JmaElement, JmaFrame, JmaTile, JmaTileSpec, TargetTimesRow

ELEMENTS = {
    "ras": JmaElement("nowc", ("targetTimes_N1.json", "targetTimes_N2.json"), "nowcast", JmaTileSpec("even", 10)),
    "ras2": JmaElement("risk", ("targetTimes.json",), "latest", JmaTileSpec("even", 11)),
    "vec": JmaElement("risk", ("targetTimes.json",), "latest", JmaTileSpec("even", 11, vector_layer="lines")),
    "oddz": JmaElement("rasrf", ("targetTimes.json",), "latestFullRun", JmaTileSpec("odd", 9)),
    "allz": JmaElement("rasrf", ("targetTimes.json",), "latest", JmaTileSpec("all", 8)),
    "pts": JmaElement("nowc", ("targetTimes_N3.json",), "nowcast", data_delay_minutes=10),
}


@pytest.fixture
def _elements(monkeypatch):
    monkeypatch.setattr(specs, "JMA_ELEMENTS", ELEMENTS)


# --- ズーム ---


@pytest.mark.parametrize(
    ("zoom_use", "max_native_zoom", "effective"),
    [("even", 10, 10), ("even", 11, 10), ("odd", 9, 9), ("odd", 10, 9), ("all", 11, 11)],
)
def test_the_usable_maximum_zoom_drops_to_the_parity_the_source_draws(zoom_use, max_native_zoom, effective):
    assert specs.effective_max_zoom(JmaTileSpec(zoom_use, max_native_zoom)) == effective


@pytest.mark.parametrize(
    ("spec", "native_zooms"),
    [
        (JmaTileSpec("even", 11), {4, 6, 8, 10}),
        (JmaTileSpec("odd", 10), {5, 7, 9}),
        (JmaTileSpec("all", 8), {4, 5, 6, 7, 8}),
    ],
    ids=["even", "odd", "all"],
)
def test_the_source_has_data_only_at_its_parity_between_the_minimum_and_the_usable_maximum(spec, native_zooms):
    assert {zoom for zoom in range(0, 16) if specs.has_native_tile(spec, zoom)} == native_zooms


@pytest.mark.usefixtures("_elements")
@pytest.mark.parametrize(
    ("element_id", "zoom", "source"),
    [
        ("ras2", 5, 4),
        ("ras2", 10, None),
        ("ras2", 11, None),
        ("ras2", 3, None),
        ("oddz", 4, None),
        ("allz", 6, None),
        ("pts", 5, None),
        ("undeclared", 5, None),
    ],
    ids=[
        "parent_at_the_minimum",
        "native",
        "above_the_usable_maximum_is_overzoomed_by_the_map",
        "below_the_minimum",
        "parent_below_the_minimum",
        "no_parity_constraint",
        "not_delivered_as_tiles",
        "undeclared",
    ],
)
def test_a_missing_zoom_is_interpolated_from_the_zoom_just_above_it(element_id, zoom, source):
    assert specs.source_zoom_for_interpolation(element_id, zoom) == source


@pytest.mark.usefixtures("_elements")
def test_the_tile_spec_is_given_only_for_declared_tile_elements():
    assert specs.jma_tile_spec("vec") == ELEMENTS["vec"].tile
    with pytest.raises(ValueError):
        specs.jma_tile_spec("pts")
    with pytest.raises(KeyError):
        specs.jma_tile_spec("undeclared")


def test_a_tile_element_cannot_declare_a_delivery_delay():
    """遅れのずらしは画面の読み方だけが持ち、タイルを温めるプリウォームは持たない。"""
    with pytest.raises(ValueError):
        JmaElement("nowc", ("targetTimes_N1.json",), "nowcast", JmaTileSpec("even", 10), data_delay_minutes=10)


# --- 配信元のパス ---


@pytest.mark.usefixtures("_elements")
def test_each_time_listing_of_an_element_is_under_its_path_group():
    assert specs.jma_target_times_paths("ras") == (
        "bosai/jmatile/data/nowc/targetTimes_N1.json",
        "bosai/jmatile/data/nowc/targetTimes_N2.json",
    )


@pytest.mark.usefixtures("_elements")
@pytest.mark.parametrize(
    ("element_id", "template"),
    [
        ("ras", "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/ras/{z}/{x}/{y}.png"),
        ("vec", "bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/vec/{z}/{x}/{y}.pbf"),
        ("pts", "bosai/jmatile/data/nowc/{basetime}/{member}/{validtime}/surf/pts/data.geojson?id=pts"),
    ],
    ids=["raster_png", "vector_pbf", "features_geojson"],
)
def test_the_frame_template_leaves_the_time_and_tile_fields_to_fill(element_id, template):
    assert specs.jma_url_template(element_id) == template


@pytest.mark.usefixtures("_elements")
def test_a_tile_path_fills_the_frame_and_the_tile_coordinates():
    tile = JmaTile("ras", JmaFrame("20260701000000", "none", "20260701001000"), 6, 57, 25)
    assert specs.jma_tile_path(tile) == (
        "bosai/jmatile/data/nowc/20260701000000/none/20260701001000/surf/ras/6/57/25.png"
    )


@pytest.mark.usefixtures("_elements")
def test_an_element_not_delivered_as_tiles_has_no_tile_path():
    with pytest.raises(ValueError):
        specs.jma_tile_path(JmaTile("pts", JmaFrame("20260701000000", "none", "20260701000000"), 6, 57, 25))


_timestamps = st.datetimes().map(lambda moment: moment.strftime("%Y%m%d%H%M%S"))
_segments = st.text(alphabet=st.characters(categories=["Ll", "Lu", "Nd"], codec="ascii"), min_size=1, max_size=8)


@pytest.mark.usefixtures("_elements")
@given(
    element_id=st.sampled_from(["ras", "ras2", "vec", "oddz", "allz"]),
    frame=st.builds(JmaFrame, _timestamps, st.one_of(st.just("none"), _segments), _timestamps),
    z=st.integers(min_value=0, max_value=20),
    x=st.integers(min_value=0, max_value=2**20),
    y=st.integers(min_value=0, max_value=2**20),
)
def test_a_tile_path_reads_back_as_the_same_tile(element_id, frame, z, x, y):
    tile = JmaTile(element_id, frame, z, x, y)
    assert specs.read_jma_tile_path(specs.jma_tile_path(tile)) == tile


@pytest.mark.usefixtures("_elements")
@pytest.mark.parametrize(
    "path",
    [
        "bosai/jmatile/data/nowc/targetTimes_N1.json",
        "bosai/jmatile/data/nowc/20260701000000/none/20260701000000/surf/pts/data.geojson?id=pts",
        "bosai/jmatile/data/nowc/20260701000000/none/20260701000000/surf/other/6/57/25.png",
        "bosai/jmatile/data/nowc/20260701000000/none/20260701000000/surf/ras/6/57/25.pbf",
        "bosai/jmatile/data/nowc/20260701000000/none/20260701000000/surf/ras/z/57/25.png",
        "bosai/jmatile/data/nowc/20260701000000/none/20260701000000/surf/ras/6/57/25.png?v=1",
    ],
    ids=["time_listing", "features", "undeclared_element", "wrong_extension", "non_numeric_zoom", "trailing_query"],
)
def test_paths_that_are_not_a_declared_tile_read_as_nothing(path):
    assert specs.read_jma_tile_path(path) is None


@pytest.mark.usefixtures("_elements")
@pytest.mark.parametrize(
    ("path", "final"),
    [
        ("bosai/jmatile/data/nowc/20260701000000/none/20260701001000/surf/ras/6/57/25.png", True),
        ("bosai/jmatile/data/nowc/20260701000000/none/20260701000000/surf/pts/data.geojson?id=pts", False),
    ],
    ids=["tile", "features_not_yet_delivered"],
)
def test_only_a_missing_features_file_may_still_be_delivered_later(path, final):
    """地物は配信されるまで404、配信後は地物が無くても200。タイルと時刻一覧の404は確定した事実。"""
    assert specs.is_final_absence(path) is final


# --- 時刻一覧の行をコマにする ---


def _frame(basetime: str, validtime: str, member: str = "none") -> JmaFrame:
    return JmaFrame(basetime, member, validtime)


def _rows(*frames: JmaFrame, elements: tuple[str, ...] = ("el",)) -> list[TargetTimesRow]:
    return [TargetTimesRow(frame, elements) for frame in frames]


def test_rows_of_other_elements_on_the_same_listing_are_ignored():
    mine = _frame("0100", "0100")
    rows = [TargetTimesRow(_frame("0110", "0110"), ("other",)), TargetTimesRow(mine, ("other", "el"))]
    assert specs.read_target_times("nowcast", rows, "el") == [mine]


def test_a_nowcast_starts_at_its_latest_observation_and_runs_in_valid_time_order():
    old_observation = _frame("0050", "0050")
    latest_observation = _frame("0100", "0100")
    forecasts = [_frame("0100", "0110"), _frame("0100", "0105")]
    rows = _rows(forecasts[0], latest_observation, old_observation, forecasts[1])

    assert specs.read_target_times("nowcast", rows, "el") == [latest_observation, forecasts[1], forecasts[0]]


def test_a_nowcast_without_any_observation_keeps_every_frame_in_order():
    rows = _rows(_frame("0100", "0110"), _frame("0100", "0105"))
    assert specs.read_target_times("nowcast", rows, "el") == [_frame("0100", "0105"), _frame("0100", "0110")]


def test_latest_reads_only_the_newest_base_time():
    rows = _rows(_frame("0100", "0100"), _frame("0110", "0110"), _frame("0050", "0050"))
    assert specs.read_target_times("latest", rows, "el") == [_frame("0110", "0110")]


def test_latest_of_an_element_without_rows_has_no_frames():
    assert specs.read_target_times("latest", _rows(_frame("0100", "0100"), elements=("other",)), "el") == []


def test_a_full_run_is_the_newest_run_with_several_valid_times_and_single_time_runs_are_skipped():
    full_old = [_frame("00", "01"), _frame("00", "02")]
    full_new = [_frame("03", "04"), _frame("03", "05")]
    single_newer = [_frame("06", "07")]
    rows = _rows(*full_new, *single_newer, *full_old)

    assert specs.read_target_times("latestFullRun", rows, "el") == full_new


def test_each_member_takes_its_own_full_run_and_the_newer_run_wins_where_valid_times_overlap():
    member_a = [_frame("03", "04", "a"), _frame("03", "05", "a")]
    member_b = [_frame("00", "05", "b"), _frame("00", "06", "b")]
    only_single = [_frame("09", "10", "c")]
    rows = _rows(*member_b, *only_single, *member_a)

    assert specs.read_target_times("latestFullRun", rows, "el") == [member_a[0], member_a[1], member_b[1]]
