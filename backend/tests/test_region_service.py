
import pytest

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition
from app.domain.route_preference import RoutePreference
from app.infrastructure import tile_cache
from app.infrastructure.vector_tile import encode_empty_poi_tile, encode_empty_road_surface_tile
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.region_service import RegionService
from tests.axis_system_fixture import axis_definition


@pytest.fixture(autouse=True)
def use_temp_tile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
    yield


Z, X, Y = 14, 14551, 6447


class _TileRepository:
    """路面・POIのMVTを焼く口だけを持つフェイク。取込範囲外はNone、DB障害は例外。"""

    def __init__(self, tile: bytes | None = None, error: Exception | None = None):
        self._tile = tile
        self._error = error

    async def _answer(self):
        if self._error is not None:
            raise self._error
        return self._tile

    async def get_road_surface_tile_mvt(self, z, x, y, bbox):
        return await self._answer()

    async def get_poi_tile_mvt(self, z, x, y, bbox):
        return await self._answer()


TILE_KINDS = [
    ("get_road_surface_tile", encode_empty_road_surface_tile()),
    ("get_poi_tile", encode_empty_poi_tile()),
]


@pytest.mark.parametrize(("method", "empty_tile"), TILE_KINDS)
async def test_uncovered_tile_is_empty_and_browsers_may_keep_it(method, empty_tile):
    service = RegionService(repository=_TileRepository(tile=None))

    tile = await getattr(service, method)(Z, X, Y)

    assert (tile.content, tile.cacheable) == (empty_tile, True)


@pytest.mark.parametrize(("method", "empty_tile"), TILE_KINDS)
async def test_db_error_tile_is_empty_and_browsers_must_not_keep_it(method, empty_tile):
    # 一時的な失敗の空タイルをブラウザが持つと、回復した後もその区画の空白が残る。
    service = RegionService(repository=_TileRepository(error=ConnectionRefusedError("db down")))

    tile = await getattr(service, method)(Z, X, Y)

    assert (tile.content, tile.cacheable) == (empty_tile, False)


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
        dynamic_way_value_needs_bearing=True,
    )
    monkeypatch.setitem(AXIS_DEFINITIONS, axis.axis_id, axis)
    return axis


def _inspected_axis(result, axis_id: str):
    return next(axis for axis in result.axes if axis.axis_id == axis_id)


async def test_axis_inspector_direction_dependent_axis_is_unavailable_without_dynamic_materials(direction_dependent_axis):
    # 1本の道は往復2方向で値が違うため、DBのway単位の材料だけでは求まらない
    axis = direction_dependent_axis
    service = RegionService(repository=_FakeWayRepository())

    result = await service.get_axis_inspector(12345)

    assert _inspected_axis(result, axis.axis_id).available is False


async def test_axis_inspector_uses_the_direction_dependent_materials_it_is_given(direction_dependent_axis):
    axis = direction_dependent_axis
    service = RegionService(repository=_FakeWayRepository())

    result = await service.get_axis_inspector(
        12345, dynamic_materials={material: 3.0 for material in axis.materials}
    )

    assert _inspected_axis(result, axis.axis_id).available is True


# --- 材料の実データ値一覧 ---


class _MaterialValuesRepository:
    """材料の値一覧だけを答えるフェイク。"""

    def __init__(self, error: Exception):
        self._error = error

    async def get_distinct_material_values(self, material_id):
        raise self._error


async def test_material_values_the_db_could_not_read_are_unavailable_not_empty():
    # 「候補が無い」と「候補を出せなかった」を区別する。両方を空リストへ倒すと、
    # DBのタイムアウトが「この材料には値が無い」として静かに表示される。
    service = RegionService(repository=_MaterialValuesRepository(ConnectionRefusedError("db down")))

    assert await service.get_material_values("highway") is None


# --- 事故データ収録年数 ---


class _AccidentYearsRepository:
    """収録年だけを答えるフェイク（`get_accident_years`の戻りを差し替える）。"""

    def __init__(self, years=None, error: Exception | None = None):
        self._years = years or []
        self._error = error

    async def get_accident_years(self):
        if self._error is not None:
            raise self._error
        return self._years


async def test_accident_years_come_from_the_import_profile():
    """年そのものを配る。表示側が年を文字列で持たないための口。"""
    service = RegionService(repository=_AccidentYearsRepository([2023, 2024]))

    assert await service.get_accident_years() == [2023, 2024]
    # 年数は年の数から導く（同じ値を二重に持たない）。
    assert await service.get_accident_years_covered() == 2


async def test_accident_years_fall_back_to_empty_on_db_error():
    service = RegionService(repository=_AccidentYearsRepository(error=ConnectionRefusedError("db down")))

    assert await service.get_accident_years() == []
    assert await service.get_accident_years_covered() == 0




async def test_axis_inspector_combines_with_the_weights_it_is_given(direction_dependent_axis):
    """重みを0にした軸は、値があっても合成に効かない（利用者の重みで見せる）。"""
    axis = direction_dependent_axis
    service = RegionService(repository=_FakeWayRepository())
    materials = {material: 3.0 for material in axis.materials}

    weighted = await service.get_axis_inspector(
        12345, dynamic_materials=materials, preference=RoutePreference(weights={axis.axis_id: 1.0})
    )
    ignored = await service.get_axis_inspector(
        12345, dynamic_materials=materials, preference=RoutePreference(weights={axis.axis_id: 0.0})
    )

    assert _inspected_axis(weighted, axis.axis_id).weight == 1.0
    assert _inspected_axis(weighted, axis.axis_id).contribution not in (None, 0)
    assert _inspected_axis(ignored, axis.axis_id).weight == 0.0
    assert not _inspected_axis(ignored, axis.axis_id).contribution
