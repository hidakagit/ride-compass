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
from app.domain.difficulty import composite_difficulty, gradient_difficulty, road_difficulty, stop_difficulty, wind_difficulty
from app.domain.geo import bearing_between
from app.domain.graph import DirectedEdge
from app.domain.road import classify_osm_surface
from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions
from app.domain.wind import WindCalculator

# 自転車で法的・実質的に通行できない道路種別（Hard Constraint、仕様書29章）。
# Costを上げるのではなく探索対象から除外する。将来、access/bicycleタグ等の
# より精密な判定に拡張する余地を残すため、ここではOSMのhighway分類のみを対象にする。
DISALLOWED_HIGHWAY_TYPES = {"motorway", "motorway_link", "trunk", "trunk_link"}


class RoutePreference(BaseModel):
    """Evaluation Engineが使う重み（仕様書27章）。

    Road Attributeとして実装済みの標高・路面・停止密度（信号・横断歩道・一時停止・踏切、
    静的道路属性P1）と、Dynamic Data対応（Phase 6）の風を対象とする（交通ストレス・
    自転車インフラは未実装のまま、docs/static-road-attributes-plan.md P1参照）。
    設定ファイルからの外部化はPhase 5で実施済み（route_preference.yaml、
    services/evaluation_service.py）。
    """

    elevation_weight: float = 0.20
    road_weight: float = 0.25
    wind_weight: float = 0.35
    stop_weight: float = 0.20


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


def is_edge_allowed(edge: DirectedEdge) -> bool:
    """Hard Constraint（仕様書29章）。highwayタグが自転車で通行できない種別かどうかを判定する。

    highwayタグが無い（不明）場合は除外しない。判断材料が無いEdgeまで一律除外すると
    経路探索対象が過度に狭まるため、不明な場合は許可しSoft Constraint側の評価に委ねる。
    """
    if edge.highway is None:
        return True
    return edge.highway not in DISALLOWED_HIGHWAY_TYPES


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
) -> EdgeCostResult:
    """RouteEngineが利用できるEdge Costを算出する（仕様書31章）。

    具体的な計算式（difficultyを距離への乗算ペナルティとして反映する方式）は今回の
    初期実装であり、固定ではない。加重和・ペナルティ方式などを比較検討できるよう、
    この関数だけを差し替えれば済む独立した責務にしてある（仕様書31章）。

    `wind`は省略可能（Noneなら風は評価に含めない、既存呼び出し元との後方互換）。
    `stop_count`はこのEdge上の信号・横断歩道・一時停止・踏切の合計個数（静的道路属性P1）。
    Noneはデータ無し（未評価、compute_edge_cost自体は0個と区別する）。
    """
    if not is_edge_allowed(edge):
        return EdgeCostResult(edge_id=edge.edge_id, cost=None, difficulty=None, allowed=False)

    gradient_percent = elevation_attribute.average_grade if elevation_attribute else None
    is_good_surface = classify_osm_surface(surface_type)
    wind_penalty = compute_wind_penalty(edge, wind)
    stop_count_per_km = stop_count / (edge.distance_m / 1000) if stop_count is not None and edge.distance_m > 0 else None

    difficulty = composite_difficulty(
        [
            (gradient_difficulty(gradient_percent), preference.elevation_weight),
            (road_difficulty(is_good_surface), preference.road_weight),
            (wind_difficulty(wind_penalty), preference.wind_weight),
            (stop_difficulty(stop_count_per_km), preference.stop_weight),
        ]
    )

    # difficulty(0-100)を距離に対する乗算ペナルティへ変換する。
    # 0=最も走りやすい(係数1.0=距離そのまま)、100=最も走りにくい(係数2.0=距離の2倍のコスト)。
    penalty_multiplier = 1.0 + (difficulty / 100) if difficulty is not None else 1.0
    cost = edge.distance_m * penalty_multiplier

    return EdgeCostResult(edge_id=edge.edge_id, cost=round(cost, 1), difficulty=difficulty, allowed=True)
