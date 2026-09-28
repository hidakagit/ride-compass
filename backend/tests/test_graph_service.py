"""`services/graph_service.py`——探索範囲を道路網全体の配列から切り出す入口。

ここで見ないもの:
- 切り出しそのもの（どの区間が範囲に入るか） → `test_road_network.py`
- 切り出した範囲で経路を探す → `test_route_generation_behavior.py`
- 断られたときに利用者へ出す理由 → `test_route_generator.py`

リポジトリは代役で、各メソッドを`RoadGraphRepository`の同名メソッドの署名へ当ててから呼ぶ（`bound`）。
道路網全体の配列は`road_network_store.current`を、コンテナのメモリ上限はcgroupのファイルの置き場を差し替えて与える。
雨の観測の履歴は、アメダスの定期バッチの入口から作る（`tests/rain_history_fake.py`、Redisと気象庁への取得だけが代役）。
"""

import numpy as np
import pytest

from app.domain.axis_definitions import AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.domain.errors import SearchAreaTooLargeError
from app.domain.material_catalog import GRADIENT_PERCENT
from app.domain.rain import rain_window_material_id
from app.domain.region import BoundingBox
from app.infrastructure import container_memory, road_network_store
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.graph_service import GraphService
from tests import rain_history_fake
from tests.axis_system_fixture import replaced_axis_definitions
from tests.bound_fake import bound
from tests.test_road_network import network

#: `test_road_network.network()`の西側の2本の道（35.00N・139.00〜139.02E）を覆う。
BBOX = BoundingBox(min_latitude=34.99, min_longitude=138.99, max_latitude=35.01, max_longitude=139.03)

#: 道10（中点139.005E）の近くと、道20（中点139.015E）の近くの雨量計。
RAIN_GAUGES = {
    "west": {"lat": [35, 0.0], "lon": [138, 59.4], "kjName": "西"},
    "east": {"lat": [35, 0.0], "lon": [139, 1.8], "kjName": "東"},
}

RAIN_3H = rain_window_material_id(3)


def _published_axis(axis_id: str, terms: list[MaterialTerm]) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id, label="軸", default_weight=1.0, is_published=True,
        shape=BreakpointLinearShape(terms=terms, breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
    )


#: 雨の材料だけを読む軸と、雨と道の材料（勾配。`network()`では全区間1%）を足して読む軸。
RAIN_AXES = {
    "rain": _published_axis("rain", [MaterialTerm(material=RAIN_3H)]),
    "rain_and_grade": _published_axis("rain_and_grade", [MaterialTerm(material=RAIN_3H), MaterialTerm(material=GRADIENT_PERCENT)]),
}


def _repository_method(fake):
    return bound(getattr(RoadGraphRepository, fake.__name__), fake)


class FakeRepository:
    def __init__(self, covered: bool = True):
        self.covered = covered

    @_repository_method
    async def is_covered(self, bbox):
        return self.covered


@pytest.fixture
def road_network(monkeypatch):
    """取込範囲全体の道路網は`test_road_network.network()`。"""
    monkeypatch.setattr(road_network_store, "current", network)


@pytest.fixture
def empty_rain_history(monkeypatch):
    """雨の観測の履歴は空から始める。"""
    rain_history_fake.use_fake_redis(monkeypatch)


async def test_outside_the_ingested_area_there_is_no_search_range():
    assert await GraphService(FakeRepository(covered=False)).get_search_slice(BBOX) is None


async def test_the_range_is_cut_along_the_bbox_itself_and_scored_row_by_row(road_network, empty_rain_history):
    """切り出しはbboxそのもの——同じz12タイル（138.955〜139.043E）の中でも、bboxの外の道20は取らない。
    タイル集合は迂回率の鍵としてz12で返る。"""
    narrow = BoundingBox(min_latitude=34.99, min_longitude=138.99, max_latitude=35.01, max_longitude=139.005)
    road, matrix, tile_set = await GraphService(FakeRepository()).get_search_slice(narrow)

    assert road.rows.tolist() == [0, 1]
    assert len(matrix.distance_m) == road.edge_count
    assert tile_set and all(zoom == 12 for zoom, _x, _y in tile_set)


