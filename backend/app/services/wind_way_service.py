"""way_id→wind_penalty配信層（改善計画T405→T414で作り直し、docs/tasks/T400.md「2. 動的要素
（時刻・向き等）を含む材料は状態（ルートの有無）に応じてパラメータの出所と塗る対象が変わる」節）。

「評価軸」グループとしての風（ルート未確定時、視界内の全道路へユーザー指定の[時刻,向き]を
一律適用する線表示）の基盤。「環境」グループの風（時刻＋方位スライダー＋`gridFill`面表示、
windLayer.ts/dynamicWeather.ts）とは別経路だが、**同じ[時刻,向き]のユーザー入力を共有する**
（T400.md「2.」節）。

**T414での設計変更**: T405時点の実装は、道路のbearing_deg（道路自身のOSM格納方向）と
風グリッドを掛け合わせて`wind_penalty`を計算していたが、これは実機フィードバックで発覚した
設計ミスだった——道路自身の向きはデータ収集上の都合で決まる値であり、ユーザーの走行方向とは
無関係。訂正後は、走行方位（travel_bearing_deg）は**ユーザーがコンパススライダーで指定した
単一の値**（全道路共通）を使う。この結果、同じタイル内の全wayは常に同じwind_penalty値を
持つ（風グリッドもタイル中心1点で代表させる既存の近似のため）——道路自身の向きの取得
（旧`get_way_bearings_in_tile`、ST_Azimuth）は不要になり、対象タイルに存在するway_idの一覧
（`get_way_ids_in_tile`）だけを取得すればよい。計算結果のキャッシュも、way_idごとではなく
タイル単位のスカラー値1個で足りる（`wind_way_penalty_cache.py`のモジュールdocstring参照）。
"""

import logging
from datetime import datetime

from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_ancestor, tile_bounds_lonlat
from app.domain.route import Coordinates
from app.domain.wind import WindCalculator
from app.domain.wind_grid import nearest_grid_point
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.infrastructure.wind_way_penalty_cache import get_tile_penalty, set_tile_penalty
from app.services.route_generator import JST
from app.services.weather_service import WeatherService

logger = logging.getLogger("ridecompass.wind_way")


def _hour_bucket(at: datetime) -> str:
    """時刻を1時間バケットへ丸める（wind_way_penalty_cache.pyのキー、モジュールdocstring参照）。"""
    return at.strftime("%Y-%m-%dT%H")


def _tile_center(bbox: BoundingBox) -> Coordinates:
    return Coordinates(
        latitude=(bbox.min_latitude + bbox.max_latitude) / 2,
        longitude=(bbox.min_longitude + bbox.max_longitude) / 2,
    )


def _nearest_time_index(times: list[str], target: datetime) -> int | None:
    """風グリップのhourly時刻配列から、targetに最も近いindexを求める
    （weather_service.py: WeatherService._nearest_hourly_index/_within_hourly_rangeと同じ
    「最近傍だが範囲外は不可」という考え方を踏襲した簡易版。targetはtz-aware/naiveどちらでも
    受け付け、wall-clock成分[JST想定、route_generator.py: JSTのコメント参照]だけを比較する）。
    範囲外（風グリッドがまだ届いていない遠い未来・過去）はNoneを返し、呼び出し元は「不明」
    として扱う。"""
    if not times:
        return None
    target_naive = target.replace(tzinfo=None)
    parsed = [datetime.fromisoformat(t) for t in times]
    if target_naive < min(parsed) or target_naive > max(parsed):
        return None
    diffs = [abs((t - target_naive).total_seconds()) for t in parsed]
    return diffs.index(min(diffs))


class WindWayService:
    def __init__(self, repository: RoadGraphRepository | None, weather_service: WeatherService):
        self._repository = repository
        self._weather_service = weather_service

    async def get_way_wind_penalties(
        self, z: int, x: int, y: int, at: datetime | None, bearing_deg: float
    ) -> dict[int, float]:
        """指定タイル内のway_idごとのwind_penaltyを返す（T414の訂正後契約では、同じタイル内の
        全wayは同じ値を持つ——モジュールdocstring参照）。repository未接続・取込範囲外・
        風データ取得不能等はいずれも空dictへ倒す（地図表示という既存機能全体を落とさず、
        「この道路には色が付かない」という安全側の劣化で済ませる、他タイル系メソッドと
        同じグレースフルデグレード方針）。

        bearing_degはユーザーがコンパススライダーで指定した走行方位（0〜360度、北=0・
        時計回り）。全道路共通の値として使う。
        """
        if self._repository is None:
            return {}
        target = at or datetime.now(JST)
        bbox = tile_bounds_lonlat(z, x, y)
        ancestor_x, ancestor_y = tile_ancestor(z, x, y, ROAD_GRAPH_TILE_ZOOM)

        with log_external_call("region:wind-way-penalty", z=z, x=x, y=y) as fields:
            try:
                way_ids = await self._repository.get_way_ids_in_tile(
                    z, x, y, bbox, (ROAD_GRAPH_TILE_ZOOM, ancestor_x, ancestor_y)
                )
            except Exception as exc:  # noqa: BLE001 DB障害は空dictへ倒す（他タイル系と同じ方針）
                fields["result"] = "error"
                fields["warned"] = True
                logger.warning("風の評価軸配信のway_id取得に失敗 z=%d x=%d y=%d error=%r", z, x, y, exc)
                return {}
            if not way_ids:
                fields["postgis"] = "uncovered" if way_ids is None else "empty"
                return {}
            fields["way_count"] = len(way_ids)

            hour_bucket = _hour_bucket(target)
            cached = await get_tile_penalty(z, x, y, hour_bucket, bearing_deg)
            if cached is not None:
                fields["cache_hit"] = len(way_ids)
                fields["cache_status"] = "hit"
                penalty = cached
            else:
                fields["cache_status"] = "miss"

                grid_point = nearest_grid_point(_tile_center(bbox))
                times, points = await self._weather_service.get_wind_grid([grid_point])
                wind_grid_point = points[0] if points else None
                if wind_grid_point is None:
                    fields["wind_grid"] = "unavailable"
                    logger.warning("風の評価軸配信の風グリッド取得に失敗 z=%d x=%d y=%d", z, x, y)
                    return {}
                index = _nearest_time_index(times, target)
                if index is None:
                    fields["wind_grid"] = "out_of_range"
                    logger.warning("風の評価軸配信の時刻が風グリッド範囲外 z=%d x=%d y=%d", z, x, y)
                    return {}

                wind_speed = wind_grid_point.wind_speed_ms[index]
                wind_direction = wind_grid_point.wind_direction_deg[index]
                penalty = round(WindCalculator.wind_penalty(wind_speed, wind_direction, bearing_deg), 2)
                await set_tile_penalty(z, x, y, hour_bucket, bearing_deg, penalty)
                fields["computed"] = len(way_ids)

            # T414の訂正後契約では同じタイル内の全wayが同じ値を持つため、キャッシュhit/miss
            # いずれの経路もここで1回だけbroadcastする。
            return dict.fromkeys(way_ids, penalty)
