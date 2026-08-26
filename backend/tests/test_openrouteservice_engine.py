"""OpenRouteServiceEngine（openrouteservice委譲エンジン）のテスト。

RouteGenerator（戦略層）を通したエンドツーエンドで、エンジン固有の責務
（RoutingServiceへの委譲・標高/風プロファイルのマージ・segments構築）を検証する。
戦略側の責務（距離フィルタ・失敗スキップ等）はtest_route_generator.pyで検証済み。
"""

from datetime import datetime, timezone

from app.domain.axis_definitions import AXIS_DEFINITIONS, evaluate_axis_scalar
from app.domain.errors import RoutingError
from app.domain.evaluation import RoutePreference
from app.domain.route import Coordinates, RouteSegment
from app.services.openrouteservice_engine import (
    MAX_SAMPLE_COUNT,
    MIN_SAMPLE_COUNT,
    OpenRouteServiceEngine,
    sample_count_for_distance,
)
from app.services.route_generator import DIRECTIONS_DEG, RouteGenerator
from app.services.route_scorer import RouteScorer

# 改善計画T350: 本番相当の14軸（実軸id前提のロジック用）はtests/conftest.pyのセッション
# スコープautouseフィクスチャが全テスト共通で用意する（tests/realistic_axis_fixtures.py参照）。

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
    async def prefetch(self, points_per_candidate: list[list[Coordinates]]) -> None:
        pass

    async def get_wind_profile(self, points: list[Coordinates], start_time) -> dict:
        segments = [
            {"distance_km": 1.0, "arrival_time": start_time, "wind_penalty": 1.5}
            for _ in range(max(len(points) - 1, 0))
        ]
        return {"wind_score": 1.5, "segments": segments}


class FakeSurfaceRepository:
    """`RoadGraphRepository.get_nearest_surface_tags`のFake（改善計画T21）。全候補分が
    1回のDBラウンドトリップにまとめられることを検証できるよう、呼び出し履歴を記録する。"""

    def __init__(
        self,
        default_tag: str | None = "asphalt",
        default_stop_count: int = 0,
        default_highway: str | None = "residential",
        default_way_tags: dict[str, str] | None = None,
        default_intersection_count: int = 0,
        default_accident_count: int = 0,
        accident_years_covered: int = 3,
        default_designated: bool = False,
    ):
        self._default_tag = default_tag
        self._default_stop_count = default_stop_count
        self._default_highway = default_highway
        self._default_way_tags = default_way_tags or {}
        self._default_intersection_count = default_intersection_count
        self._default_accident_count = default_accident_count
        self._accident_years_covered = accident_years_covered
        self._default_designated = default_designated
        self.calls: list[list[tuple[float, float]]] = []
        self.stop_count_calls: list[list[tuple[float, float]]] = []

    async def get_nearest_surface_tags(
        self, points: list[tuple[float, float]], max_distance_m: float = 30.0
    ) -> list[str | None]:
        self.calls.append(points)
        return [self._default_tag for _ in points]

    async def get_nearest_stop_poi_counts(
        self, points: list[tuple[float, float]], max_distance_m: float = 15.0
    ) -> list[int]:
        self.stop_count_calls.append(points)
        return [self._default_stop_count for _ in points]

    async def get_nearest_way_tags(
        self, points: list[tuple[float, float]], max_distance_m: float = 30.0
    ) -> list[tuple[str | None, dict[str, str], bool]]:
        # is_designatedは改善計画T76でget_nearest_designated_flagsから統合された。
        return [(self._default_highway, self._default_way_tags, self._default_designated) for _ in points]

    async def get_nearest_intersection_counts(
        self, points: list[tuple[float, float]], max_distance_m: float = 30.0
    ) -> list[int]:
        return [self._default_intersection_count for _ in points]

    async def get_nearest_accident_counts(
        self, points: list[tuple[float, float]], max_distance_m: float = 30.0
    ) -> list[int]:
        return [self._default_accident_count for _ in points]

    async def get_accident_years_covered(self) -> int:
        return self._accident_years_covered


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
        assert seg.road_surface_good is None  # repository未注入のため空間マッチ自体を行わない
        assert seg.difficulty is not None  # 標高・風の指標は揃っているので合成できる
    assert all(c.road_score is None for c in candidates)


