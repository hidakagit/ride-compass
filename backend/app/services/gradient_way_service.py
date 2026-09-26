"""鍵→勾配（gradient_percent）配信層。

`gradient_percent`は道路の始点→終点方向を基準にした符号付き値で、道路自身の向きが要る。
そのため**鍵ごとに異なる値**を返す——タイル単位のスカラー1個へ縮められない。

勾配は時刻に依存しないため、キャッシュキーの時刻バケットは常にNoneで扱う。
"""

import logging
from datetime import datetime

from app.domain.gradient import GradientCalculator
from app.domain.region import tile_bounds_lonlat
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.dynamic_way_value_cache import get_tile_values, set_tile_values
from app.services import derived_data_revision_service
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.gradient_way")

# 勾配の入力は道路の向きと標高で決まりほぼ不変のため、鮮度の制約が無い。長く持って
# DBへの再問い合わせを抑える。正本を持たないキャッシュで、期限切れ後は再計算されるだけ。
GRADIENT_TILE_VALUES_TTL_SECONDS = 24 * 3600


class GradientWayService:
    #: 返す生値の材料id。この材料を参照する軸の配信を担当し、キャッシュの名前空間にもなる。
    material_id = "gradient_percent"

    def __init__(self, repository: RoadGraphRepository):
        self._repository = repository

    @classmethod
    def build(cls, repository: RoadGraphRepository, weather_service: object) -> "GradientWayService":
        """登録テーブルから呼ぶための統一シグネチャ。勾配は天候を要らない。"""
        return cls(repository=repository)

    async def get_way_values(
        self, z: int, x: int, y: int, at: datetime | None, bearing_deg: float | None, speed_kmh: float | None = None
    ) -> dict[str, float]:
        """指定タイル内のフィーチャーごとの実効勾配（正=登り・負=下り）を返す。

        取込範囲外・DB障害はいずれも空dictへ倒す。

        `at`・`speed_kmh`は材料非依存な呼び出し口と形を揃えるためだけに受け取り、勾配の
        計算には使わない。`bearing_deg`も同じ理由で`float | None`だが、勾配はこれが無いと
        計算できないため、Noneのまま到達したら即座に失敗させる（無音で進めない）。
        """
        if bearing_deg is None:
            raise ValueError("GradientWayService.get_way_valuesにはbearing_degが必須です")
        bbox = tile_bounds_lonlat(z, x, y)

        with log_external_call("region:gradient-way-values", z=z, x=x, y=y) as fields:
            # 世代は鍵の一部。渡し忘れると世代をまたいだ値を配る。
            revision = derived_data_revision_service.current_revision()
            cached = await get_tile_values(self.material_id, z, x, y, None, bearing_deg, revision=revision)
            if cached is not None:
                fields["cache_hit"] = len(cached)
                fields["cache_status"] = "hit"
                return cached
            fields["cache_status"] = "miss"

            try:
                inputs = await self._repository.get_feature_gradient_inputs_in_tile(z, x, y, bbox)
            except DB_UNAVAILABLE_ERRORS as exc:
                fields["result"] = "error"
                fields["warned"] = True
                logger.warning("勾配の評価軸配信のway入力取得に失敗 z=%d x=%d y=%d error=%r", z, x, y, exc)
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
                feature_key: round(value, 1)
                for feature_key, value in effective
                if value is not None
            }
            await set_tile_values(
                self.material_id, z, x, y, None, bearing_deg, values, GRADIENT_TILE_VALUES_TTL_SECONDS,
                revision=revision,
            )
            fields["computed"] = len(values)
            return values
