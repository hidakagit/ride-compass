# 区間ごとの生データ（勾配・向かい風・路面）を、ロードバイク走行の一般的な目安に基づく
# 絶対基準で0-100の「難易度」に変換する。Step8のtotal_score（候補集合内の相対評価）とは異なり、
# 地図上の色分けは候補間の比較ではなく「客観的にどこが大変か」を示す目的のため絶対基準を採用する。

from typing import NamedTuple

from app.domain.traffic import BicycleInfraClass

# 勾配(%)の目安: 0-3%易しい、3-6%普通、6-9%大変、9%以上激坂
_GRADIENT_BREAKPOINTS = [(0.0, 0.0), (3.0, 25.0), (6.0, 50.0), (9.0, 75.0), (15.0, 100.0)]

# 向かい風の目安: 0m/s(無風)〜8m/s(強い向かい風)で0→100
_WIND_MIN_MS = 0.0
_WIND_MAX_MS = 8.0

# 路面: 舗装路は易しい、非舗装は大変（domain/road.pyのclassify_osm_surfaceと基準を統一）
_ROAD_EASY_SCORE = 0.0
_ROAD_HARD_SCORE = 80.0

# 停止密度(信号・横断歩道・一時停止・踏切の合計回数/km)の目安: 0回/kmが最も易しく、
# 4回/km(250mに1回)を最大値とする。静的道路属性P1、スコアの本格チューニングはP2据え置き
# （docs/static-road-attributes-plan.md §3）のため暫定値。
_STOP_DENSITY_MAX_PER_KM = 4.0
_STOP_DENSITY_HARD_SCORE = 100.0

# 交通ストレス(1-5、domain/traffic.py: traffic_stress_level)の目安: 1が最も易しく5が最も大変。
# 静的道路属性P1残り、暫定値（本格チューニングはP2据え置き）。上限は改善計画（交通ストレス
# 5段階化）で4→5へ拡張済み。
_TRAFFIC_STRESS_MIN_LEVEL = 1
_TRAFFIC_STRESS_MAX_LEVEL = 5

# 自転車インフラ分類(domain/traffic.py: BicycleInfraClass)の目安: 分離自転車道が最も易しく、
# 自転車通行禁止が最も大変。unknownは評価しない（None）。静的道路属性P1残り、暫定値。
_BICYCLE_INFRA_DIFFICULTY_SCORES: dict[str, float] = {
    "separated": 0.0,
    "lane": 20.0,
    "shared_busway": 40.0,
    "shared_pedestrian": 50.0,
    "roadway": 80.0,
    "prohibited": 100.0,
}

# 交差点密度(次数3以上のNodeの合計回数/km)の目安: 0回/kmが最も易しく、2回/km(500mに1回)を
# 最大値とする。停止密度（信号・横断歩道等）よりも出現頻度が低い想定のため上限を低く取る。
# 静的道路属性P1残り、暫定値（本格チューニングはP2据え置き）。
_INTERSECTION_DENSITY_MAX_PER_KM = 2.0
_INTERSECTION_DENSITY_HARD_SCORE = 100.0

# 事故密度(件/(km・年)、domain/accident.py: distance_weighted_accident_density)の目安:
# 0件/(km・年)が最も易しく、0.5件/(km・年)を最大値とする。関東7都県3年分で303,455件
# （道路延長を考えるとkm・年あたり平均は1を大きく下回る水準）という実測規模を踏まえた
# 暫定値（本格チューニングはP2据え置き）。外部静的データソース T50残作業。
_ACCIDENT_DENSITY_MAX_PER_KM_YEAR = 0.5
_ACCIDENT_DENSITY_HARD_SCORE = 100.0

# 安全度(1-4、domain/safety.py: safety_level)の目安: 1が最も安全(易しい)で4が最も危険(大変)。
# 交通ストレスと同じ1-4→0-100の区分線形（改善計画: 安全度レシピ、9軸目）。
_SAFETY_MIN_LEVEL = 1
_SAFETY_MAX_LEVEL = 4


def _piecewise_linear(value: float, breakpoints: list[tuple[float, float]]) -> float:
    if value <= breakpoints[0][0]:
        return breakpoints[0][1]
    if value >= breakpoints[-1][0]:
        return breakpoints[-1][1]

    for (x0, y0), (x1, y1) in zip(breakpoints, breakpoints[1:]):
        if x0 <= value <= x1:
            ratio = (value - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)

    return breakpoints[-1][1]