async def test_road_surface_good_reflects_spatial_match_when_repository_injected():
    repository = FakeSurfaceRepository(default_tag="asphalt")
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
        repository=repository,
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(seg.road_surface_good is True for c in candidates for seg in c.segments)
    assert all(c.road_score == 100.0 for c in candidates)
    # 候補ごとに分割せず、全候補分のサンプル点をまとめて1回のDBラウンドトリップで問い合わせる
    assert len(repository.calls) == 1


async def test_road_surface_good_is_false_for_unpaved_tag_from_repository():
    repository = FakeSurfaceRepository(default_tag="gravel")
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
        repository=repository,
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(seg.road_surface_good is False for c in candidates for seg in c.segments)
    assert all(c.road_score == 0.0 for c in candidates)


async def test_stop_density_reflects_nearest_poi_counts_when_repository_injected():
    repository = FakeSurfaceRepository(default_tag="asphalt", default_stop_count=2)
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
        repository=repository,
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.stop_density is not None and c.stop_density > 0.0 for c in candidates)
    assert all(
        seg.axis_difficulties.get("stop_density", 0) > 0.0 for c in candidates for seg in c.segments
    )
    # 全候補分のサンプル点をまとめて1回のDBラウンドトリップで問い合わせる（路面と同じ方針）
    assert len(repository.stop_count_calls) == 1


async def test_stop_density_is_zero_without_nearby_pois():
    repository = FakeSurfaceRepository(default_tag="asphalt", default_stop_count=0)
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
        repository=repository,
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.stop_density == 0.0 for c in candidates)


async def test_car_stress_and_bicycle_infra_reflect_nearest_way_tags_when_repository_injected():
    # 静的道路属性P1残り。get_nearest_way_tagsで取得したhighway/tagsから車ストレス・
    # 自転車インフラを評価する。
    repository = FakeSurfaceRepository(
        default_tag="asphalt", default_highway="primary", default_way_tags={"cycleway": "track"}
    )
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
        repository=repository,
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    # 改善計画T353: car_stressはhighway種別のみで決まり自転車インフラの有無に影響
    # されなくなったため、trackがあってもprimary(highway_base=4)のまま最大値4になる。
    assert all(seg.car_stress == 4 for c in candidates for seg in c.segments)  # primary(4), track非依存
    assert all(c.car_stress_score is not None for c in candidates)
    assert all(c.bicycle_infra_score == 100.0 for c in candidates)


async def test_car_stress_reflects_designation_bonus_when_repository_injected():
    # 指定路線コンフレーション機構（外部静的データソース T51）。KSJ N10/N12該当は
    # carStressへ+1する。residential(base=2)で確認（primary等は既にクランプ上限4に
    # 近く効果が見えないため、上乗せの余地があるhighwayを選ぶ）。
    repository_designated = FakeSurfaceRepository(
        default_tag="asphalt", default_highway="residential", default_designated=True
    )
    repository_not_designated = FakeSurfaceRepository(
        default_tag="asphalt", default_highway="residential", default_designated=False
    )

    async def _car_stress_values(repository):
        engine = OpenRouteServiceEngine(
            FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
            FakeElevationService(),
            FakeWindService(),
            RoutePreference(),
            repository=repository,
        )
        generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))
        candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)
        return {seg.car_stress for c in candidates for seg in c.segments}

    designated_values = await _car_stress_values(repository_designated)
    not_designated_values = await _car_stress_values(repository_not_designated)

    # 改善計画T353: car_stressから自転車インフラ調整（旧car_stress_bicycle_infra_
    # adjustment、1材料1軸原則T268違反のため廃止）を排除したため、highway基準値(2)+
    # 指定路線補正(designated=1、not_designated=0)のみで決まる。breakpointsは
    # (0,0)-(4,100)へ再較正済み（旧(1,0)-(5,100)からのシフトで、difficulty自体は
    # 変わらないが表示レベルは1つ小さくなる）。
    assert designated_values == {3}  # (2+1-0)/4*100=75% -> level 3
    assert not_designated_values == {2}  # (2-0)/4*100=50% -> level 2


