"""`services/graph_service.py`——探索素材を読む入口が、読む前に断る条件。

ここで見ないもの:
- タイル単位のキャッシュの読み書き・結合 → `test_road_graph_engine.py`（探索の側から見る）
- 区間を数えるSQLそのもの → PostGISが要るため見ない（外接矩形の重なりを数えるだけ）
- 断られたときに利用者へ出す理由 → `test_route_generator.py`

リポジトリは代役で、各メソッドを`RoadGraphRepository`の同名メソッドの署名へ当ててから呼ぶ（`bound`）。
"""

import pytest

from app.domain.errors import SearchAreaTooLargeError
from app.domain.region import BoundingBox
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services import derived_data_revision_service
from app.services.graph_service import MAX_SEARCH_ROAD_EDGES, GraphService
from tests.bound_fake import bound

BBOX = BoundingBox(min_latitude=35.60, min_longitude=139.70, max_latitude=35.70, max_longitude=139.80)


def _repository_method(fake):
    return bound(getattr(RoadGraphRepository, fake.__name__), fake)


class FakeRepository:
    """取込範囲の中にあり、数えると`road_edges`本の区間があるリポジトリ。グラフを読みに来たら落ちる。"""

    def __init__(self, road_edges: int):
        self.road_edges = road_edges
        self.counted: list[BoundingBox] = []

    @_repository_method
    async def is_covered(self, bbox):
        return True

    @_repository_method
    async def count_edges_in_bbox(self, bbox):
        self.counted.append(bbox)
        return self.road_edges

    @_repository_method
    async def get_graph_topology_in_bbox(self, bbox):
        raise AssertionError("上限を超えた範囲のグラフを読みに来た")


@pytest.fixture(autouse=True)
def _skip_revision_check(monkeypatch):
    async def ensure_caches_match_db(repository, *, force=False):
        return None

    monkeypatch.setattr(derived_data_revision_service, "ensure_caches_match_db", ensure_caches_match_db)


async def test_search_area_over_the_limit_is_refused_before_reading_the_graph():
    repository = FakeRepository(road_edges=MAX_SEARCH_ROAD_EDGES + 1)

    with pytest.raises(SearchAreaTooLargeError) as raised:
        await GraphService(repository).get_search_materials_for_bbox(BBOX)

    assert (raised.value.road_edges, raised.value.limit) == (MAX_SEARCH_ROAD_EDGES + 1, MAX_SEARCH_ROAD_EDGES)
    # 読み込むのはbboxを覆うタイルの全体なので、数える範囲もbboxを含む。
    (counted,) = repository.counted
    assert counted.min_latitude <= BBOX.min_latitude and counted.max_latitude >= BBOX.max_latitude
    assert counted.min_longitude <= BBOX.min_longitude and counted.max_longitude >= BBOX.max_longitude
