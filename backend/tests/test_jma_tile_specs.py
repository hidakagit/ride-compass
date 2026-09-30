"""`domain/jma_tile_specs.py`——気象庁タイルの要素ごとの仕様（系統・ズームの偶奇と上限）から導くもの。

ここで見ないもの:
- 実データの無いズームを親から補間する処理 → `test_jma_tile_interpolation.py`
- プリウォームの対象ズーム → `test_jma_tile_prewarm_service.py`

導出の規則は架空の仕様で見る（配信元の実際の値を書き写さない）。
"""

import pytest

from app.domain import jma_tile_specs as specs

Spec = specs.JmaTileSpec
Element = specs.JmaElement


# ---- 実データのある最大ズーム ----


@pytest.mark.parametrize(
    ("zoom_use", "max_native", "expected"),
    [
        ("even", 10, 10),
        ("even", 11, 10),  # 偶数しか配らないのに上限が奇数なら1段下げる
        ("odd", 9, 9),
        ("odd", 10, 9),
        ("all", 11, 11),
    ],
)
def test_the_top_zoom_is_the_native_maximum_on_the_right_parity(zoom_use, max_native, expected):
    assert specs.effective_max_zoom(Spec(zoom_use, max_native)) == expected


# ---- そのズームに実データがあるか ----


@pytest.mark.parametrize(
    ("spec", "zoom", "native"),
    [
        (Spec("even", 10, min_zoom=4), 4, True),  # 下限ちょうど
        (Spec("even", 10, min_zoom=4), 3, False),  # 下限の下
        (Spec("even", 10, min_zoom=4), 10, True),  # 上限ちょうど
        (Spec("even", 10, min_zoom=4), 12, False),  # 上限の上
        (Spec("even", 10, min_zoom=4), 7, False),  # 偶奇が合わない
        (Spec("odd", 9, min_zoom=3), 7, True),
        (Spec("odd", 9, min_zoom=3), 8, False),
        (Spec("all", 9, min_zoom=3), 8, True),
    ],
)
def test_a_zoom_has_native_tiles_only_within_range_and_on_the_right_parity(spec, zoom, native):
    assert specs.has_native_tile(spec, zoom) is native


# ---- 補間の元にする親ズーム ----


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(
        specs,
        "JMA_ELEMENTS",
        {
            "even_el": Element("risk", ("t.json",), "latest", Spec("even", 10, min_zoom=4)),
            "all_el": Element("risk", ("t.json",), "latest", Spec("all", 10, min_zoom=4)),
            "no_tile_el": Element("nowc", ("t.json",), "nowcast"),
        },
    )


@pytest.mark.parametrize(
    ("element", "zoom", "parent"),
    [
        ("even_el", 5, 4),  # 奇数のズームは1つ上の偶数から補う
        ("even_el", 9, 8),
        ("even_el", 6, None),  # 実データがある
        ("even_el", 3, None),  # 下限の下
        ("even_el", 11, None),  # 上限の上はMapLibreの拡大に任せる
        ("all_el", 5, None),  # 偶奇の制約が無い
        ("no_tile_el", 5, None),  # タイルで配らない
        ("unknown_el", 5, None),
    ],
)
def test_the_parent_to_interpolate_from(table, element, zoom, parent):
    assert specs.source_zoom_for_interpolation(element, zoom) == parent


def test_no_parent_when_it_would_fall_below_the_lowest_zoom(monkeypatch):
    monkeypatch.setattr(
        specs, "JMA_ELEMENTS", {"odd_el": Element("risk", ("t.json",), "latest", Spec("odd", 9, min_zoom=4))}
    )

    # 4は奇数ではないので補うが、親の3は下限の下
    assert specs.source_zoom_for_interpolation("odd_el", 4) is None


# ---- 時刻一覧のパスとタイルの仕様 ----


def test_the_time_file_paths_are_the_element_files_under_its_path_group(monkeypatch):
    monkeypatch.setattr(specs, "JMA_ELEMENTS", {"el": Element("nowc", ("a.json", "b.json"), "nowcast")})

    assert specs.jma_target_times_paths("el") == ("bosai/jmatile/data/nowc/a.json", "bosai/jmatile/data/nowc/b.json")


def test_an_element_not_delivered_as_tiles_has_no_tile_spec(monkeypatch):
    monkeypatch.setattr(specs, "JMA_ELEMENTS", {"el": Element("nowc", ("a.json",), "nowcast")})

    with pytest.raises(ValueError):
        specs.jma_tile_spec("el")
    with pytest.raises(ValueError):
        specs.jma_tile_path(specs.JmaTile("el", FRAME, 5, 1, 2))


# ---- 時刻一覧の行をコマにする ----
# 時刻は"HHMM"で書く（読み方は時刻の文字列の大小だけを見る）。


def _row(basetime: str, validtime: str, member: str = "none", elements: tuple[str, ...] = ("el",)):
    return specs.TargetTimesRow(specs.JmaFrame(basetime, member, validtime), elements)


