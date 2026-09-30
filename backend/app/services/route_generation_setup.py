"""探索エンジンの組み立てと、省略された評価条件の既定の解決。"""

from dataclasses import dataclass

from app.domain.errors import RoutingError
from app.domain.evaluation import resolve_penalty_strength
from app.domain.hard_filters import DEFAULT_HARD_FILTERS
from app.domain.route import Coordinates, RouteSegment
from app.domain.route_preference import RoutePreference
from app.domain.wind import ASSUMED_SPEED_KMH
from app.services.graph_service import GraphService
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import RouteGenerator
from app.services.weather_service import WeatherService


@dataclass
class RouteGenerationSetup:
    """組み立て済みのエンジンと、実際に適用された評価条件。

    `route_preference`以降はレスポンスの条件エコーにもそのまま使う。
    """

    engine: RoadGraphEngine
    generator: RouteGenerator
    route_preference: RoutePreference
    # 主観的割増と時間の換算レート（P）。
    penalty_strength: float
    # 仮定巡航速度（km/h）。通過予定時刻・到達予想時刻・所要時間の算出に使う。
    assumed_speed_kmh: float
    # 0次ハードフィルタの勾配しきい値（%、Noneは無効）。
    max_average_grade_percent: float | None
    # 0次ハードフィルタ名の個別ON/OFF上書き。常に解決済み（Noneではなく実際に適用された集合）。
    hard_filters: frozenset[str]


def assemble_route_generation_setup(
    graph_service: GraphService,
    weather_service: WeatherService,
    *,
    preference_override: RoutePreference | None = None,
    penalty_strength: float | None = None,
    max_average_grade_percent: float | None = None,
    hard_filters_override: frozenset[str] | None = None,
    assumed_speed_kmh: float = ASSUMED_SPEED_KMH,
    lens_axis_id: str | None = None,
) -> RouteGenerationSetup:
    """エンジンを組む唯一の入口。ルート生成・区間確認・計測・テストのどれもここを通る。

    省略された評価条件の既定はここで1度だけ決める。以後は解決済みの値だけを回し、
    レスポンスのconditionsへも同じ値をエコーする（画面が見る値と探索が使う値を分けない）。
    """
    preference = preference_override or RoutePreference()
    hard_filters = hard_filters_override if hard_filters_override is not None else DEFAULT_HARD_FILTERS
    resolved_penalty_strength = resolve_penalty_strength(penalty_strength)
    engine = RoadGraphEngine(
        graph_service,
        weather_service,
        route_preference=preference,
        penalty_strength=resolved_penalty_strength,
        max_average_grade_percent=max_average_grade_percent,
        hard_filters=hard_filters,
        assumed_speed_kmh=assumed_speed_kmh,
        lens_axis_id=lens_axis_id,
    )
    return RouteGenerationSetup(
        engine=engine,
        generator=RouteGenerator(engine),
        route_preference=preference,
        penalty_strength=resolved_penalty_strength,
        assumed_speed_kmh=assumed_speed_kmh,
        max_average_grade_percent=max_average_grade_percent,
        hard_filters=hard_filters,
    )


class RoutePreviewService:
    """`/api/routes/preview`（単一区間確認）。

    評価条件のうち想定速度だけを受け取り、それ以外はルート生成が省略時に使うのと同じ既定で探す。
    """

    def __init__(self, graph_service: GraphService, weather_service: WeatherService):
        self._graph_service = graph_service
        self._weather_service = weather_service

    async def preview(
        self, origin: Coordinates, destination: Coordinates, assumed_speed_kmh: float = ASSUMED_SPEED_KMH
    ) -> RouteSegment:
        setup = assemble_route_generation_setup(
            self._graph_service, self._weather_service, assumed_speed_kmh=assumed_speed_kmh
        )
        segment = await setup.engine.preview_segment(origin, destination)
        if segment is None:
            raise RoutingError("road_graph: no path found between origin and destination")
        return segment
