# 区間ごとの生データ（勾配・向かい風・路面）を、ロードバイク走行の一般的な目安に基づく
# 絶対基準で0-100の「難易度」に変換する。Step8のtotal_score（候補集合内の相対評価）とは異なり、
# 地図上の色分けは候補間の比較ではなく「客観的にどこが大変か」を示す目的のため絶対基準を採用する。

from typing import NamedTuple

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


class AxisDifficulties(NamedTuple):
    """4軸（勾配・向かい風・路面・停止密度）の難易度と、重み付き合成値。

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
    composite: float | None


def evaluate_axis_difficulties(
    gradient_percent: float | None,
    wind_penalty: float | None,
    road_surface_good: bool | None,
    stop_count_per_km: float | None,
    elevation_weight: float,
    wind_weight: float,
    road_weight: float,
    stop_weight: float,
) -> AxisDifficulties:
    """4軸の生値と重みから、軸別difficultyと合成difficultyをまとめて算出する。

    RoutePreference型（domain/evaluation.py）をここで受け取らないのは、evaluation.pyが
    本モジュールへ依存しているため（循環import回避）。重みは呼び出し元が
    `preference.elevation_weight`等をそのまま渡す。
    """
    elevation = gradient_difficulty(gradient_percent)
    wind = wind_difficulty(wind_penalty)
    road = road_difficulty(road_surface_good)
    stop = stop_difficulty(stop_count_per_km)
    composite = composite_difficulty(
        [
            (elevation, elevation_weight),
            (wind, wind_weight),
            (road, road_weight),
            (stop, stop_weight),
        ]
    )
    return AxisDifficulties(elevation=elevation, wind=wind, road=road, stop=stop, composite=composite)


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
