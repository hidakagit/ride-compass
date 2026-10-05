"""`infrastructure/jma_tile_paths.py`——気象庁タイルの配信元のパスを読む。

入口は`read_jma_tile_path`（テンプレートどおりのパスをタイルとして読み戻す）と`is_final_absence`（404が確定した事実か）。
要素の宣言は`test_jma_tile_specs.py`と同じ架空の要素へ差し替える。

ここで見ないもの:
- テンプレートとパスの組み立て → `test_jma_tile_specs.py`
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain import jma_tile_specs as specs
from app.domain.jma_tile_specs import JmaFrame, JmaTile
from app.infrastructure import jma_tile_paths as paths
from tests.test_jma_tile_specs import ELEMENTS


@pytest.fixture
def _elements(monkeypatch):
    monkeypatch.setattr(specs, "JMA_ELEMENTS", ELEMENTS)


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
    assert paths.read_jma_tile_path(specs.jma_tile_path(tile)) == tile


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
    assert paths.read_jma_tile_path(path) is None


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
    assert paths.is_final_absence(path) is final
