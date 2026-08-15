"""openrouteservice委譲のルーティングエンジン（Road Graph移行前の実装をポート化したもの）。

`RouteGenerator`（services/route_generator.py）の`LoopRoutingEngine`契約を実装する。
経由地点間の経路はopenrouteservice Directions API（`RoutingService`/`ORSClient`）へ
1方位1リクエストで委譲し、評価は距離フィルタ通過後の候補だけに対して
`ElevationService`（GSI標高API、12点サンプリング）・`WindService`（区間ごとの
推定到達時刻の風）で行う。

もう一方の`RoadGraphEngine`（road_graph_engine.py）との評価値の意味の違い:
- `wind_score`/`segments[].wind_penalty`: 本エンジンは区間ごとの**推定到達時刻**の風を
  使う（時間変化あり）。RoadGraphEngineは出発時点の風を全区間へ一様適用する
  （探索中は到達時刻が未確定という制約による簡略化）。長距離ほど乖離しうるため、
  レスポンスの`engine`フィールドでどちらの値かを識別できるようにしてある
- `road_score`・`segments[].road_surface_good`・区間難易度の重み（route_preference.yaml）は
  両エンジンで定義を統一済み（不明路面は分母から除外・難易度なし扱い。
  domain/road.py参照）
"""

import asyncio

from app.domain.difficulty import composite_difficulty, gradient_difficulty, road_difficulty, wind_difficulty
from app.domain.errors import RoutingError
from app.domain.evaluation import RoutePreference
from app.domain.geo import haversine_distance_km, sample_line_points
from app.domain.road import is_good_surface, paved_percent, surface_id_at_index
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.services.elevation_service import ElevationService
from app.services.route_generator import TracedLoop, candidate_identity
from app.services.routing_service import RoutingService
from app.services.wind_service import WindService

# 標高・風・路面を同じ点集合で評価するためのサンプリング密度。
# 以前はルート距離に関わらず12点固定で、30kmルートでは1区間約2.7kmと粗く、地図の
# 区間色分けから実態が読み取れなかった（研究IFレビューのフィードバック）。距離に応じて
# 約1km間隔になるよう点数を決め、下限12点（従来密度を下回らない）・上限32点で頭打ちにする。
# 上限は外部API問い合わせの安全弁: 標高は1点=GSI 1リクエスト（SQLiteキャッシュあり）のため、
# 最悪ケースでも8候補×32点=256リクエスト/生成に収まる（風はTTL＋座標丸めキャッシュにより
# 点数を増やしてもほぼ増えない）。地図の色分け粒度はこの点数がそのまま決める。
SAMPLE_INTERVAL_KM = 1.0
MIN_SAMPLE_COUNT = 12
MAX_SAMPLE_COUNT = 32


def sample_count_for_distance(distance_km: float) -> int:
    """ルート距離から約SAMPLE_INTERVAL_KM間隔になるサンプル点数を決める（min/maxでクランプ）。"""
    return max(MIN_SAMPLE_COUNT, min(MAX_SAMPLE_COUNT, round(distance_km / SAMPLE_INTERVAL_KM) + 1))

# prepareが返す「準備不要」を表すコンテキスト（本エンジンはリクエスト単位の共有準備を持たない）。
_NO_CONTEXT = object()