def gradient_difficulty(gradient_percent: float | None) -> float | None:
    if gradient_percent is None:
        return None
    return round(_piecewise_linear(abs(gradient_percent), _GRADIENT_BREAKPOINTS), 1)


def wind_difficulty(wind_penalty: float | None) -> float | None:
    """wind_penaltyは符号付き（正=向かい風、負=追い風）。追い風・無風は難易度0、向かい風が強いほど増加。"""
    if wind_penalty is None:
        return None
    clamped = max(_WIND_MIN_MS, min(wind_penalty, _WIND_MAX_MS))
    return round((clamped - _WIND_MIN_MS) / (_WIND_MAX_MS - _WIND_MIN_MS) * 100, 1)


def road_difficulty(is_good_surface: bool | None) -> float | None:
    if is_good_surface is None:
        return None
    return _ROAD_EASY_SCORE if is_good_surface else _ROAD_HARD_SCORE


def stop_difficulty(stop_count_per_km: float | None) -> float | None:
    """信号・横断歩道・一時停止・踏切の合計密度(回/km)を難易度へ変換する。
    密度が高いほど停止・減速が多く走りにくいため単調増加。データ無し（Noneまたは
    負値。Edge単位でカウント不能なケースは呼び出し元がNoneを渡す）はNone。"""
    if stop_count_per_km is None or stop_count_per_km < 0:
        return None
    clamped = min(stop_count_per_km, _STOP_DENSITY_MAX_PER_KM)
    return round(clamped / _STOP_DENSITY_MAX_PER_KM * _STOP_DENSITY_HARD_SCORE, 1)


def traffic_stress_difficulty(traffic_stress_level: int | None) -> float | None:
    """交通ストレス(1-5、domain/traffic.py: traffic_stress_level)を難易度へ変換する。
    レベルが高いほど走りにくいため単調増加。判定不能（未知のhighway等）はNone。"""
    if traffic_stress_level is None:
        return None
    return round(
        _piecewise_linear(
            traffic_stress_level, [(_TRAFFIC_STRESS_MIN_LEVEL, 0.0), (_TRAFFIC_STRESS_MAX_LEVEL, 100.0)]
        ),
        1,
    )


def bicycle_infra_difficulty(bicycle_infra: BicycleInfraClass | None) -> float | None:
    """自転車インフラ分類(domain/traffic.py: classify_bicycle_infrastructure)を難易度へ
    変換する。unknown・未取得はNone（評価しない。road_difficulty等と同じ「不明は無視」方針）。"""
    if bicycle_infra is None:
        return None
    return _BICYCLE_INFRA_DIFFICULTY_SCORES.get(bicycle_infra)


def intersection_difficulty(intersection_count_per_km: float | None) -> float | None:
    """交差点密度(次数3以上のNodeの合計回数/km)を難易度へ変換する。密度が高いほど
    停止・減速・注意力の消費が増えるため単調増加。データ無し（Noneまたは負値）はNone。"""
    if intersection_count_per_km is None or intersection_count_per_km < 0:
        return None
    clamped = min(intersection_count_per_km, _INTERSECTION_DENSITY_MAX_PER_KM)
    return round(clamped / _INTERSECTION_DENSITY_MAX_PER_KM * _INTERSECTION_DENSITY_HARD_SCORE, 1)


def accident_difficulty(accident_count_per_km_year: float | None) -> float | None:
    """事故密度(件/(km・年)、domain/accident.py: distance_weighted_accident_density)を
    難易度へ変換する。密度が高いほど走りにくいため単調増加。データ無し（Noneまたは負値）はNone。
    外部静的データソース T50残作業（8軸目）。"""
    if accident_count_per_km_year is None or accident_count_per_km_year < 0:
        return None
    clamped = min(accident_count_per_km_year, _ACCIDENT_DENSITY_MAX_PER_KM_YEAR)
    return round(clamped / _ACCIDENT_DENSITY_MAX_PER_KM_YEAR * _ACCIDENT_DENSITY_HARD_SCORE, 1)


def safety_difficulty(safety_level_value: int | None) -> float | None:
    """安全度(1-4、domain/safety.py: safety_level)を難易度へ変換する。
    レベルが高いほど危険＝走りにくいため単調増加。判定不能（未知のhighway等）はNone。
    traffic_stress_difficultyと同じ区分線形。"""
    if safety_level_value is None:
        return None
    return round(
        _piecewise_linear(safety_level_value, [(_SAFETY_MIN_LEVEL, 0.0), (_SAFETY_MAX_LEVEL, 100.0)]),
        1,
    )


