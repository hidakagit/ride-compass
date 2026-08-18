"""Evaluation Engine（仕様書26-33章）。

Road Attribute（domain/attributes.py）とRoute PreferenceからEdge Costを算出する。
Route Engineから独立させ、Route Engine自身は「勾配がきつい」「路面が悪い」といった
評価の中身を一切知らない設計を目指す（仕様書33章）。

Score（難易度換算）は既存の`domain/difficulty.py`（Step9で導入、地図の難易度レイヤー用。
0-100、値が大きいほど走りにくい絶対基準）をそのまま再利用する。ルート単位の可視化と
Edge単位のEvaluation Engineが同じ「難易度」の意味・スケールを共有することで、新しい
正規化方式を発明せず、評価基準の食い違いも避ける。
"""

from pydantic import BaseModel

from app.domain.attributes import ElevationAttribute
from app.domain.difficulty import evaluate_axis_difficulties
from app.domain.geo import bearing_between
from app.domain.graph import DirectedEdge
from app.domain.recipe import (
    DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    DEFAULT_ROAD_SUITABILITY_RECIPE,
    MotorVehicleDensityRecipe,
    RoadSuitabilityRecipe,
    car_closeness,
)
from app.domain.road import classify_osm_surface
from app.domain.route import Coordinates
from app.domain.safety import SafetyRecipe, safety_level
from app.domain.traffic import TrafficStressRecipe, classify_bicycle_infrastructure, traffic_stress_level
from app.domain.weather import WeatherConditions
from app.domain.wind import WindCalculator

# 自転車で法的・実質的に通行できない道路種別（Hard Constraint、仕様書29章）。
# Costを上げるのではなく探索対象から除外する。将来、access/bicycleタグ等の
# より精密な判定に拡張する余地を残すため、ここではOSMのhighway分類のみを対象にする。
DISALLOWED_HIGHWAY_TYPES = {"motorway", "motorway_link", "trunk", "trunk_link"}


class RoutePreference(BaseModel):
    """Evaluation Engineが使う重み（仕様書27章）。

    Road Attributeとして実装済みの標高・路面・停止密度（信号・横断歩道・一時停止・踏切）・
    交通ストレス・自転車インフラ・交差点密度（静的道路属性P1残り）・事故密度（外部静的
    データソース T50）・安全度（改善計画: 安全度レシピ、9軸目）と、Dynamic Data対応
    （Phase 6）の風を対象とする。設定ファイルからの外部化はPhase 5で実施済み
    （route_preference.yaml、services/evaluation_service.py）。

    traffic_weight/infra_weight/intersection_weight/accident_weight/safety_weightは区間難易度・
    探索コスト（本モデル）にのみ効き、scoring.yaml（total_score＝おすすめ度、候補集合内の
    相対評価）には含めない（stop_weightと同じ扱い。ユーザー承認済みのスコープ判断、
    静的道路属性P1参照）。
    """

    elevation_weight: float = 0.15
    road_weight: float = 0.19
    wind_weight: float = 0.26
    stop_weight: float = 0.15
    traffic_weight: float = 0.10
    infra_weight: float = 0.10
    intersection_weight: float = 0.05
    accident_weight: float = 0.08
    safety_weight: float = 0.10


class EdgeCostResult(BaseModel):
    """Edge Costの算出結果。

    difficultyは0-100（大きいほど走りにくい、domain/difficulty.pyと同じ絶対基準）。
    costは距離ベース（メートル相当、小さいほど良い＝Route Engineが最短経路探索に
    そのまま使える単位）。allowed=FalseはHard Constraintによる除外を表し、この場合
    cost/difficultyはNoneになる。

    Road Graphへ恒久保存しない（仕様書32章）。このモデルは呼び出しごとの計算結果を
    表すだけであり、Route Preference・出発時刻（風）が変われば同じEdgeでも異なる
    結果になりうる。
    """

    edge_id: str
    cost: float | None
    difficulty: float | None
    allowed: bool


