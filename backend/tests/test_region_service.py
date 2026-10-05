"""`services/region_service.py`——地域のレイヤー（路面・点のタイル）の配信と、区間インスペクタ・事故の収録年。

確かめるのは、焼けなかったタイル（範囲外・DB障害）の空タイルとブラウザに持たせてよいか、焼いたタイルを世代付きの鍵で
ディスクへ残すか、区間インスペクタが渡された向きの材料と重みで合成すること、DB障害の倒し方。差し替えるのはDBの口だけ。

ここで見ないもの:
- キャッシュの読み書きの骨格 → `test_region_tile_cache.py`
- 世代の文字列の組み立て → `test_cache_identity.py`。世代をTTLで読み直すこと → `test_derived_data_revision_service.py`
- 焼き込むSQLが出す点 → `test_point_tiles.py`
- HTTPの受け渡し → `test_region_routes.py`
"""

import pytest

from app.config import settings
from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition
from app.domain.route_preference import RoutePreference
from app.infrastructure.derived_data_meta import DataRevisions
from app.infrastructure.point_tile_layers import POINT_TILE_LAYERS
from app.infrastructure.vector_tile import ROAD_SURFACE_LAYER_NAME, encode_empty_tile
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.region_service import RegionService
from tests.axis_system_fixture import axis_definition


Z, X, Y = 14, 14551, 6447
POINT_LAYER = next(iter(POINT_TILE_LAYERS.values()))


class _TileRepository:
    """路面・点のMVTを焼く口とデータの世代だけを持つフェイク。取込範囲外はNone、DB障害は例外。"""

    def __init__(self, tile: bytes | None = None, error: Exception | None = None, derived: int | None = 1):
        self.tile = tile
        self.error = error
        self.derived = derived

    async def get_data_revisions(self):
        return DataRevisions(derived=self.derived, imported=1)

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


def _point_tile(service):
    return service.get_point_tile(POINT_LAYER, Z, X, Y)


@pytest.mark.parametrize(("serve", "error", "empty_tile", "cacheable"), [
    (_road_surface_tile, None, encode_empty_tile(ROAD_SURFACE_LAYER_NAME), True),
    # 一時的な失敗の空タイルをブラウザが持つと、回復した後もその区画の空白が残る。
    (_road_surface_tile, ConnectionRefusedError("db down"), encode_empty_tile(ROAD_SURFACE_LAYER_NAME), False),
    # 点のレイヤーも同じ道で配る。空タイルは自分のsource-layerを名乗る。
    (_point_tile, None, encode_empty_tile(POINT_LAYER.source_layer), True),
], ids=["範囲外", "DB障害", "点のレイヤー"])
async def test_a_tile_that_cannot_be_made_is_empty_and_browsers_may_keep_only_an_uncovered_one(
        serve, error, empty_tile, cacheable):
    service = RegionService(repository=_TileRepository(tile=None, error=error))

    tile = await serve(service)

    assert (tile.content, tile.cacheable) == (empty_tile, cacheable)


@pytest.mark.parametrize(("before", "after", "kept"), [
    (1, 1, True),
    (1, 2, False),
    (None, None, False),
], ids=["同じ世代", "派生を作り直した", "世代が分からない"])
async def test_a_baked_tile_is_served_from_disk_only_while_its_generation_is_known_and_unchanged(
        monkeypatch, before, after, kept):
    """世代はタイルを配る経路が自分で読む。起動後に誰もカタログを取っていなくても、焼いたタイルは世代付きの鍵で
    ディスクへ残り、世代が変わると焼き直す。世代が分からないうちに焼いたタイルは残さない——後で世代が分かっても
    古いと判定できない。"""
    monkeypatch.setattr(settings, "derived_data_revision_check_interval_seconds", 0.0)
    repository = _TileRepository(tile=b"first", derived=before)
    service = RegionService(repository=repository)
    await _road_surface_tile(service)

    repository.tile, repository.derived = b"second", after
    tile = await _road_surface_tile(service)

    assert tile.content == (b"first" if kept else b"second")


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


@pytest.mark.parametrize("given", [False, True], ids=["向きの材料なし", "向きの材料あり"])
async def test_axis_inspector_values_a_direction_dependent_axis_only_with_the_materials_it_is_given(
        direction_dependent_axis, given):
    # 1本の道は往復2方向で値が違うため、DBのway単位の材料だけでは求まらない
    axis = direction_dependent_axis
    service = RegionService(repository=_FakeWayRepository())
    dynamic_materials = {material: 3.0 for material in axis.materials} if given else None

    result = await service.get_axis_inspector(12345, None, dynamic_materials, None)

    assert (_inspected_axis(result, axis.axis_id).difficulty is not None) is given


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


# --- 事故データ収録年数 ---


class _UnreadableAccidentYearsRepository:
    """収録年を読めないDBの代役。"""

    async def get_accident_years(self):
        raise ConnectionRefusedError("db down")


async def test_accident_years_fall_back_to_empty_on_db_error():
    service = RegionService(repository=_UnreadableAccidentYearsRepository())

    assert await service.get_accident_years() == []
