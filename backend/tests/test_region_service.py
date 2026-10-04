
import pytest

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition
from app.domain.route_preference import RoutePreference
from app.infrastructure.derived_data_meta import DataRevisions
from app.infrastructure.point_tile_layers import POINT_TILE_LAYERS
from app.infrastructure.vector_tile import ROAD_SURFACE_LAYER_NAME, encode_empty_tile
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.region_service import RegionService
from tests.axis_system_fixture import axis_definition


Z, X, Y = 14, 14551, 6447


class _TileRepository:
    """路面・点のMVTを焼く口とデータの世代だけを持つフェイク。取込範囲外はNone、DB障害は例外。"""

    def __init__(self, tile: bytes | None = None, error: Exception | None = None):
        self.tile = tile
        self.error = error

    async def get_data_revisions(self):
        return DataRevisions(derived=1, imported=1)

    async def _answer(self):
        if self.error is not None:
            raise self.error
        return self.tile

    async def get_road_surface_tile_mvt(self, z, x, y, bbox):
        return await self._answer()

    async def get_tile_mvt(self, sql, layer_name, z, x, y, bbox):
        return await self._answer()


def _road_surface_tile(service):
    return service.get_road_surface_tile(Z, X, Y)


def _point_tile(layer):
    return lambda service: service.get_point_tile(layer, Z, X, Y)


# 路面と、宣言された点のレイヤー全部。空タイルはそれぞれのsource-layerを名乗る。
TILE_KINDS = [
    pytest.param(_road_surface_tile, encode_empty_tile(ROAD_SURFACE_LAYER_NAME), id="road_surface"),
    *(pytest.param(_point_tile(layer), encode_empty_tile(layer.source_layer), id=name)
      for name, layer in POINT_TILE_LAYERS.items()),
]


@pytest.mark.parametrize(("serve", "empty_tile"), TILE_KINDS)
async def test_uncovered_tile_is_empty_and_browsers_may_keep_it(serve, empty_tile):
    service = RegionService(repository=_TileRepository(tile=None))

    tile = await serve(service)

    assert (tile.content, tile.cacheable) == (empty_tile, True)


@pytest.mark.parametrize(("serve", "empty_tile"), TILE_KINDS)
async def test_db_error_tile_is_empty_and_browsers_must_not_keep_it(serve, empty_tile):
    # 一時的な失敗の空タイルをブラウザが持つと、回復した後もその区画の空白が残る。
    service = RegionService(repository=_TileRepository(error=ConnectionRefusedError("db down")))

    tile = await serve(service)

    assert (tile.content, tile.cacheable) == (empty_tile, False)


@pytest.mark.parametrize(("serve", "empty_tile"), TILE_KINDS)
async def test_tile_is_kept_on_disk_without_anyone_fetching_the_catalog_first(serve, empty_tile):
    """世代はタイルを配る経路が自分で読む。起動後に誰もカタログを取っていなくても、焼いたタイルは
    世代付きの鍵でディスクへ残り、同じタイルの2回目はDBが答えなくても焼いたタイルを配る。"""
    repository = _TileRepository(tile=b"tile")
    service = RegionService(repository=repository)
    await serve(service)

    repository.error = ConnectionRefusedError("db down")
    tile = await serve(service)

    assert tile.content == b"tile"


# --- 区間インスペクタ ---


class _FakeWayRepository(RoadGraphRepository):
    """way1本ぶんの読み出しだけに答えるなりすまし（実セッションを持たない）。"""

    def __init__(self, materials: dict[str, float] | None = None):
        self._materials = materials or {}

    async def get_way_tags_by_osm_way_id(self, osm_way_id):
        return ("primary", {}, None)

    async def get_accident_years_covered(self):
        return 1

    async def get_way_material_values(self, osm_way_id, accident_years_covered):
        return dict(self._materials)

    async def get_feature_landcover(self, osm_way_id, feature_key):
        return None


@pytest.fixture
def direction_dependent_axis(monkeypatch) -> AxisDefinition:
    """向きが決まらないと値の出ない軸（専用way値配信で方位を要る）を1本だけ置く。"""
    axis = axis_definition(
        "axis_needs_bearing",
        material="wind_drag_ratio",
        is_published=True,
        dedicated_way_value_layer=True,
    )
    monkeypatch.setitem(AXIS_DEFINITIONS, axis.axis_id, axis)
    return axis


def _inspected_axis(result, axis_id: str):
    return next(axis for axis in result.axes if axis.axis_id == axis_id)


async def test_axis_inspector_direction_dependent_axis_is_unavailable_without_dynamic_materials(direction_dependent_axis):
    # 1本の道は往復2方向で値が違うため、DBのway単位の材料だけでは求まらない
    axis = direction_dependent_axis
    service = RegionService(repository=_FakeWayRepository())

    result = await service.get_axis_inspector(12345, None, None, None)

    assert _inspected_axis(result, axis.axis_id).difficulty is None


async def test_axis_inspector_uses_the_direction_dependent_materials_it_is_given(direction_dependent_axis):
    axis = direction_dependent_axis
    service = RegionService(repository=_FakeWayRepository())

    result = await service.get_axis_inspector(
        12345, None, {material: 3.0 for material in axis.materials}, None
    )

    assert _inspected_axis(result, axis.axis_id).difficulty is not None


# --- 事故データ収録年数 ---


class _UnreadableAccidentYearsRepository:
    """収録年を読めないDBの代役。"""

    async def get_accident_years(self):
        raise ConnectionRefusedError("db down")


async def test_accident_years_fall_back_to_empty_on_db_error():
    service = RegionService(repository=_UnreadableAccidentYearsRepository())

    assert await service.get_accident_years() == []




async def test_axis_inspector_combines_with_the_weights_it_is_given(direction_dependent_axis):
    """重みを0にした軸は、値があっても合成に効かない（利用者の重みで見せる）。"""
    axis = direction_dependent_axis
    service = RegionService(repository=_FakeWayRepository())
    materials = {material: 3.0 for material in axis.materials}

    weighted = await service.get_axis_inspector(
        12345, None, materials, RoutePreference(weights={axis.axis_id: 1.0})
    )
    ignored = await service.get_axis_inspector(
        12345, None, materials, RoutePreference(weights={axis.axis_id: 0.0})
    )

    assert _inspected_axis(weighted, axis.axis_id).weight == 1.0
    assert _inspected_axis(weighted, axis.axis_id).contribution not in (None, 0)
    assert _inspected_axis(ignored, axis.axis_id).weight == 0.0
    assert not _inspected_axis(ignored, axis.axis_id).contribution