class AxisDifficulties(NamedTuple):
    """9軸（勾配・向かい風・路面・停止密度・交通ストレス・自転車インフラ・交差点密度・
    事故密度・安全度）の難易度と、重み付き合成値。

    「生値セット→軸別difficulty→composite_difficulty」という同一の組み立てが
    OpenRouteServiceEngine._build_segment_details / RoadGraphEngine._build_segment_details /
    domain/evaluation.compute_edge_costの3箇所に重複していたための共通化（改善計画T43）。
    呼び出し元は軸別フィールド（RouteSegmentDetail用）・compositeのみ（EdgeCostResult用）の
    どちらか一方、または両方を使う。
    """

    elevation: float | None
    wind: float | None
    road: float | None
    stop: float | None
    traffic: float | None
    infra: float | None
    intersection: float | None
    accident: float | None
    safety: float | None
    composite: float | None


def evaluate_axis_difficulties(
    gradient_percent: float | None,
    wind_penalty: float | None,
    road_surface_good: bool | None,
    stop_count_per_km: float | None,
    traffic_stress_level_value: int | None,
    bicycle_infra: BicycleInfraClass | None,
    intersection_count_per_km: float | None,
    accident_count_per_km_year: float | None,
    safety_level_value: int | None,
    elevation_weight: float,
    wind_weight: float,
    road_weight: float,
    stop_weight: float,
    traffic_weight: float,
    infra_weight: float,
    intersection_weight: float,
    accident_weight: float,
    safety_weight: float,
) -> AxisDifficulties:
    """9軸の生値と重みから、軸別difficultyと合成difficultyをまとめて算出する。

    RoutePreference型（domain/evaluation.py）をここで受け取らないのは、evaluation.pyが
    本モジュールへ依存しているため（循環import回避）。重みは呼び出し元が
    `preference.elevation_weight`等をそのまま渡す。traffic_stress_level_valueの引数名が
    `traffic_stress_level`（関数名）と衝突するため`_value`サフィックスを付けている
    （safety_level_valueも同様）。
    """
    elevation = gradient_difficulty(gradient_percent)
    wind = wind_difficulty(wind_penalty)
    road = road_difficulty(road_surface_good)
    stop = stop_difficulty(stop_count_per_km)
    traffic = traffic_stress_difficulty(traffic_stress_level_value)
    infra = bicycle_infra_difficulty(bicycle_infra)
    intersection = intersection_difficulty(intersection_count_per_km)
    accident = accident_difficulty(accident_count_per_km_year)
    safety = safety_difficulty(safety_level_value)
    composite = composite_difficulty(
        [
            (elevation, elevation_weight),
            (wind, wind_weight),
            (road, road_weight),
            (stop, stop_weight),
            (traffic, traffic_weight),
            (infra, infra_weight),
            (intersection, intersection_weight),
            (accident, accident_weight),
            (safety, safety_weight),
        ]
    )
    return AxisDifficulties(
        elevation=elevation,
        wind=wind,
        road=road,
        stop=stop,
        traffic=traffic,
        infra=infra,
        intersection=intersection,
        accident=accident,
        safety=safety,
        composite=composite,
    )


def composite_difficulty(scored_weights: list[tuple[float | None, float]]) -> float | None:
    """(スコア, 重み)のリストから加重平均を求める。Noneのスコアは除外し残りの重みで再正規化する
    （RouteScorerと同じ考え方）。1つも有効なスコアが無ければNone。"""
    available = [(score, weight) for score, weight in scored_weights if score is not None]
    if not available:
        return None

    weight_sum = sum(weight for _, weight in available)
    if weight_sum == 0:
        return None

    total = sum(score * weight for score, weight in available) / weight_sum
    return round(total, 1)


def distance_weighted_difficulty(segments: list[tuple[float | None, float]]) -> float | None:
    """(区間difficulty, 区間distance_km)のリストから距離加重平均を求める。ルート単位の
    絶対基準集約値（研究インターフェース改善 §10-7）。difficultyがNoneの区間は除外し
    残りの距離で再正規化する（composite_difficultyと同じ考え方）。1つも有効な区間が
    無い、または距離の合計が0ならNone。"""
    available = [(difficulty, distance) for difficulty, distance in segments if difficulty is not None]
    if not available:
        return None

    distance_sum = sum(distance for _, distance in available)
    if distance_sum <= 0:
        return None

    total = sum(difficulty * distance for difficulty, distance in available) / distance_sum
    return round(total, 1)