def _memory_limit(monkeypatch, tmp_path, content):
    """コンテナのメモリ上限（cgroupの`memory.max`）。Noneならファイルが無い環境（開発機）。"""
    path = tmp_path / "memory.max"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(container_memory, "CGROUP_MEMORY_MAX", path)


async def test_a_range_too_large_for_the_memory_limit_is_refused(monkeypatch, tmp_path, road_network):
    """取り置きぶんしか無いメモリ上限では、どの範囲も組めない。"""
    _memory_limit(monkeypatch, tmp_path, str(2 * 1024**3))

    with pytest.raises(SearchAreaTooLargeError) as raised:
        await GraphService(FakeRepository()).get_search_slice(BBOX)

    assert (raised.value.edges, raised.value.limit) == (3, 0)


async def test_the_limit_grows_with_the_memory_limit(monkeypatch, tmp_path, road_network, empty_rain_history):
    """メモリを増やせば、上限の数字を直さなくても同じ範囲が通るようになる。"""
    _memory_limit(monkeypatch, tmp_path, str(2 * 1024**3 + 1))
    with pytest.raises(SearchAreaTooLargeError):
        await GraphService(FakeRepository()).get_search_slice(BBOX)

    _memory_limit(monkeypatch, tmp_path, str(8 * 1024**3))
    road, _matrix, _tiles = await GraphService(FakeRepository()).get_search_slice(BBOX)

    assert road.edge_count == 3


@pytest.mark.parametrize("content", ["max\n", None], ids=["上限なし", "cgroupの外"])
async def test_without_a_memory_limit_no_range_is_refused(monkeypatch, tmp_path, content, road_network, empty_rain_history):
    _memory_limit(monkeypatch, tmp_path, content)

    road, _matrix, _tiles = await GraphService(FakeRepository()).get_search_slice(BBOX)

    assert road.edge_count == 3


def _axis_column(matrix, axis_id: str) -> list[float]:
    return matrix.axis_scores[:, matrix.axis_ids.index(axis_id)].tolist()


async def test_each_edge_reads_the_rain_observed_at_the_gauge_nearest_its_midpoint(monkeypatch, road_network, empty_rain_history):
    """雨の材料は区間の中点に最も近い雨量計の今の観測で、道の材料と同じ列として軸の得点・生値に載る
    ——雨と道の材料を1つの軸で足すこともできる。"""
    await rain_history_fake.observe(monkeypatch, RAIN_GAUGES, {"west": 1.0, "east": 0.0})

    with replaced_axis_definitions(RAIN_AXES):
        road, matrix, _tiles = await GraphService(FakeRepository()).get_search_slice(BBOX)

    # 行は道10の往復（西の雨量計）と道20（東の雨量計）。3時間の雨量は1時間1.0mmの3本ぶん。
    assert road.rows.tolist() == [0, 1, 2]
    assert _axis_column(matrix, "rain") == [30.0, 30.0, 0.0]
    assert _axis_column(matrix, "rain_and_grade") == [40.0, 40.0, 10.0]
    assert matrix.axis_raw_values[:, matrix.raw_axis_ids.index("rain")].tolist() == [3.0, 3.0, 0.0]


async def test_without_an_observation_history_the_rain_axis_has_no_data_but_the_range_is_built(road_network, empty_rain_history):
    """履歴が無い（バッチがまだ・Redisが不通）ときは、雨を読む軸だけが「データなし」になる。"""
    with replaced_axis_definitions(RAIN_AXES):
        road, matrix, _tiles = await GraphService(FakeRepository()).get_search_slice(BBOX)

    assert road.edge_count == 3
    assert np.isnan(_axis_column(matrix, "rain")).all()