def is_edge_allowed(edge: DirectedEdge, way_tags: dict[str, str] | None = None) -> bool:
    """Hard Constraint（仕様書29章）。highwayタグが自転車で通行できない種別か、または
    `bicycle=no`（自転車通行不可）が明示されているかを判定する（改善計画T100でbicycle=noを追加）。

    highwayタグが無い（不明）場合、way_tagsが無い（未取得）場合は除外しない。判断材料が
    無いEdgeまで一律除外すると経路探索対象が過度に狭まるため、不明な場合は許可し
    Soft Constraint側の評価に委ねる（trafficStress/bicycle_infra評価と同じway_tags=None時の
    扱い、compute_edge_costのdocstring参照）。
    """
    if edge.highway is not None and edge.highway in DISALLOWED_HIGHWAY_TYPES:
        return False
    if way_tags is not None:
        bicycle = (way_tags.get("bicycle") or "").strip().lower()
        if bicycle == "no":
            return False
    return True


def compute_wind_penalty(edge: DirectedEdge, wind: WeatherConditions | None) -> float | None:
    """Edgeの進行方向（from_node→to_node）と風向風速からwind_penaltyを算出する
    （Dynamic Data対応、仕様書20・44章：Edge + Travel Direction + Timeから評価する）。

    正=向かい風、負=追い風（domain/wind.py: WindCalculatorをそのまま再利用）。風は
    Edgeに永続保存しない（動的データでありRoad Attributeとして扱わない、仕様書20章）。

    既知の簡略化: 本来は出発時刻とEdgeまでの推定累積走行時間から「そのEdgeを実際に
    通過するであろう時刻」の風を使うべきだが（ルート単位評価の`WindService`
    （`services/wind_service.py`、`routing_engine=="openrouteservice"`のときは今も
    `OpenRouteServiceEngine`が使う）はこの方式）、経路探索中（Dijkstra探索の途中）は
    まだ累積走行時間が確定していないため、探索対象領域全体で単一の風（出発時点・
    起点付近の風）を一様に適用する簡略化を採用している。将来、時間展開グラフ等で
    より精密化する余地がある（docs/architecture.md参照）。
    """
    if wind is None or len(edge.geometry) < 2:
        return None
    start_lat, start_lon = edge.geometry[0]
    end_lat, end_lon = edge.geometry[-1]
    bearing = bearing_between(
        Coordinates(latitude=start_lat, longitude=start_lon), Coordinates(latitude=end_lat, longitude=end_lon)
    )
    return WindCalculator.wind_penalty(wind.wind_speed_ms, wind.wind_direction_deg, bearing)


