"""way_id→勾配（gradient_percent）配信層。wind_way_service.pyと同型の役割——「評価軸」
グループとしての勾配（ルート未確定時、視界内の全道路へユーザー指定の向きを一律適用する
線表示）の基盤。「環境」グループの勾配（gridFill面表示）とも同じ入力（ユーザー指定の
向き）を共有する。

風とは異なり、gradient_percent自体が道路の始点→終点方向を基準にした符号付き値のため
道路自身の向きが本質的に必要——そのため風はタイル単位のスカラー値1個（同じタイル内の
全wayが同じ値）へ縮小できるが、勾配はway_idごとに異なる値を返す
（`RoadGraphRepository.get_way_gradient_inputs_in_tile`が返すway単位の
`(gradient_percent, road_bearing_deg)`と、ユーザー指定の走行方位から
`domain/gradient.py: GradientCalculator.effective_gradient`をway単位で計算する）。
`infrastructure/dynamic_way_value_cache.py`は両者を同じ`dict[way_id, float]`表現で
吸収するため、キャッシュ層自体は共有できる。

勾配は時刻に依存しないため、`at`パラメータは受け取らず（インターフェース統一のため
引数としては受け取るが無視する）、キャッシュキーの時刻バケットも常にNoneで扱う。TTLは
風のような気象データの新鮮さの制約が無いため、DB再問い合わせの頻度を抑える目的だけの
長めの値にする。
"""

import logging
from datetime import datetime

from app.domain.gradient import GradientCalculator
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, tile_ancestor, tile_bounds_lonlat
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.dynamic_way_value_cache import get_tile_values, set_tile_values
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.gradient_way")

MATERIAL_ID = "gradient"

# 勾配の入力（elevation_attributes.average_grade・road_edges.bearing_deg）は道路の向き・
# 標高由来の値でほぼ不変のため、風のような気象データの新鮮さの制約は無い。DBへの
# 再問い合わせ頻度を抑える目的だけの長めのTTL（24時間）にする——正本を持たない
# キャッシュのため、期限切れ後は単に再計算されるだけで安全（dynamic_way_value_cache.py
# のモジュールdocstring参照）。
GRADIENT_TILE_VALUES_TTL_SECONDS = 24 * 3600


class GradientWayService:
    # このサービスが返す生値の材料id（api/routers/region.pyが地図の表示値へ変換する際、
    # 軸定義のどの材料として評価するかを決める）。
    material_id = "gradient_percent"

    def __init__(self, repository: RoadGraphRepository | None):
        self._repository = repository

    async def get_way_values(
        self, z: int, x: int, y: int, at: datetime | None, bearing_deg: float | None, speed_kmh: float | None = None
    ) -> dict[int, float]:
        """指定タイル内のway_idごとの実効勾配（`GradientCalculator.effective_gradient`、
        正=登り・負=下り）を返す。repository未接続・取込範囲外・DB障害等はいずれも空dictへ
        倒す（他の動的配信層[wind_way_service.py]と同じグレースフルデグレード方針）。

        `at`・`speed_kmh`はrouter側の材料非依存な呼び出しインターフェース（`api/routers/region.py`の
        `/dynamic-way-values/{material_id}/...`）と揃えるためだけに受け取り、勾配の計算
        自体には使わない（勾配は時刻・走行速度に依存しない、モジュールdocstring参照）。

        bearing_degはユーザーがコンパススライダーで指定した走行方位（0〜360度、北=0・
        時計回り）。全道路共通の値として使うが、道路自身の向き（road_bearing_deg）との
        cos補正込みでway単位に異なる値になる（風とは異なる性質、モジュールdocstring参照）。
        型を`float | None`にしているのはrouter側インターフェースと揃えるためで、`at`と
        同じ理由（wind_way_service.pyのbearing_deg docstring参照）。勾配は常にbearing_degを
        必須とする材料のため、Noneのまま到達したら即座に失敗させる。
        """
        if bearing_deg is None:
            raise ValueError("GradientWayService.get_way_valuesにはbearing_degが必須です")
        if self._repository is None:
            return {}
        bbox = tile_bounds_lonlat(z, x, y)
        ancestor_x, ancestor_y = tile_ancestor(z, x, y, ROAD_GRAPH_TILE_ZOOM)

        with log_external_call("region:gradient-way-values", z=z, x=x, y=y) as fields:
            cached = await get_tile_values(MATERIAL_ID, z, x, y, None, bearing_deg)
            if cached is not None:
                fields["cache_hit"] = len(cached)
                fields["cache_status"] = "hit"
                return cached
            fields["cache_status"] = "miss"

            try:
                inputs = await self._repository.get_way_gradient_inputs_in_tile(
                    z, x, y, bbox, (ROAD_GRAPH_TILE_ZOOM, ancestor_x, ancestor_y)
                )
            except Exception as exc:  # noqa: BLE001 DB障害は空dictへ倒す（他タイル系と同じ方針）
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
            fields["way_count"] = len(inputs)

            values = {
                way_id: round(GradientCalculator.effective_gradient(gradient_percent, road_bearing_deg, bearing_deg), 1)
                for way_id, (gradient_percent, road_bearing_deg) in inputs.items()
            }
            await set_tile_values(MATERIAL_ID, z, x, y, None, bearing_deg, values, GRADIENT_TILE_VALUES_TTL_SECONDS)
            fields["computed"] = len(values)
            return values
