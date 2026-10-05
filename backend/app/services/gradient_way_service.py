"""鍵→勾配（gradient_percent）配信層。

`gradient_percent`は道路の始点→終点方向を基準にした符号付き値で、道路自身の向きが要る。
そのため**鍵ごとに異なる値**を返す——タイル単位のスカラー1個へ縮められない。
"""

from dataclasses import dataclass

from app.domain.gradient import GRADIENT_VALUE_DECIMALS, LENS_PERPENDICULAR_BAND_DEG, GradientCalculator
from app.domain.material_catalog import GRADIENT_PERCENT
from app.domain.region import tile_bounds_lonlat
from app.infrastructure.cache_identity import cache_identity
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import log_external_call, mark_failed
from app.infrastructure.dynamic_way_value_cache import get_tile_values, set_tile_values
from app.infrastructure.road_graph_repository import (
    FEATURE_GRADIENT_INPUTS_SHAPE,
    ROAD_SURFACE_TILE_SHAPE,
    RoadGraphRepository,
)
from app.services.tile_version_service import served_tile_version

#: 勾配の値の作り方の署名。キャッシュの鍵に入り、変われば勾配のタイル値だけを作り直す。
#: 入力のSQL・落とす幅・丸めは機械で署名する。式（`domain/gradient.py: GradientCalculator.effective_gradient`）を
#: 変えたときは先頭のリビジョンを上げる——関数のソースは署名しない（docs/conventions/caching.md「無効化」）。
GRADIENT_VALUE_SHAPE = cache_identity(
    "1", FEATURE_GRADIENT_INPUTS_SHAPE, LENS_PERPENDICULAR_BAND_DEG, GRADIENT_VALUE_DECIMALS
)


@dataclass(frozen=True)
class GradientConditions:
    """勾配の値に要る条件。勾配は時刻にも速度にも依らない。"""

    bearing_deg: float


class GradientWayService:
    #: 返す生値の材料id。この材料を参照する軸の配信を担当し、キャッシュの名前空間にもなる。
    material_id = GRADIENT_PERCENT
    material_ids = (GRADIENT_PERCENT,)
    conditions_type = GradientConditions

    def __init__(self, repository: RoadGraphRepository):
        self._repository = repository

    @classmethod
    def build(cls, repository: RoadGraphRepository, weather_service: object, material_id: str) -> "GradientWayService":
        """登録テーブルから呼ぶための統一シグネチャ。勾配は天候を要らず、材料は1つだけ。"""
        return cls(repository=repository)

    async def get_way_values(self, z: int, x: int, y: int, conditions: GradientConditions) -> dict[str, float]:
        """指定タイル内のフィーチャーごとの実効勾配（正=登り・負=下り）を返す。

        取込範囲外・DB障害はいずれも空dictへ倒す。
        """
        bearing_deg = conditions.bearing_deg
        bbox = tile_bounds_lonlat(z, x, y)

        with log_external_call("region:gradient-way-values", z=z, x=x, y=y) as fields:
            # 路面タイルの世代は鍵の一部。渡し忘れると世代をまたいだ値を配る。
            surface_tile_version = await served_tile_version(self._repository, ROAD_SURFACE_TILE_SHAPE)
            cached = await get_tile_values(
                self.material_id, z, x, y, bearing_deg,
                surface_tile_version=surface_tile_version, value_shape=GRADIENT_VALUE_SHAPE,
            )
            if cached is not None:
                fields["cache"] = "hit"
                fields["value_count"] = len(cached)
                return cached
            fields["cache"] = "miss"

            try:
                inputs = await self._repository.get_feature_gradient_inputs_in_tile(z, x, y, bbox)
            except DB_UNAVAILABLE_ERRORS as exc:
                mark_failed(fields, exc)
                return {}
            if inputs is None:
                fields["postgis"] = "uncovered"
                return {}
            if not inputs:
                fields["postgis"] = "empty"
                return {}
            fields["feature_count"] = len(inputs)

            # 指定方位に対して直角に近い道路は`effective_gradient`がNoneを返す。そのまま
            # 0%として配ると、実際には急な坂の道が凡例の「平坦」の段へ入り区別できなくなる
            # ため、値を持たないフィーチャーとして落とす。
            effective = (
                (feature_key,
                 GradientCalculator.effective_gradient(gradient_percent, road_bearing_deg, bearing_deg))
                for feature_key, (gradient_percent, road_bearing_deg) in inputs.items()
            )
            values = {
                feature_key: round(value, GRADIENT_VALUE_DECIMALS)
                for feature_key, value in effective
                if value is not None
            }
            await set_tile_values(
                self.material_id, z, x, y, bearing_deg, values,
                surface_tile_version=surface_tile_version, value_shape=GRADIENT_VALUE_SHAPE,
            )
            fields["computed"] = len(values)
            return values
