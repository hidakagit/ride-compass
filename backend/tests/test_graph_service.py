"""`services/graph_service.py`——探索範囲を道路網全体の配列から切り出す入口。

ここで見ないもの:
- 切り出しそのもの（どの区間が範囲に入るか） → `test_road_network.py`
- 切り出した範囲で経路を探す → `test_route_generation_behavior.py`
- 断られたときに利用者へ出す理由 → `test_route_generator.py`

リポジトリは代役で、各メソッドを`RoadGraphRepository`の同名メソッドの署名へ当ててから呼ぶ（`bound`）。
道路網全体の配列は`road_network_store.current`を差し替えて与える。
"""

import pytest

from app.domain.errors import SearchAreaTooLargeError
from app.domain.region import BoundingBox
from app.infrastructure import road_network_store
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services import graph_service
from app.services.graph_service import GraphService
from tests.bound_fake import bound
from tests.test_road_network import network

#: `test_road_network.network()`の西側の2本の道（35.00N・139.00〜139.02E）を覆う。
BBOX = BoundingBox(min_latitude=34.99, min_longitude=138.99, max_latitude=35.01, max_longitude=139.03)


def _repository_method(fake):
    return bound(getattr(RoadGraphRepository, fake.__name__), fake)


class FakeRepository:
    def __init__(self, covered: bool = True):
        self.covered = covered

    @_repository_method
    async def is_covered(self, bbox):
        return self.covered


@pytest.fixture(autouse=True)
def _network(monkeypatch):
    monkeypatch.setattr(road_network_store, "current", network)


async def test_outside_the_ingested_area_there_is_no_search_range():
    assert await GraphService(FakeRepository(covered=False)).get_search_slice(BBOX) is None


async def test_the_range_is_cut_along_the_tiles_covering_the_bbox_and_scored_row_by_row():
    """切り出しはbboxではなくそれを覆うz12タイルの外接矩形——同じタイル集合なら同じ範囲になる。"""
    road, matrix, tile_set = await GraphService(FakeRepository()).get_search_slice(BBOX)

    assert road.rows.tolist() == [0, 1, 2]
    assert len(matrix.distance_m) == road.edge_count
    assert tile_set and all(zoom == 12 for zoom, _x, _y in tile_set)


async def test_a_range_over_the_limit_is_refused_before_it_is_scored(monkeypatch):
    monkeypatch.setattr(graph_service, "MAX_SEARCH_EDGES", 2)

    def score_must_not_run(materials):
        raise AssertionError("上限を超えた範囲のスコア行列を作りに来た")

    monkeypatch.setattr(graph_service, "build_static_edge_score_matrix", score_must_not_run)

    with pytest.raises(SearchAreaTooLargeError) as raised:
        await GraphService(FakeRepository()).get_search_slice(BBOX)

    assert (raised.value.edges, raised.value.limit) == (3, 2)