async def test_bicycle_infra_score_excludes_points_unmatched_to_any_way():
    # get_nearest_way_tagsが空間マッチに失敗した点(highway=None・tags={})を返すケース
    # （repository自体は注入されている＝実運用でも道路網カバレッジの境界等で起こりうる）。
    # 改善計画T347回帰テスト: 旧classify_bicycle_infrastructureは判定不能を"unknown"
    # （Noneではない）で返し、is_dedicated_bicycle_infraがこれをNone扱いすることで
    # データ欠損をbicycle_infra_scoreの分母から除外していた。新しいbicycle_infra_flagsは
    # 常に具体的なbool値を返すため区別が無く、呼び出し側（openrouteservice_engine.py）が
    # highwayの有無を見て明示的にNoneへ倒す必要がある（tagsだけを見るとtags={}を通過して
    # しまい、データ欠損が「専用インフラではないと確認された区間」として誤って混入する）。
    repository = FakeSurfaceRepository(default_tag="asphalt", default_highway=None, default_way_tags={})
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
        repository=repository,
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.bicycle_infra_score is None for c in candidates)


async def test_car_stress_and_bicycle_infra_are_none_without_repository():
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(seg.car_stress is None for c in candidates for seg in c.segments)
    assert all(c.car_stress_score is None and c.bicycle_infra_score is None for c in candidates)




async def test_intersection_density_reflects_nearest_intersection_counts_when_repository_injected():
    repository = FakeSurfaceRepository(default_tag="asphalt", default_intersection_count=1)
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
        repository=repository,
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.intersection_density is not None and c.intersection_density > 0.0 for c in candidates)
    # 改善計画T149: 交差点密度は独立軸を持たずstop_density側へ低い重みで吸収される
    # （旧intersection_difficultyは廃止）。
    assert all(
        seg.axis_difficulties.get("stop_density", 0) > 0.0
        for c in candidates
        for seg in c.segments
    )


async def test_accident_density_reflects_nearest_accident_counts_when_repository_injected():
    # 外部静的データソース T50残作業（8軸目）。
    repository = FakeSurfaceRepository(default_tag="asphalt", default_accident_count=1, accident_years_covered=2)
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
        repository=repository,
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.accident_density is not None and c.accident_density > 0.0 for c in candidates)
    assert all(
        seg.axis_difficulties.get("accident", 0) > 0 for c in candidates for seg in c.segments
    )


async def test_accident_density_is_none_without_repository():
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.accident_density is None for c in candidates)
    assert all("accident" not in seg.axis_difficulties for c in candidates for seg in c.segments)


async def test_intersection_density_is_none_without_repository():
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
    )
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.intersection_density is None for c in candidates)


async def test_stop_density_is_none_without_repository():
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0) for _ in DIRECTIONS_DEG]),
        FakeElevationService(),
        FakeWindService(),
        RoutePreference(),
    )  # repository未注入
    generator = RouteGenerator(engine, RouteScorer(SCORING_WEIGHTS))

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert all(c.stop_density is None for c in candidates)
    assert all("stop_density" not in seg.axis_difficulties for c in candidates for seg in c.segments)


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
    assert seg.axis_difficulties["gradient"] == evaluate_axis_scalar(
        AXIS_DEFINITIONS["gradient"], {"gradient_percent": 1.0}
    )


async def test_engine_name_is_openrouteservice():
    generator = make_generator([segment(30.0) for _ in DIRECTIONS_DEG])

    assert generator.engine_name == "openrouteservice"


def test_sample_count_scales_with_distance_within_bounds():
    # 約1km間隔・下限12（従来密度）・上限32（外部API問い合わせの安全弁）。
    assert sample_count_for_distance(5.0) == MIN_SAMPLE_COUNT
    assert sample_count_for_distance(11.0) == MIN_SAMPLE_COUNT
    assert sample_count_for_distance(15.0) == 16
    assert sample_count_for_distance(30.0) == 31
    assert sample_count_for_distance(100.0) == MAX_SAMPLE_COUNT


def make_dense_geometry(point_count: int) -> dict:
    # 東方向へ等間隔に並ぶpoint_count個の座標列（値の同一性で区間形状の切り出しを検証する）
    return {
        "type": "LineString",
        "coordinates": [[139.7 + i * 0.001, 35.75 + i * 0.0005] for i in range(point_count)],
    }