def test_a_nowcast_starts_at_the_latest_observation_of_the_element():
    rows = [
        _row("0900", "0900"),
        _row("0905", "0915"),
        _row("0905", "0905"),
        _row("0910", "0910", elements=("other",)),  # 別の要素の実況は最新の実況に数えない
        _row("0905", "0910"),
    ]

    assert specs.read_target_times("nowcast", rows, "el") == [
        ("0905", "none", "0905"),
        ("0905", "none", "0910"),
        ("0905", "none", "0915"),
    ]


def test_a_nowcast_without_an_observation_keeps_every_frame():
    rows = [_row("0900", "0920"), _row("0900", "0910")]

    assert specs.read_target_times("nowcast", rows, "el") == [("0900", "none", "0910"), ("0900", "none", "0920")]


def test_a_full_run_is_the_latest_run_with_several_valid_times_per_member():
    rows = [
        _row("0700", "0800", "a"),
        _row("0700", "0900", "a"),
        _row("0800", "0900", "a"),
        _row("0800", "1000", "a"),
        _row("0810", "0810", "a"),  # 中間ランの単発の行は完全なランではない
        _row("0805", "1000", "b"),  # 系列どうしで有効時刻が重なれば新しいランを採る
        _row("0805", "1100", "b"),
    ]

    assert specs.read_target_times("latestFullRun", rows, "el") == [
        ("0800", "a", "0900"),
        ("0805", "b", "1000"),
        ("0805", "b", "1100"),
    ]


def test_no_full_run_reads_as_no_frames():
    assert specs.read_target_times("latestFullRun", [_row("0810", "0810", "a")], "el") == []


def test_latest_is_the_newest_row_of_the_element():
    rows = [_row("0900", "0900", "a"), _row("0910", "0910", "b"), _row("0920", "0920", elements=("other",))]

    assert specs.read_target_times("latest", rows, "el") == [("0910", "b", "0910")]


@pytest.mark.parametrize("reader", ["nowcast", "latestFullRun", "latest"])
def test_no_rows_of_the_element_read_as_no_frames(reader):
    rows = [_row("0900", "0900", elements=("other",)), _row("0900", "1000", elements=("other",))]

    assert specs.read_target_times(reader, rows, "el") == []


# ---- コマの配信元のパス ----

FRAME = specs.JmaFrame("20260101000000", "immed0", "20260101003000")
DIR = "bosai/jmatile/data/risk/20260101000000/immed0/20260101003000/surf"


@pytest.fixture
def delivered(monkeypatch):
    monkeypatch.setattr(
        specs,
        "JMA_ELEMENTS",
        {
            "raster_el": Element("risk", ("t.json",), "latest", Spec("even", 10)),
            "vector_el": Element("risk", ("t.json",), "latest", Spec("even", 10, vector_layer="lines")),
            "points_el": Element("risk", ("t.json",), "latest"),
        },
    )


def test_a_tile_sits_under_its_frame_with_the_extension_of_its_kind(delivered):
    assert specs.jma_tile_path(specs.JmaTile("raster_el", FRAME, 5, 1, 2)) == f"{DIR}/raster_el/5/1/2.png"
    assert specs.jma_tile_path(specs.JmaTile("vector_el", FRAME, 5, 1, 2)) == f"{DIR}/vector_el/5/1/2.pbf"


def test_the_template_leaves_the_frame_and_the_tile_coordinates_to_fill(delivered):
    """画面は生成物のテンプレートをコマの項目名で埋め、タイル座標は地図ライブラリが埋める。"""
    frame_dir = "bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf"
    assert specs.jma_url_template("raster_el") == f"{frame_dir}/raster_el/{{z}}/{{x}}/{{y}}.png"
    assert specs.jma_url_template("points_el") == f"{frame_dir}/points_el/data.geojson?id=points_el"


def test_a_tile_path_reads_back_to_the_same_tile():
    """組み立てと読み戻しは同じ宣言から導く。宣言のある、タイルで配る要素すべてで往復する。"""
    tile_elements = [element_id for element_id, element in specs.JMA_ELEMENTS.items() if element.tile is not None]
    assert tile_elements
    for element_id in tile_elements:
        tile = specs.JmaTile(element_id, FRAME, 9, 454, 201)
        assert specs.read_jma_tile_path(specs.jma_tile_path(tile)) == tile, element_id


@pytest.mark.parametrize(
    "path",
    [
        f"{DIR}/raster_el/5/1/2.pbf",  # 要素の描き方と違う拡張子
        f"{DIR}/unknown_el/5/1/2.png",  # 宣言の無い要素
        f"{DIR}/points_el/data.geojson?id=points_el",  # タイルで配らない要素
        f"{DIR}/raster_el/5/1/two.png",
        "bosai/jmatile/data/risk/t.json",
    ],
)
def test_paths_that_are_not_declared_tiles_do_not_read(delivered, path):
    assert specs.read_jma_tile_path(path) is None
