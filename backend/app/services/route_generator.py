import asyncio
from datetime import datetime, timedelta, timezone

from app.domain.difficulty import composite_difficulty, gradient_difficulty, road_difficulty, wind_difficulty
from app.domain.errors import RoutingError
from app.domain.geo import compass_label, destination_point, haversine_distance_km, sample_line_points
from app.domain.road import is_good_surface, paved_percent, surface_id_at_index
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.services.elevation_service import ElevationService
from app.services.route_scorer import RouteScorer, load_scoring_weights
from app.services.routing_service import RoutingService
from app.services.wind_service import WindService

# 8方位（北を0として時計回り）
DIRECTIONS_DEG = [0, 45, 90, 135, 180, 225, 270, 315]

# 半径ヒューリスティック: 仕様書7章の目安（30kmなら半径10〜15km程度）に近い値。
# 適応的な探索は行わないため、実際の道路網次第で距離のばらつきが生じる（既知の制約）。
RADIUS_RATIO = 1 / 3

# サーバーのローカル時刻＝Asia/Tokyoという簡易近似（Open-Meteoのhourlyもtimezone=Asia/Tokyo
# 指定でnaiveなローカル時刻文字列を返すため整合している。詳細はdocs/architecture.md参照）。
# IANAタイムゾーンDB（zoneinfo）はWindows等で別途tzdataパッケージが要るため、日本にDSTが
# 無いことを利用して固定オフセットで表現し、追加依存なしでdatetimeをtz-awareにする。
# tz-awareにすることで.isoformat()にオフセットが付き、フロントの`new Date(iso)`が
# ブラウザのローカルタイムゾーンに関わらず同じ絶対時刻として解釈できるようになる。
JST = timezone(timedelta(hours=9))

# 標高・風・路面を同じ点集合で評価するためのサンプリング密度。
# 密度を上げると地図の難易度レイヤーは滑らかになるが、GSI/Open-Meteoへの問い合わせ数が
# 比例して増え生成時間が伸びるため、Step5-7から使ってきた密度をそのまま踏襲する（既知の制約）。
SAMPLE_COUNT = 12


class RouteGenerator:
    def __init__(
        self,
        routing_service: RoutingService,
        elevation_service: ElevationService,
        wind_service: WindService,
        route_scorer: RouteScorer,
    ):
        self._routing_service = routing_service
        self._elevation_service = elevation_service
        self._wind_service = wind_service
        self._route_scorer = route_scorer

    async def generate_loops(
        self,
        origin: Coordinates,
        distance_km: float,
        distance_tolerance_km: float,
    ) -> list[RouteCandidate]:
        radius_km = distance_km * RADIUS_RATIO

        results = await asyncio.gather(
            *(self._build_candidate(origin, bearing, radius_km) for bearing in DIRECTIONS_DEG),
            return_exceptions=True,
        )

        pairs = [r for r in results if isinstance(r, tuple)]
        pairs = [(c, sv) for c, sv in pairs if abs(c.distance_km - distance_km) <= distance_tolerance_km]
        pairs.sort(key=lambda cs: abs(cs[0].distance_km - distance_km))

        candidates = [c for c, _ in pairs]
        surface_values_per_candidate = [sv for _, sv in pairs]

        # 標高・風・路面を同じ点集合（インデックス付き）で評価する
        sampled = [sample_line_points(c.geometry, SAMPLE_COUNT) for c in candidates]
        points_per_candidate = [[point for _, point in s] for s in sampled]
        indices_per_candidate = [[index for index, _ in s] for s in sampled]

        # 棄却されなかった候補にのみ標高プロファイルを問い合わせる（GSIへの負荷を抑える）
        profiles = await asyncio.gather(
            *(self._elevation_service.get_profile(points) for points in points_per_candidate)
        )
        elevations_per_candidate = [profile.pop("elevations") for profile in profiles]
        candidates = [c.model_copy(update=profile) for c, profile in zip(candidates, profiles)]

        # 出発時刻を「今」として、各候補の風負荷を評価する
        start_time = datetime.now(JST)
        wind_profiles = await asyncio.gather(
            *(self._wind_service.get_wind_profile(points, start_time) for points in points_per_candidate)
        )
        wind_segments_per_candidate = [wp["segments"] for wp in wind_profiles]
        candidates = [
            c.model_copy(update={"wind_score": wp["wind_score"]}) for c, wp in zip(candidates, wind_profiles)
        ]

        # 地図の難易度レイヤー用に、区間ごとの詳細（標高・風・路面・難易度）を組み立てる
        weights = load_scoring_weights()
        candidates = [
            c.model_copy(
                update={
                    "segments": self._build_segment_details(
                        points=points_per_candidate[i],
                        indices=indices_per_candidate[i],
                        elevations=elevations_per_candidate[i],
                        wind_segments=wind_segments_per_candidate[i],
                        surface_values=surface_values_per_candidate[i],
                        weights=weights,
                    )
                }
            )
            for i, c in enumerate(candidates)
        ]

        # 距離・獲得標高・風・路面を合成したtotal_scoreを算出し、良い候補が先頭に来るよう並べ替える
        candidates = self._route_scorer.score(candidates, distance_km)
        candidates.sort(key=lambda c: c.total_score if c.total_score is not None else -1, reverse=True)

        return candidates

    async def _build_candidate(
        self, origin: Coordinates, bearing: int, radius_km: float
    ) -> tuple[RouteCandidate, list[list] | None]:
        waypoint_a = destination_point(origin, bearing, radius_km)
        waypoint_b = destination_point(origin, (bearing + 45) % 360, radius_km)

        try:
            segment = await self._routing_service.get_route([origin, waypoint_a, waypoint_b, origin])
        except RoutingError as exc:
            raise RoutingError(f"direction {bearing} failed: {exc}") from exc

        candidate = RouteCandidate(
            id=f"route-{bearing:03d}",
            direction_label=compass_label(bearing),
            distance_km=segment.distance_km,
            geometry=segment.geometry,
            road_score=paved_percent(segment.surface_summary),
        )
        return candidate, segment.surface_values

    def _build_segment_details(
        self,
        points: list[Coordinates],
        indices: list[int],
        elevations: list[float | None],
        wind_segments: list[dict],
        surface_values: list[list] | None,
        weights: dict[str, float],
    ) -> list[RouteSegmentDetail]:
        segments = []
        cumulative_km = 0.0

        for i in range(len(points) - 1):
            wind_segment = wind_segments[i] if i < len(wind_segments) else None
            distance_km = (
                wind_segment["distance_km"] if wind_segment else haversine_distance_km(points[i], points[i + 1])
            )

            e1 = elevations[i] if i < len(elevations) else None
            e2 = elevations[i + 1] if i + 1 < len(elevations) else None
            gradient_percent = None
            if e1 is not None and e2 is not None and distance_km > 0:
                gradient_percent = abs(e2 - e1) / (distance_km * 1000) * 100

            wind_penalty = wind_segment["wind_penalty"] if wind_segment else None
            arrival_time = wind_segment["arrival_time"] if wind_segment else None

            surface_id = surface_id_at_index(indices[i], surface_values)
            road_surface_good = is_good_surface(surface_id)

            elevation_diff = gradient_difficulty(gradient_percent)
            wind_diff = wind_difficulty(wind_penalty)
            road_diff = road_difficulty(road_surface_good)
            difficulty = composite_difficulty(
                [
                    (elevation_diff, weights["elevation_weight"]),
                    (wind_diff, weights["wind_weight"]),
                    (road_diff, weights["road_weight"]),
                ]
            )

            segments.append(
                RouteSegmentDetail(
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
