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


def test_max_zoom_for_unknown_element_returns_none():
    assert max_zoom_for("no_such_element") is None


def test_every_registered_max_zoom_matches_its_zoom_use():
    """登録済みのどの要素も、上限ズームが`zoom_use`の偶奇を満たし配信元の上限を超えない。"""
    for element_id, spec in JMA_TILE_SPECS.items():
        z = max_zoom_for(element_id)
        assert z is not None, element_id
        assert z <= spec.max_native_zoom, element_id
        if spec.zoom_use == "even":
            assert z % 2 == 0, element_id
        elif spec.zoom_use == "odd":
            assert z % 2 == 1, element_id
