"""`domain/jma_tile_specs.py`（配信元ズーム仕様からの上限導出）のテスト。

このロジックが無かった頃、各レイヤーのmaxzoomはfrontend/backendそれぞれで手書きされて
おり、配信元の`zoomUse`と`maxNativeZoom`の突き合わせを誤って7要素中6要素が実データの
無いズームを指していた。導出結果そのものを固定して再発を防ぐ。
"""

import pytest

from app.domain.jma_tile_specs import (
    JMA_TILE_SPECS,
    JmaTileSpec,
    effective_max_zoom,
    max_zoom_for,
)


@pytest.mark.parametrize(
    ("zoom_use", "max_native_zoom", "expected"),
    [
        # maxNativeZoomが使用する偶奇と一致する場合はそのまま。
        ("even", 10, 10),
        ("odd", 9, 9),
        # 一致しない場合、そのズームのタイルは存在しないため1段下げる。
        ("even", 11, 10),
        ("even", 9, 8),
        ("odd", 10, 9),
        # 偶奇の制約が無い要素はmaxNativeZoomがそのまま上限。
        ("all", 11, 11),
        ("all", 10, 10),
    ],
)
def test_effective_max_zoom(zoom_use, max_native_zoom, expected):
    spec = JmaTileSpec("dummy", zoom_use, max_native_zoom)
    assert effective_max_zoom(spec) == expected


@pytest.mark.parametrize(
    ("element_id", "expected"),
    [
        # キキクル4種: maxNativeZoom=11 かつ even のため z10 が上限。
        ("land", 10),
        ("rain_mesh", 10),
        ("inund", 10),
        ("flood", 10),
        # 降水ナウキャスト: maxNativeZoom=10 かつ even のためそのまま。
        ("hrpns", 10),
        # 雷・竜巻: maxNativeZoom=9 かつ even のため z8 が上限（他より1段粗い）。
        ("thns", 8),
        ("trns", 8),
        ("sjfcstmap", 10),
    ],
)
def test_max_zoom_for_registered_elements(element_id, expected):
    assert max_zoom_for(element_id) == expected


def test_max_zoom_for_unknown_element_returns_none():
    assert max_zoom_for("no_such_element") is None


def test_every_registered_max_zoom_matches_its_zoom_use():
    """導出結果が必ず`zoom_use`の偶奇を満たすことの不変条件。"""
    for element_id, spec in JMA_TILE_SPECS.items():
        z = effective_max_zoom(spec)
        assert z <= spec.max_native_zoom, element_id
        if spec.zoom_use == "even":
            assert z % 2 == 0, element_id
        elif spec.zoom_use == "odd":
            assert z % 2 == 1, element_id
