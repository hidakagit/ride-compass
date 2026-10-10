"""地図の配信が評価する、タイル1枚ぶんのフィーチャーごとの材料を読む（路面タイルの世代ごとにディスクへ持つ）。"""

from app.domain.dynamic_way_values import FeatureMaterials
from app.domain.region import tile_bounds_lonlat
from app.infrastructure.cache_identity import cache_identity, is_known_tile_version
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.feature_material_cache import get_tile_materials, set_tile_materials
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.road_tile_sql import FEATURE_MATERIALS_SHAPE, ROAD_SURFACE_TILE_SHAPE
from app.services.feature_midpoints import tile_features
from app.services.tile_version_service import served_tile_version

#: 材料の値の読み方の署名。キャッシュの鍵に入り、読み出しのSQLか持つ列の組を変えれば作り直す。
FEATURE_MATERIALS_VALUE_SHAPE = cache_identity("1", FEATURE_MATERIALS_SHAPE, FeatureMaterials)


class FeatureMaterialService:
    def __init__(self, repository: RoadGraphRepository):
        self._repository = repository

    async def materials(self, z: int, x: int, y: int) -> FeatureMaterials | None:
        """タイル内のフィーチャーごとの材料。取込範囲外・DB障害・フィーチャーの無いタイルはNone。"""
        with log_external_call("region:feature-materials", z=z, x=x, y=y) as fields:
            # 路面タイルの世代は鍵の一部。渡し忘れると世代をまたいだ鍵の材料を配る。
            surface_tile_version = await served_tile_version(self._repository, ROAD_SURFACE_TILE_SHAPE)
            cached = await get_tile_materials(
                z, x, y, surface_tile_version=surface_tile_version, value_shape=FEATURE_MATERIALS_VALUE_SHAPE
            )
            if cached is not None:
                fields["cache"] = "hit"
                fields["feature_count"] = len(cached)
                return cached
            fields["cache"] = "miss"
            materials = await tile_features(self._read(z, x, y), fields)
            if materials is not None and is_known_tile_version(surface_tile_version):
                await set_tile_materials(
                    z, x, y, materials,
                    surface_tile_version=surface_tile_version, value_shape=FEATURE_MATERIALS_VALUE_SHAPE,
                )
            return materials

    async def _read(self, z: int, x: int, y: int) -> FeatureMaterials | None:
        accident_years = await self._repository.get_accident_years_covered()
        return await self._repository.get_feature_materials_in_tile(z, x, y, tile_bounds_lonlat(z, x, y), accident_years)