def compute_edge_cost(
    edge: DirectedEdge,
    elevation_attribute: ElevationAttribute | None,
    surface_type: str | None,
    preference: RoutePreference,
    wind: WeatherConditions | None = None,
    stop_count: int | None = None,
    way_tags: dict[str, str] | None = None,
    intersection_count: int | None = None,
    accident_count: int | None = None,
    accident_years_covered: int = 0,
    is_designated: bool = False,
    traffic_stress_recipe: TrafficStressRecipe | None = None,
    safety_recipe: SafetyRecipe | None = None,
    road_suitability_recipe: RoadSuitabilityRecipe | None = None,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
) -> EdgeCostResult:
    """RouteEngineが利用できるEdge Costを算出する（仕様書31章）。

    具体的な計算式（difficultyを距離への乗算ペナルティとして反映する方式）は今回の
    初期実装であり、固定ではない。加重和・ペナルティ方式などを比較検討できるよう、
    この関数だけを差し替えれば済む独立した責務にしてある（仕様書31章）。

    `wind`は省略可能（Noneなら風は評価に含めない、既存呼び出し元との後方互換）。
    `stop_count`はこのEdge上の信号・横断歩道・一時停止・踏切の合計個数（静的道路属性P1）。
    Noneはデータ無し（未評価、0個と区別する）。
    `way_tags`はこのEdgeのosm_way_idに対応する許可リストタグ（静的道路属性P0、
    交通ストレス・自転車インフラ評価の入力）。Noneはデータ未取得（repository未注入等）を表し
    両軸とも評価しない。タグ自体が空（`{}`）でも`edge.highway`があれば交通ストレスの基本値は
    評価できる（trafficStress_levelがhighwayのみでも決まるunknown安全設計のため）。
    `intersection_count`はこのEdge周辺の交差点（次数3以上のNode）の件数（静的道路属性P1残り）。
    Noneはデータ無し（未評価、0件と区別する）。
    `accident_count`はこのEdge周辺の事故（accident_points）の件数（外部静的データソース
    T50残作業、8軸目）。Noneはデータ無し（未評価、0件と区別する）。`accident_years_covered`は
    事故データの収録年数（`AttributeRepository.get_accident_years_covered`）で、密度を
    件/(km・年)へ正規化するために使う。
    `is_designated`はこのEdgeがKSJ N10/N12（緊急輸送道路・重要物流道路）に該当するか
    （外部静的データソース T51）。trafficStressへの補正のみに使い、新しい評価軸は増やさない。
    `traffic_stress_recipe`は交通ストレス軸の判定レシピの上書き（省略時はdomain/traffic.py:
    DEFAULT_TRAFFIC_STRESS_RECIPE）。研究モードでのレシピ調整用（一次情報→二次情報の変換式
    自体をリクエスト単位で差し替える）。
    `safety_recipe`は安全度軸の判定レシピの上書き（省略時はdomain/safety.py:
    DEFAULT_SAFETY_RECIPE）。traffic_stress_recipeと同じ扱い。
    `road_suitability_recipe`/`motor_vehicle_density_recipe`は交通ストレス・安全度が
    共有する「車との近さ」(N2)の材料の上書き（省略時はそれぞれdomain/recipe.py:
    DEFAULT_ROAD_SUITABILITY_RECIPE/DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE、改善計画:
    車との近さ材料の共有元化）。
    """
    if not is_edge_allowed(edge, way_tags):
        return EdgeCostResult(edge_id=edge.edge_id, cost=None, difficulty=None, allowed=False)

    gradient_percent = elevation_attribute.average_grade if elevation_attribute else None
    is_good_surface = classify_osm_surface(surface_type)
    wind_penalty = compute_wind_penalty(edge, wind)
    stop_count_per_km = stop_count / (edge.distance_m / 1000) if stop_count is not None and edge.distance_m > 0 else None
    # 「車との近さ」(N2、改善計画: 車との近さ材料の共有元化)はtraffic_stress_level・
    # safety_levelの両方が内部で同じ材料タグ・同じレシピから計算する共通の土台のため、
    # ここで1回だけ計算して両方へ渡す（全Edgeに対して2回ずつ計算する無駄を避ける）。
    car_closeness_result = (
        car_closeness(
            edge.highway,
            way_tags,
            is_designated,
            road_suitability_recipe or DEFAULT_ROAD_SUITABILITY_RECIPE,
            motor_vehicle_density_recipe or DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
        )
        if way_tags is not None
        else None
    )
    traffic_stress = (
        traffic_stress_level(
            edge.highway,
            way_tags,
            is_designated,
            traffic_stress_recipe,
            road_suitability_recipe=road_suitability_recipe,
            motor_vehicle_density_recipe=motor_vehicle_density_recipe,
            car_closeness_result=car_closeness_result,
        )
        if way_tags is not None
        else None
    )
    bicycle_infra = classify_bicycle_infrastructure(way_tags, edge.highway) if way_tags is not None else None
    intersection_count_per_km = (
        intersection_count / (edge.distance_m / 1000) if intersection_count is not None and edge.distance_m > 0 else None
    )
    accident_count_per_km_year = (
        accident_count / (edge.distance_m / 1000) / accident_years_covered
        if accident_count is not None and edge.distance_m > 0 and accident_years_covered > 0
        else None
    )
    safety = (
        safety_level(
            edge.highway,
            way_tags,
            is_designated,
            safety_recipe,
            road_suitability_recipe=road_suitability_recipe,
            motor_vehicle_density_recipe=motor_vehicle_density_recipe,
            car_closeness_result=car_closeness_result,
        )
        if way_tags is not None
        else None
    )

    difficulty = evaluate_axis_difficulties(
        gradient_percent, wind_penalty, is_good_surface, stop_count_per_km,
        traffic_stress, bicycle_infra, intersection_count_per_km, accident_count_per_km_year, safety,
        preference.elevation_weight, preference.wind_weight, preference.road_weight, preference.stop_weight,
        preference.traffic_weight, preference.infra_weight, preference.intersection_weight,
        preference.accident_weight, preference.safety_weight,
    ).composite

    # difficulty(0-100)を距離に対する乗算ペナルティへ変換する。
    # 0=最も走りやすい(係数1.0=距離そのまま)、100=最も走りにくい(係数2.0=距離の2倍のコスト)。
    penalty_multiplier = 1.0 + (difficulty / 100) if difficulty is not None else 1.0
    cost = edge.distance_m * penalty_multiplier

    return EdgeCostResult(edge_id=edge.edge_id, cost=round(cost, 1), difficulty=difficulty, allowed=True)
