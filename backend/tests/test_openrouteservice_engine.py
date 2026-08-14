"""OpenRouteServiceEngine（openrouteservice委譲エンジン）のテスト。

RouteGenerator（戦略層）を通したエンドツーエンドで、エンジン固有の責務
（RoutingServiceへの委譲・標高/風プロファイルのマージ・segments構築）を検証する。
戦略側の責務（距離フィルタ・失敗スキップ等）はtest_route_generator.pyで検証済み。
"""

from app.domain.difficulty import gradient_difficulty
from app.domain.errors import RoutingError
from app.domain.evaluation import RoutePreference
from app.domain.route import Coordinates, RouteSegment
from app.services.openrouteservice_engine import OpenRouteServiceEngine
from app.services.route_generator import DIRECTIONS_DEG, RouteGenerator
from app.services.route_scorer import RouteScorer

ORIGIN = Coordinates(latitude=35.7597, longitude=139.7387)

SCORING_WEIGHTS = {"distance_weight": 0.30, "elevation_weight": 0.15, "wind_weight": 0.30, "road_weight": 0.25}


def make_geometry():
    return {"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]}


class FakeRoutingService:
    """呼び出し順（asyncio.gatherが生成順に同期実行することに依存）に対応する結果を返す。

    フェイク自体に`await`を挟まないため、CPythonのasyncioは各コルーチンを
    生成順に完了させる。そのため`outcomes`のインデックスはDIRECTIONS_DEGの順序と対応する。
    """

    def __init__(self, outcomes: list):
        self._outcomes = outcomes
        self._call_count = 0

    async def get_route(self, waypoints: list[Coordinates]) -> RouteSegment:
        outcome = self._outcomes[self._call_count]
        self._call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def segment(distance_km: float) -> RouteSegment:
    return RouteSegment(distance_km=distance_km, duration_minutes=distance_km * 3, geometry=make_geometry())


class FakeElevationService:
    async def get_profile(self, points: list[Coordinates]) -> dict:
        return {
            "elevation_gain_m": 100.0,
            "min_elevation_m": 0.0,
            "max_elevation_m": 50.0,
            "max_gradient_percent": 8.0,
            "elevations": [0.0] * len(points),
        }


class FakeWindService:
    async def get_wind_profile(self, points: list[Coordinates], start_time) -> dict:
        segments = [
            {"distance_km": 1.0, "bearing_deg": 0.0, "arrival_time": start_time, "wind_penalty": 1.5}
            for _ in range(max(len(points) - 1, 0))
        ]
        return {"wind_score": 1.5, "segments": segments}


def make_generator(outcomes: list) -> RouteGenerator:
    engine = OpenRouteServiceEngine(
        FakeRoutingService(outcomes),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
    )
    return RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))


async def test_generates_one_candidate_per_direction_when_all_within_tolerance():
    generator = make_generator([segment(30.0) for _ in DIRECTIONS_DEG])

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert len(candidates) == len(DIRECTIONS_DEG)
    assert {c.id for c in candidates} == {f"route-{b:03d}" for b in DIRECTIONS_DEG}


async def test_skips_directions_where_routing_fails():
    outcomes = [segment(30.0) if i % 3 != 0 else RoutingError("no route") for i in range(len(DIRECTIONS_DEG))]
    generator = make_generator(outcomes)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    # i=0,3,6 が失敗するので8-3=5件
    assert len(candidates) == 5


async def test_merges_elevation_profile_into_candidates():
    generator = make_generator([segment(30.0) for _ in DIRECTIONS_DEG])

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.elevation_gain_m == 100.0 for c in candidates)
    assert all(c.max_gradient_percent == 8.0 for c in candidates)


async def test_merges_wind_score_into_candidates():
    generator = make_generator([segment(30.0) for _ in DIRECTIONS_DEG])

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.wind_score == 1.5 for c in candidates)


async def test_merges_total_score_and_sorts_by_it_descending():
    # 標高・風・路面（未取得のためNone）は全候補で同条件なので、total_scoreの順序は距離の近さの順序と一致するはず
    distances = [33.0, 30.0, 27.0, 34.0, 26.0, 30.0, 30.0, 30.0]
    generator = make_generator([segment(d) for d in distances])

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert all(c.total_score is not None for c in candidates)
    scores = [c.total_score for c in candidates]
    assert scores == sorted(scores, reverse=True)


async def test_builds_segment_details_for_map_visualization():
    generator = make_generator([segment(30.0) for _ in DIRECTIONS_DEG])

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    for candidate in candidates:
        # make_geometry()は2点なので区間は1つ
        assert len(candidate.segments) == 1
        seg = candidate.segments[0]
        assert seg.cumulative_distance_km == 0.0
        assert seg.gradient_percent == 0.0  # FakeElevationServiceの標高はどの点も同じ
        assert seg.wind_penalty == 1.5
        assert seg.road_surface_good is None  # サンプルのRouteSegmentにsurface_valuesが無いため
        assert seg.difficulty is not None  # 標高・風の指標は揃っているので合成できる


class FakeDescendingElevationService:
    """下り区間を表す標高（後の点ほど10m低い）を返す。"""

    async def get_profile(self, points: list[Coordinates]) -> dict:
        return {
            "elevation_gain_m": 0.0,
            "min_elevation_m": 40.0,
            "max_elevation_m": 50.0,
            "max_gradient_percent": 1.0,
            "elevations": [50.0 - 10.0 * i for i in range(len(points))],
        }


async def test_segment_gradient_is_signed_and_negative_for_downhill():
    """segments[].gradient_percentは符号付き（進行方向基準、下り=負）であること。

    RoadGraphEngine（ElevationAttribute.average_grade、符号付き）と意味を統一する。
    以前は絶対値で返しており、フロントの勾配色分けモード（routeStyleModes.tsの
    「下り」カテゴリ）が既定エンジンで一度も表示されない不整合があった（設計レビューB1）。
    """
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeDescendingElevationService(),
        FakeWindService(),
        RoutePreference(),
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    seg = candidates[0].segments[0]
    # 区間距離1.0km（FakeWindService）で標高差-10m → -1.0%
    assert seg.gradient_percent == -1.0
    # 難易度は勾配の絶対値で決まる（下りを「易しすぎる」扱いにはしない、domain/difficulty.py）
    assert seg.elevation_difficulty == gradient_difficulty(1.0)


async def test_engine_name_is_openrouteservice():
    generator = make_generator([segment(30.0) for _ in DIRECTIONS_DEG])

    assert generator.engine_name == "openrouteservice"
