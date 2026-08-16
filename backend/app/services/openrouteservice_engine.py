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
  両エンジンで定義を統一済み（不明路面は分母から除外・難易度なし扱い。domain/road.py参照）。
  路面判定そのものも、本エンジンのサンプル点を自前DBのEdgeへ空間マッチ（`RoadGraphRepository.
  get_nearest_surface_tags`）して読むOSMタグ語彙に統一されている（改善計画T21。以前は
  openrouteservice側の数値ID語彙を使っていた）。`repository`未注入時
  （`settings.road_graph_use_repository=false`）は空間マッチ自体を行わず、路面評価は
  全区間Noneになる
"""

import asyncio
from dataclasses import dataclass

from app.domain.accident import ACCIDENT_MATCH_MAX_DISTANCE_M, distance_weighted_accident_density
from app.domain.difficulty import distance_weighted_difficulty, evaluate_axis_difficulties
from app.domain.errors import RoutingError
from app.domain.evaluation import RoutePreference
from app.domain.geo import haversine_distance_km, sample_line_points
from app.domain.road import SURFACE_MATCH_MAX_DISTANCE_M, classify_osm_surface, distance_weighted_road_score
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.domain.traffic import (
    INTERSECTION_MATCH_MAX_DISTANCE_M,
    STOP_POI_MATCH_MAX_DISTANCE_M,
    TrafficStressRecipe,
    classify_bicycle_infrastructure,
    distance_weighted_bicycle_infra_score,
    distance_weighted_intersection_density,
    distance_weighted_stop_density,
    is_dedicated_bicycle_infra,
    traffic_stress_level,
)
from app.infrastructure.road_graph_repository import RoadGraphRepository
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

# 空間マッチ半径（路面: domain/road.py: SURFACE_MATCH_MAX_DISTANCE_M、停止密度:
# domain/traffic.py: STOP_POI_MATCH_MAX_DISTANCE_M）はdomain層の定数を参照する
# （改善計画T44。road_graphエンジン側のAttributeRepositoryデフォルト引数も同じ定数を
# 参照するため、値の重複管理を構造的に防ぐ）。

# prepareが返す「準備不要」を表すコンテキスト（本エンジンはリクエスト単位の共有準備を持たない）。
_NO_CONTEXT = object()


@dataclass
class _PointAttributes:
    """サンプル点1つぶんの評価用属性（改善計画T78）。

    以前はsurface_tags/stop_counts/way_tags/intersection_counts/accident_counts/
    designated_flagsの6本の平行フラット配列で、属性1つの追加に「宣言・elseデフォルト・
    offsetループ内append・スライス・引数・`i < len(...)`ガード」という同型セットを
    毎回6箇所コピーする必要があった。append漏れ・順序ずれがあっても防御的ガードが
    「データ無し」として握りつぶすため、別属性の値が別地点へ紐づく誤評価がテストを
    すり抜けるリスクもあった。1つのdataclassへ束ね、offset簿記を`_split_by_counts`
    （呼び出し側）へ1箇所化する。

    デフォルト値は`repository`未注入時（DBなし構成）の値と一致させる。`highway`/`tags`は
    「repositoryはあるが空間マッチが範囲外」（highway=None・tags={}、traffic_stress等は
    Noneに評価される）と「repository自体が無い」（tags=None、評価自体をスキップ）を
    区別する必要があるため、tagsのデフォルトは`{}`ではなく`None`にする。
    """

    surface_tag: str | None = None
    stop_count: int | None = None
    highway: str | None = None
    tags: dict[str, str] | None = None
    is_designated: bool = False
    intersection_count: int | None = None
    accident_count: int | None = None


def _split_by_counts(flat: list, counts: list[int]) -> list[list]:
    """`flat`を先頭から`counts`の各要素数ずつ切り出す（複数候補ぶんをまとめて1回で
    問い合わせた結果を候補単位へ戻すoffset簿記の共通ヘルパ、改善計画T78）。"""
    result = []
    offset = 0
    for count in counts:
        result.append(flat[offset : offset + count])
        offset += count
    return result


class OpenRouteServiceEngine:
    engine_name = "openrouteservice"

    def __init__(
        self,
        routing_service: RoutingService,
        elevation_service: ElevationService,
        wind_service: WindService,
        route_preference: RoutePreference,
        repository: RoadGraphRepository | None = None,
        traffic_stress_recipe: TrafficStressRecipe | None = None,
    ):
        self._routing_service = routing_service
        self._elevation_service = elevation_service
        self._wind_service = wind_service
        self._route_preference = route_preference
        # 路面評価の空間マッチ用（改善計画T21）。GraphService/ElevationAttributeServiceと同じ
        # 「repository未注入時は該当評価をスキップしNoneを返す」パターン。
        self._repository = repository
        self._traffic_stress_recipe = traffic_stress_recipe

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
            )
            for t in traced
        ]

        # 標高・風・路面を同じ点集合（インデックス付き）で評価する
        sampled = [sample_line_points(c.geometry, sample_count_for_distance(c.distance_km)) for c in candidates]
        points_per_candidate = [[point for _, point in s] for s in sampled]
        indices_per_candidate = [[index for index, _ in s] for s in sampled]

        # 路面評価: 同じサンプル点集合を自前DBのEdgeへ空間マッチする（改善計画T21）。候補ごとに
        # 分けると最大MAX_SAMPLE_COUNT×候補数回のDBラウンドトリップに分割されるため、標高・風
        # （非同期I/O律速でasyncio.gather）とは違い、こちらは全候補分をまとめて1回で問い合わせる。
        point_counts = [len(points) for points in points_per_candidate]
        if self._repository is not None:
            flat_points = [(p.latitude, p.longitude) for points in points_per_candidate for p in points]
            flat_surface_tags = await self._repository.get_nearest_surface_tags(
                flat_points, max_distance_m=SURFACE_MATCH_MAX_DISTANCE_M
            )
            # 停止密度評価（信号・横断歩道・一時停止・踏切、静的道路属性P1）も同じサンプル点集合を
            # 使い、路面と同様に全候補分をまとめて1回で問い合わせる。
            flat_stop_counts = await self._repository.get_nearest_stop_poi_counts(
                flat_points, max_distance_m=STOP_POI_MATCH_MAX_DISTANCE_M
            )
            # 交通ストレス・自転車インフラ・交差点密度評価（静的道路属性P1残り）も同じ
            # サンプル点集合を使い、全候補分をまとめて1回で問い合わせる。指定路線コンフレーション
            # 機構（外部静的データソース T51、trafficStress補正）のis_designatedも、以前は
            # 専用メソッドの3本目の独立KNNだったが、同一サンプル点集合に対するクエリのため
            # get_nearest_way_tagsへ統合済み（改善計画T76）。
            flat_way_tags_full = await self._repository.get_nearest_way_tags(
                flat_points, max_distance_m=SURFACE_MATCH_MAX_DISTANCE_M
            )
            flat_intersection_counts = await self._repository.get_nearest_intersection_counts(
                flat_points, max_distance_m=INTERSECTION_MATCH_MAX_DISTANCE_M
            )
            # 事故密度評価（外部静的データソース T50残作業、8軸目）も同じサンプル点集合を使う。
            flat_accident_counts = await self._repository.get_nearest_accident_counts(
                flat_points, max_distance_m=ACCIDENT_MATCH_MAX_DISTANCE_M
            )
            accident_years_covered = await self._repository.get_accident_years_covered()
            # 6本の平行フラット配列（改善計画T78）を1つのdataclassへ束ねる。
            flat_attributes = [
                _PointAttributes(
                    surface_tag=flat_surface_tags[i],
                    stop_count=flat_stop_counts[i],
                    highway=flat_way_tags_full[i][0],
                    tags=flat_way_tags_full[i][1],
                    is_designated=flat_way_tags_full[i][2],
                    intersection_count=flat_intersection_counts[i],
                    accident_count=flat_accident_counts[i],
                )
                for i in range(len(flat_points))
            ]
        else:
            accident_years_covered = 0
            flat_attributes = [_PointAttributes() for _ in range(sum(point_counts))]
        attributes_per_candidate = _split_by_counts(flat_attributes, point_counts)

        # 距離フィルタで棄却されなかった候補にのみ標高プロファイルを問い合わせる（GSIへの負荷を抑える）
        profiles = await asyncio.gather(
            *(self._elevation_service.get_profile(points) for points in points_per_candidate)
        )
        elevations_per_candidate = [profile.pop("elevations") for profile in profiles]
        candidates = [c.model_copy(update=profile) for c, profile in zip(candidates, profiles)]

        # 候補（方位）ごとにget_wind_profileを並列実行すると、各候補が独立にOpen-Meteoへ
        # 1リクエストずつ投げるため候補数ぶん（最大8本）がほぼ同時に発火してしまう
        # （本番Renderの共有送信元IPで429が常態化する一因、weather_client.py参照）。
        # gatherの前に全候補分の点をまとめて1回先読みしキャッシュを温めておくことで、
        # 後続の候補ごとの呼び出しをキャッシュヒットさせHTTP発生を実質1回に減らす。
        await self._wind_service.prefetch(points_per_candidate)
        wind_profiles = await asyncio.gather(
            *(self._wind_service.get_wind_profile(points, start_time) for points in points_per_candidate)
        )
        wind_segments_per_candidate = [wp["segments"] for wp in wind_profiles]
        candidates = [
            c.model_copy(update={"wind_score": wp["wind_score"]}) for c, wp in zip(candidates, wind_profiles)
        ]

        # 地図の難易度レイヤー用に、区間ごとの詳細（標高・風・路面・難易度）を組み立てる。
        # road_score（候補単位の舗装率%）は区間のroad_surface_goodから距離加重で求める
        # （road_graph_engine.pyと同じdistance_weighted_road_score、改善計画T21）。
        results = []
        for i, c in enumerate(candidates):
            segments = self._build_segment_details(
                points=points_per_candidate[i],
                indices=indices_per_candidate[i],
                elevations=elevations_per_candidate[i],
                wind_segments=wind_segments_per_candidate[i],
                attributes=attributes_per_candidate[i],
                accident_years_covered=accident_years_covered,
                route_geometry=c.geometry,
            )
            road_score = distance_weighted_road_score([(s.distance_km, s.road_surface_good) for s in segments])
            # stop_density（回/km）も路面と同じ「サンプル点iの値を区間iの代表値として使う」
            # 近似（road_graph_engine.pyの_aggregate_stop_densityと集約方法は同じ。repository
            # 未注入時はNoneが並び、distance_weighted_stop_density側で「実測0件」と区別して除外される）。
            stop_density = distance_weighted_stop_density(
                [(s.distance_km, attributes_per_candidate[i][j].stop_count) for j, s in enumerate(segments)]
            )
            # 交通ストレス・自転車インフラ・交差点密度（静的道路属性P1残り）も同じ「サンプル点iの
            # 値を区間iの代表値として使う」近似で集約する。
            traffic_stress_score = distance_weighted_difficulty([(s.traffic_stress, s.distance_km) for s in segments])
            bicycle_infra_score = distance_weighted_bicycle_infra_score(
                [(s.distance_km, is_dedicated_bicycle_infra(s.bicycle_infra)) for s in segments]
            )
            intersection_density = distance_weighted_intersection_density(
                [(s.distance_km, attributes_per_candidate[i][j].intersection_count) for j, s in enumerate(segments)]
            )
            accident_density = distance_weighted_accident_density(
                [(s.distance_km, attributes_per_candidate[i][j].accident_count) for j, s in enumerate(segments)],
                accident_years_covered,
            )
            results.append(
                c.model_copy(
                    update={
                        "segments": segments,
                        "road_score": road_score,
                        "stop_density": stop_density,
                        "traffic_stress_score": traffic_stress_score,
                        "bicycle_infra_score": bicycle_infra_score,
                        "intersection_density": intersection_density,
                        "accident_density": accident_density,
                    }
                )
            )
        return results

    def _build_segment_details(
        self,
        points: list[Coordinates],
        indices: list[int],
        elevations: list[float | None],
        wind_segments: list[dict],
        attributes: list[_PointAttributes],
        accident_years_covered: int,
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

            # 改善計画T78: 6本の平行フラット配列だったsurface_tags/stop_counts/way_tags/
            # intersection_counts/accident_counts/designated_flagsを1つの_PointAttributesへ
            # 束ねたことで、境界外ガードもここ1箇所に集約された。
            attr = attributes[i] if i < len(attributes) else _PointAttributes()

            road_surface_good = classify_osm_surface(attr.surface_tag)
            stop_count = attr.stop_count
            stop_count_per_km = stop_count / distance_km if stop_count is not None and distance_km > 0 else None

            highway, tags, is_designated = attr.highway, attr.tags, attr.is_designated
            traffic_stress = (
                traffic_stress_level(highway, tags, is_designated, self._traffic_stress_recipe)
                if tags is not None
                else None
            )
            bicycle_infra = classify_bicycle_infrastructure(tags, highway) if tags is not None else None
            intersection_count = attr.intersection_count
            intersection_count_per_km = (
                intersection_count / distance_km if intersection_count is not None and distance_km > 0 else None
            )
            accident_count = attr.accident_count
            accident_count_per_km_year = (
                accident_count / distance_km / accident_years_covered
                if accident_count is not None and distance_km > 0 and accident_years_covered > 0
                else None
            )

            axis_difficulties = evaluate_axis_difficulties(
                gradient_percent, wind_penalty, road_surface_good, stop_count_per_km,
                traffic_stress, bicycle_infra, intersection_count_per_km, accident_count_per_km_year,
                preference.elevation_weight, preference.wind_weight, preference.road_weight, preference.stop_weight,
                preference.traffic_weight, preference.infra_weight, preference.intersection_weight,
                preference.accident_weight,
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
                    traffic_stress=traffic_stress,
                    bicycle_infra=bicycle_infra,
                    elevation_difficulty=axis_difficulties.elevation,
                    wind_difficulty=axis_difficulties.wind,
                    road_difficulty=axis_difficulties.road,
                    stop_difficulty=axis_difficulties.stop,
                    traffic_difficulty=axis_difficulties.traffic,
                    infra_difficulty=axis_difficulties.infra,
                    intersection_difficulty=axis_difficulties.intersection,
                    accident_difficulty=axis_difficulties.accident,
                    difficulty=axis_difficulties.composite,
                )
            )
            cumulative_km += distance_km

        return segments
