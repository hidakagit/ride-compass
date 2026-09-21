
import pytest

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition
from app.domain.dynamic_way_values import dedicated_way_value_axes
from app.domain.material_catalog import is_known_material
from app.infrastructure import tile_cache
from app.services import derived_data_revision_service
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.region_service import RegionService

# 改善計画T350: 本番相当の14軸（実軸id前提のロジック用）はtests/conftest.pyのセッション
# スコープautouseフィクスチャが全テスト共通で用意する（tests/realistic_axis_fixtures.py参照）。


@pytest.fixture(autouse=True)
def use_temp_tile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
    yield


@pytest.fixture(autouse=True)
def known_derived_data_revision(monkeypatch):
    """世代が読めている状態を既定にする。

    読めていないあいだタイルはディスクへ残さない（改善計画T929、
    `services/tile_serving.py: serve_cached_tile`の`persist`）ため、キャッシュの挙動を
    見るテストはこの前提を明示する必要がある。
    """
    monkeypatch.setattr(derived_data_revision_service, "current_revision", lambda: 1)
    yield


Z, X, Y = 14, 14551, 6447


async def test_no_repository_returns_empty_mvt():
    # road_graph_use_repository無効（DBなし構成）ではrepository自体が注入されず、
    # 路面レイヤーは常に空タイルになる
    service = RegionService()

    tile_bytes = (await service.get_road_surface_tile(Z, X, Y)).content

    assert isinstance(tile_bytes, bytes)


# 改善計画T54: 停止要因POI・交差点密度レイヤー。get_road_surface_tileと同じ_get_tile経由の
# 契約（カバレッジ判定・キャッシュ・エラー処理）を共有するため、代表的なケースのみ確認する
# （全パターンの再検証はget_road_surface_tile側のテストで既に担保済み）。


async def test_poi_tile_no_repository_returns_empty_mvt():
    service = RegionService()

    tile_bytes = (await service.get_poi_tile(Z, X, Y)).content

    assert isinstance(tile_bytes, bytes)


# 改善計画T59: ルート生成した地点でしか道路グラフ（road_nodes/road_edges）が構築されず、
# 地図を眺めるだけの利用（ルート生成を経ない）では道路情報・車ストレス・自転車インフラ・
# 交差点密度レイヤーが永遠に空のままだった問題への対応。カバレッジ内タイルの応答時、
# z12祖先タイル単位でバックグラウンド構築を起動する（_maybe_trigger_graph_build）。


class _FakeRealRoadGraphRepository(RoadGraphRepository):
    """isinstance(repository, RoadGraphRepository)による発火判定をテストするための
    なりすまし。実DBセッションは使わない（__init__をオーバーライドしてsuper().__init__を
    呼ばない。tile_query.get_road_surface_tile_mvt等への委譲も直接オーバーライドで避ける）。"""

    def __init__(self, tile: bytes = b"fake-mvt-tile"):
        self._tile = tile

    async def get_road_surface_tile_mvt(self, z, x, y, bbox, coverage_tile):
        return self._tile

    async def get_poi_tile_mvt(self, z, x, y, bbox, coverage_tile):
        return self._tile


# --- 区間インスペクタ（改善計画T146） ---


async def test_axis_inspector_no_repository_returns_none():
    service = RegionService()

    assert await service.get_axis_inspector(12345) is None


class _FakeWayRepository(RoadGraphRepository):
    """way1本ぶんの読み出しだけに答えるなりすまし（_FakeRealRoadGraphRepositoryと同じく
    実セッションを持たない）。"""

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


def _direction_dependent_axis() -> AxisDefinition:
    """向きが決まらないと値の出ない軸を1本選ぶ。

    軸idを名指ししない——`dedicated_way_value_axes()`の宣言から引く。他の軸を参照する
    合成軸は、材料を差し込んでも被参照側の欠損で落ちるため除く。
    """
    return next(
        AXIS_DEFINITIONS[axis_id]
        for axis_id, axis in dedicated_way_value_axes().items()
        if axis.needs_bearing
        and all(is_known_material(m) for m in AXIS_DEFINITIONS[axis_id].materials)
    )


def _inspected_axis(result, axis_id: str):
    return next(axis for axis in result.axes if axis.axis_id == axis_id)


async def test_axis_inspector_direction_dependent_axis_is_unavailable_without_dynamic_materials():
    # 1本の道は往復2方向で値が違うため、DBのway単位の材料だけでは求まらない
    axis = _direction_dependent_axis()
    service = RegionService(repository=_FakeWayRepository())

    result = await service.get_axis_inspector(12345)

    assert _inspected_axis(result, axis.axis_id).available is False


async def test_axis_inspector_uses_the_direction_dependent_materials_it_is_given():
    axis = _direction_dependent_axis()
    service = RegionService(repository=_FakeWayRepository())

    result = await service.get_axis_inspector(
        12345, dynamic_materials={material: 3.0 for material in axis.materials}
    )

    assert _inspected_axis(result, axis.axis_id).available is True


# --- 材料の実データ値一覧（改善計画T340） ---


async def test_material_values_without_a_repository_are_unavailable_not_empty():
    # 「候補が無い」と「候補を出せなかった」を区別する。両方を空リストへ倒すと、
    # DBのタイムアウトが「この材料には値が無い」として静かに表示される。
    service = RegionService()

    assert await service.get_material_values("highway") is None


# --- 事故データ収録年数（改善計画T404、GET /api/axis-catalogのmaterial_runtime_scales用） ---


async def test_accident_years_covered_no_repository_returns_zero():
    service = RegionService()

    assert await service.get_accident_years_covered() == 0


async def test_no_repository_stays_cacheable():
    # repository未接続は設定由来で、プロセスが生きている間は変わらない。
    service = RegionService(repository=None)

    tile = await service.get_road_surface_tile(Z, X, Y)

    assert tile.cacheable is True

