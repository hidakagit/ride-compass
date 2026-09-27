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
