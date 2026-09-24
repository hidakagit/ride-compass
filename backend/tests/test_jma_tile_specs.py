"""`domain/jma_tile_specs.py`——気象庁タイルの要素ごとの仕様（系統・ズームの偶奇と上限）から導くもの。

ここで見ないもの:
- 実データの無いズームを親から補間する処理 → `test_jma_tile_interpolation.py`
- プリウォームの対象ズーム → `test_jma_tile_prewarm_service.py`

導出の規則は架空の仕様で見る（配信元の実際の値を書き写さない）。宣言そのものには、全要素に対して
成り立つべき不変条件（系統と時刻一覧の対応）だけを当てる。
"""

from typing import get_args

import pytest

from app.domain import jma_tile_specs as specs

Spec = specs.JmaTileSpec


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
    assert specs.effective_max_zoom(Spec("risk", zoom_use, max_native)) == expected


# ---- そのズームに実データがあるか ----


@pytest.mark.parametrize(
    ("spec", "zoom", "native"),
    [
        (Spec("risk", "even", 10, min_zoom=4), 4, True),  # 下限ちょうど
        (Spec("risk", "even", 10, min_zoom=4), 3, False),  # 下限の下
        (Spec("risk", "even", 10, min_zoom=4), 10, True),  # 上限ちょうど
        (Spec("risk", "even", 10, min_zoom=4), 12, False),  # 上限の上
        (Spec("risk", "even", 10, min_zoom=4), 7, False),  # 偶奇が合わない
        (Spec("risk", "odd", 9, min_zoom=3), 7, True),
        (Spec("risk", "odd", 9, min_zoom=3), 8, False),
        (Spec("risk", "all", 9, min_zoom=3), 8, True),
    ],
)
def test_a_zoom_has_native_tiles_only_within_range_and_on_the_right_parity(spec, zoom, native):
    assert specs.has_native_tile(spec, zoom) is native


# ---- 補間の元にする親ズーム ----


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(
        specs,
        "JMA_TILE_SPECS",
        {"even_el": Spec("risk", "even", 10, min_zoom=4), "all_el": Spec("risk", "all", 10, min_zoom=4)},
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
        ("unknown_el", 5, None),
    ],
)
def test_the_parent_to_interpolate_from(table, element, zoom, parent):
    assert specs.source_zoom_for_interpolation(element, zoom) == parent


def test_no_parent_when_it_would_fall_below_the_lowest_zoom(monkeypatch):
    monkeypatch.setattr(specs, "JMA_TILE_SPECS", {"odd_el": Spec("risk", "odd", 9, min_zoom=4)})

    # 4は奇数ではないので補うが、親の3は下限の下
    assert specs.source_zoom_for_interpolation("odd_el", 4) is None


# ---- 系統と時刻一覧 ----


def test_the_path_group_comes_from_whichever_table_has_the_element():
    tile_id = next(iter(specs.JMA_TILE_SPECS))
    non_tile_id = next(iter(specs.JMA_NON_TILE_PATH_GROUPS))

    assert specs.jma_path_group(tile_id) == specs.JMA_TILE_SPECS[tile_id].path_group
    assert specs.jma_path_group(non_tile_id) == specs.JMA_NON_TILE_PATH_GROUPS[non_tile_id]


def test_an_unknown_element_has_no_path_group():
    with pytest.raises(KeyError):
        specs.jma_path_group("no_such_element")


def test_every_element_belongs_to_exactly_one_table():
    assert not set(specs.JMA_TILE_SPECS) & set(specs.JMA_NON_TILE_PATH_GROUPS)


def test_every_path_group_has_its_time_files():
    assert set(get_args(specs.PathGroup)) == set(specs.JMA_TARGET_TIME_FILES)


def test_every_element_resolves_to_time_files_of_its_own_group():
    # 全要素が時刻一覧を引ける——複数のファイルに分かれる系統では、要素ごとの分け方の宣言が要る
    elements = [*specs.JMA_TILE_SPECS, *specs.JMA_NON_TILE_PATH_GROUPS]
    assert elements

    for element in elements:
        group = specs.jma_path_group(element)
        files = specs.jma_target_time_files(element)
        assert files and set(files) <= set(specs.JMA_TARGET_TIME_FILES[group])


def test_an_element_of_a_split_group_without_its_own_files_is_an_error(monkeypatch):
    split = next(group for group, files in specs.JMA_TARGET_TIME_FILES.items() if len(files) > 1)
    monkeypatch.setattr(specs, "JMA_NON_TILE_PATH_GROUPS", {"undeclared": split})

    with pytest.raises(KeyError):
        specs.jma_target_time_files("undeclared")