async def test_segments_carry_route_geometry_slices():
    """区間は道なり形状（ルートgeometryの部分列）を持ち、隣接区間で連続し全体を覆うこと
    （研究IF改善: 区間表示の道なり化。以前は始点・終点の直線チョードで描いており、
    カーブ区間で色分け線が道路から外れていた）。"""
    geometry = make_dense_geometry(100)
    outcomes = [
        RouteSegment(distance_km=30.0, duration_minutes=90.0, geometry=geometry) for _ in DIRECTIONS_DEG
    ]
    generator = make_generator(outcomes)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    seg_list = candidates[0].segments
    # 30km → 31点サンプリング＝30区間
    assert len(seg_list) == sample_count_for_distance(30.0) - 1
    reconstructed = []
    for seg in seg_list:
        assert seg.geometry is not None
        coordinates = seg.geometry["coordinates"]
        assert len(coordinates) >= 2
        # 形状の端点はstart/endフィールドと一致（GeoJSONは[lon, lat]順）
        assert coordinates[0] == [seg.start_longitude, seg.start_latitude]
        assert coordinates[-1] == [seg.end_longitude, seg.end_latitude]
        # 隣接区間の境界点（前区間の終端＝次区間の始端）を除いて連結すると元のgeometryに戻る
        reconstructed.extend(coordinates if not reconstructed else coordinates[1:])
    assert reconstructed == geometry["coordinates"]


# 改善計画T173: night軸の動的化。区間ごとの推定到達時刻（wind_penaltyと同じarrival_time）が
# その地点の市民薄明の外（夜間）ならnight_weightをそのまま、日中なら0倍にして合成する。
async def test_night_weight_zeroed_during_daytime_and_applied_at_night():
    repository = FakeSurfaceRepository()  # default_way_tags={}（litタグ無し）はnight_difficulty=50.0
    preference = RoutePreference(
        weights={"gradient": 0.0, "wind": 0.0, "surface_q": 0.0, "stop_density": 0.0,
                 "car_stress": 0.0, "accident": 0.0, "night": 1.0, "bicycle_infra_quality": 0.0}
    )
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0)]),
        FakeElevationService(),
        FakeWindService(),
        preference,
        repository=repository,
    )
    context = await engine.prepare(ORIGIN, radius_km=10.0)
    traced = await engine.trace_loop(context, [ORIGIN, ORIGIN, ORIGIN], bearing=0)

    # 東京、2024-06-21 12:00 JST（明らかに昼）= UTC 03:00
    daytime = datetime(2024, 6, 21, 3, 0, tzinfo=timezone.utc)
    # 東京、2024-06-21 02:00 JST（明らかに夜）= UTC 2024-06-20 17:00
    nighttime = datetime(2024, 6, 20, 17, 0, tzinfo=timezone.utc)

    day_candidates = await engine.evaluate_loops(context, [traced], daytime)
    night_candidates = await engine.evaluate_loops(context, [traced], nighttime)

    # night_weight=1.0のみ有効な本ケースでは、日中はcompositeを合成できる重みが1つも
    # 無くなり（他の軸は重み0）Noneに、夜間はnight_difficulty(50.0)そのものになる。
    assert day_candidates[0].segments[0].difficulty is None
    assert night_candidates[0].segments[0].difficulty == 50.0


async def test_evaluate_loops_does_not_crash_when_night_axis_is_unpublished(monkeypatch):
    # 改善計画T316フォローアップ回帰テスト: night軸が軸スタジオで非公開化されると
    # RoutePreference.weights・axis_difficulties.axesのどちらにも"night"キーが
    # 存在しなくなる。修正前はbase_axis_weights["night"]・axis_difficulties.axes["night"]
    # の直接indexingが素のKeyErrorで落ちていた（2026-08-25の実障害、7軸のどれが
    # 非公開化されても同型で発生しうる）。
    from app.domain.axis_definitions import AXIS_DEFINITIONS

    original_night = AXIS_DEFINITIONS["night"]
    monkeypatch.setitem(AXIS_DEFINITIONS, "night", original_night.model_copy(update={"is_published": False}))

    repository = FakeSurfaceRepository()
    preference = RoutePreference()
    assert "night" not in preference.weights  # night非公開のため既定値に含まれない前提の確認
    engine = OpenRouteServiceEngine(
        FakeRoutingService([segment(30.0)]),
        FakeElevationService(),
        FakeWindService(),
        preference,
        repository=repository,
    )
    context = await engine.prepare(ORIGIN, radius_km=10.0)
    traced = await engine.trace_loop(context, [ORIGIN, ORIGIN, ORIGIN], bearing=0)

    daytime = datetime(2024, 6, 21, 3, 0, tzinfo=timezone.utc)
    candidates = await engine.evaluate_loops(context, [traced], daytime)  # 例外が出ないことを確認

    assert "night" not in candidates[0].segments[0].axis_difficulties