class OpenRouteServiceEngine:
    engine_name = "openrouteservice"

    def __init__(
        self,
        routing_service: RoutingService,
        elevation_service: ElevationService,
        wind_service: WindService,
        route_preference: RoutePreference,
    ):
        self._routing_service = routing_service
        self._elevation_service = elevation_service
        self._wind_service = wind_service
        self._route_preference = route_preference

    async def prepare(self, origin: Coordinates, radius_km: float):
        return _NO_CONTEXT

    async def trace_loop(self, context, waypoints: list[Coordinates], bearing: int) -> TracedLoop:
        try:
            segment = await self._routing_service.get_route(waypoints)
        except RoutingError as exc:
            raise RoutingError(f"direction {bearing} failed: {exc}") from exc
        return TracedLoop(bearing=bearing, distance_km=segment.distance_km, data=segment)

    async def evaluate_loops(self, context, traced: list[TracedLoop], start_time) -> list[RouteCandidate]:
        candidates = [
            RouteCandidate(
                **candidate_identity(t.bearing),
                distance_km=t.data.distance_km,
                geometry=t.data.geometry,
                road_score=paved_percent(t.data.surface_summary),
            )
            for t in traced
        ]
        surface_values_per_candidate = [t.data.surface_values for t in traced]

        # 標高・風・路面を同じ点集合（インデックス付き）で評価する
        sampled = [sample_line_points(c.geometry, sample_count_for_distance(c.distance_km)) for c in candidates]
        points_per_candidate = [[point for _, point in s] for s in sampled]
        indices_per_candidate = [[index for index, _ in s] for s in sampled]

        # 距離フィルタで棄却されなかった候補にのみ標高プロファイルを問い合わせる（GSIへの負荷を抑える）
        profiles = await asyncio.gather(
            *(self._elevation_service.get_profile(points) for points in points_per_candidate)
        )
        elevations_per_candidate = [profile.pop("elevations") for profile in profiles]
        candidates = [c.model_copy(update=profile) for c, profile in zip(candidates, profiles)]

        wind_profiles = await asyncio.gather(
            *(self._wind_service.get_wind_profile(points, start_time) for points in points_per_candidate)
        )
        wind_segments_per_candidate = [wp["segments"] for wp in wind_profiles]
        candidates = [
            c.model_copy(update={"wind_score": wp["wind_score"]}) for c, wp in zip(candidates, wind_profiles)
        ]

        # 地図の難易度レイヤー用に、区間ごとの詳細（標高・風・路面・難易度）を組み立てる
        return [
            c.model_copy(
                update={
                    "segments": self._build_segment_details(
                        points=points_per_candidate[i],
                        indices=indices_per_candidate[i],
                        elevations=elevations_per_candidate[i],
                        wind_segments=wind_segments_per_candidate[i],
                        surface_values=surface_values_per_candidate[i],
                        route_geometry=c.geometry,
                    )
                }
            )
            for i, c in enumerate(candidates)
        ]

    def _build_segment_details(
        self,
        points: list[Coordinates],
        indices: list[int],
        elevations: list[float | None],
        wind_segments: list[dict],
        surface_values: list[list] | None,
        route_geometry: dict,
    ) -> list[RouteSegmentDetail]:
        # 区間難易度の合成重みはroute_preference.yaml（Edge単位の絶対評価用の重み）を使う。
        # 以前はscoring.yaml（候補集合内の相対評価用）を流用しており、RoadGraphEngineと
        # 地図の色分けが食い違っていたため、両エンジンでこちらへ統一した。
        preference = self._route_preference
        segments = []
        cumulative_km = 0.0
        # 区間の道なり形状: サンプル点はルートgeometry上の点（インデックス付き）なので、
        # 隣接サンプル点間の座標列をそのまま切り出せば区間形状になる（追加のAPIコール無し。
        # sample_indicesは狭義単調増加のインデックスを返すため各スライスは必ず2点以上）。
        route_coordinates = route_geometry["coordinates"]

        for i in range(len(points) - 1):
            wind_segment = wind_segments[i] if i < len(wind_segments) else None
            distance_km = (
                wind_segment["distance_km"] if wind_segment else haversine_distance_km(points[i], points[i + 1])
            )

            e1 = elevations[i] if i < len(elevations) else None
            e2 = elevations[i + 1] if i + 1 < len(elevations) else None
            gradient_percent = None
            if e1 is not None and e2 is not None and distance_km > 0:
                # 符号付き（進行方向基準、登り=正/下り=負）。RoadGraphEngineの
                # ElevationAttribute.average_gradeと意味を統一する（domain/route.py:
                # RouteSegmentDetailの正準定義参照）。以前は絶対値で返しており、
                # フロントの勾配色分け（routeStyleModes.tsの「下り」カテゴリ）が
                # 本エンジンでは一度も表示されない不整合があった。難易度への変換は
                # gradient_difficultyが内部で絶対値を取るため影響しない。
                gradient_percent = (e2 - e1) / (distance_km * 1000) * 100

            wind_penalty = wind_segment["wind_penalty"] if wind_segment else None
            arrival_time = wind_segment["arrival_time"] if wind_segment else None

            surface_id = surface_id_at_index(indices[i], surface_values)
            road_surface_good = is_good_surface(surface_id)

            elevation_diff = gradient_difficulty(gradient_percent)
            wind_diff = wind_difficulty(wind_penalty)
            road_diff = road_difficulty(road_surface_good)
            difficulty = composite_difficulty(
                [
                    (elevation_diff, preference.elevation_weight),
                    (wind_diff, preference.wind_weight),
                    (road_diff, preference.road_weight),
                ]
            )

            segment_coordinates = route_coordinates[indices[i] : indices[i + 1] + 1]

            segments.append(
                RouteSegmentDetail(
                    geometry=(
                        {"type": "LineString", "coordinates": segment_coordinates}
                        if len(segment_coordinates) >= 2
                        else None
                    ),
                    start_latitude=points[i].latitude,
                    start_longitude=points[i].longitude,
                    end_latitude=points[i + 1].latitude,
                    end_longitude=points[i + 1].longitude,
                    cumulative_distance_km=round(cumulative_km, 2),
                    distance_km=round(distance_km, 2),
                    estimated_arrival_time=arrival_time.isoformat() if arrival_time else None,
                    gradient_percent=round(gradient_percent, 1) if gradient_percent is not None else None,
                    wind_penalty=wind_penalty,
                    road_surface_good=road_surface_good,
                    elevation_difficulty=elevation_diff,
                    wind_difficulty=wind_diff,
                    road_difficulty=road_diff,
                    difficulty=difficulty,
                )
            )
            cumulative_km += distance_km

        return segments
