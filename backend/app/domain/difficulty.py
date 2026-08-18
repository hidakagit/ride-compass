# 区間ごとの生データ（勾配・向かい風・路面）を、ロードバイク走行の一般的な目安に基づく
# 絶対基準で0-100の「難易度」に変換する。Step8のtotal_score（候補集合内の相対評価）とは異なり、
# 地図上の色分けは候補間の比較ではなく「客観的にどこが大変か」を示す目的のため絶対基準を採用する。

from typing import NamedTuple

from app.domain.night import night_difficulty

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

# 改善計画T149（設計プロンプト改訂2026-08-18「現行9軸からの帰属先」）: 交差点密度は
# 単独軸を持たず、タグなし交差点(次数3以上のroad_node、信号等のタグが付いていない
# もの)として、信号・横断歩道・一時停止・踏切と同じstop_density軸へ低い重みで吸収する。
# 「立ち止まる／減速する頻度」という同じ性質の指標であり、車ストレス軸（走行中の車との
# 近接ストレス）とは質的に異なるためstop_density側に寄せる、という設計プロンプトの判断。
# 重みはsignal等のstop_poi(重み1.0相当)に対する相対値（設計プロンプトのaxis_params例
# `stop_density.weights.unsignaled_intersection: 0.3`）。現行のstop_poiカウント自体が
# 種別ごとの重み付けを実装していない（全種別を等しく1件としてカウント、暫定実装）ため、
# 交差点もこの水準に合わせた単純な係数掛けで組み込む（種別ごとの重み付けの本格実装は
# P2据え置き、上記stop_density本体の暫定値と同じ扱い）。
_UNSIGNALED_INTERSECTION_WEIGHT = 0.3

# 車ストレス(1-5、domain/traffic.py: car_stress_level)の目安: 1が最も易しく5が最も大変。
# 静的道路属性P1残り、暫定値（本格チューニングはP2据え置き）。上限は改善計画（車ストレス
# 5段階化）で4→5へ拡張済み。
_CAR_STRESS_MIN_LEVEL = 1
_CAR_STRESS_MAX_LEVEL = 5

# 事故密度(件/(km・年)、domain/accident.py: distance_weighted_accident_density)の目安:
# 0件/(km・年)が最も易しく、0.5件/(km・年)を最大値とする。関東7都県3年分で303,455件
# （道路延長を考えるとkm・年あたり平均は1を大きく下回る水準）という実測規模を踏まえた
# 暫定値（本格チューニングはP2据え置き）。外部静的データソース T50残作業。
_ACCIDENT_DENSITY_MAX_PER_KM_YEAR = 0.5
_ACCIDENT_DENSITY_HARD_SCORE = 100.0

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


def stop_difficulty(
    stop_count_per_km: float | None, intersection_count_per_km: float | None = None
) -> float | None:
    """信号・横断歩道・一時停止・踏切の合計密度(回/km)に、次数3以上のタグなし交差点の
    密度を低い重み（`_UNSIGNALED_INTERSECTION_WEIGHT`）で加算した値を難易度へ変換する
    （改善計画T149で交差点密度の独立軸を廃止しここへ吸収）。密度が高いほど停止・減速・
    注意力の消費が多く走りにくいため単調増加。

    `stop_count_per_km`がNone・負値ならNone（Edge単位でカウント不能なケースは呼び出し元が
    Noneを渡す、他のdifficulty関数と同じ方針）。`intersection_count_per_km`は省略可
    （None＝交差点データ未取得、寄与0として扱う。stop_count_per_km自体はデータありのまま
    評価する非対称な扱い＝信号等のデータが主、交差点データは補助という位置づけ）。
    負のintersection_count_per_kmが渡された場合はNone（不正データとして評価しない）。
    """
    if stop_count_per_km is None or stop_count_per_km < 0:
        return None
    if intersection_count_per_km is not None and intersection_count_per_km < 0:
        return None
    combined_per_km = stop_count_per_km + (intersection_count_per_km or 0.0) * _UNSIGNALED_INTERSECTION_WEIGHT
    clamped = min(combined_per_km, _STOP_DENSITY_MAX_PER_KM)
    return round(clamped / _STOP_DENSITY_MAX_PER_KM * _STOP_DENSITY_HARD_SCORE, 1)


def car_stress_difficulty(car_stress_level: int | None) -> float | None:
    """車ストレス(1-5、domain/traffic.py: car_stress_level)を難易度へ変換する。
    レベルが高いほど走りにくいため単調増加。判定不能（未知のhighway等）はNone。"""
    if car_stress_level is None:
        return None
    return round(
        _piecewise_linear(
            car_stress_level, [(_CAR_STRESS_MIN_LEVEL, 0.0), (_CAR_STRESS_MAX_LEVEL, 100.0)]
        ),
        1,
    )


def accident_difficulty(accident_count_per_km_year: float | None) -> float | None:
    """事故密度(件/(km・年)、domain/accident.py: distance_weighted_accident_density)を
    難易度へ変換する。密度が高いほど走りにくいため単調増加。データ無し（Noneまたは負値）はNone。
    外部静的データソース T50残作業（8軸目）。"""
    if accident_count_per_km_year is None or accident_count_per_km_year < 0:
        return None
    clamped = min(accident_count_per_km_year, _ACCIDENT_DENSITY_MAX_PER_KM_YEAR)
    return round(clamped / _ACCIDENT_DENSITY_MAX_PER_KM_YEAR * _ACCIDENT_DENSITY_HARD_SCORE, 1)


class AxisDifficulties(NamedTuple):
    """7軸（勾配・向かい風・路面・停止密度・車ストレス・事故密度・夜間）の難易度と、
    重み付き合成値。

    改善計画T138（設計プロンプト「評価システムの層構造再設計」）で、自転車インフラ
    （旧`infra`）を独立軸から廃止し車ストレス（`car_stress`、旧「交通ストレス」）へ統合した
    （車ストレス側の`car_stress_level`が`car_closeness()`のcycleway補正で既に
    自転車インフラの情報を反映しているため、独立軸として同じ情報を二重に持たない）。
    続くT139で、安全度軸（旧`safety`、highway/cycleway等由来の部分はT138でcar_stress側へ
    吸収済み）を廃止し、街灯・トンネル由来の部分を`night`軸として独立させた（事故実績は
    既存の`accident`軸のまま変更なし）。続くT149で、交差点密度（旧`intersection`）を
    独立軸から廃止し停止密度（`stop`、`stop_difficulty`が内部でタグなし交差点を低い重みで
    加算）へ統合した（8軸→7軸）。フィールド名`traffic`は改善計画T150で`car_stress`へ改称
    （`domain/traffic.py`の呼称も同タスクで`car_stress`系へ統一済み）。

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
    car_stress: float | None
    accident: float | None
    night: float | None
    composite: float | None


def evaluate_axis_difficulties(
    gradient_percent: float | None,
    wind_penalty: float | None,
    road_surface_good: bool | None,
    stop_count_per_km: float | None,
    car_stress_level_value: int | None,
    intersection_count_per_km: float | None,
    accident_count_per_km_year: float | None,
    night_tags: dict[str, str] | None,
    elevation_weight: float,
    wind_weight: float,
    road_weight: float,
    stop_weight: float,
    car_stress_weight: float,
    accident_weight: float,
    night_weight: float,
) -> AxisDifficulties:
    """7軸の生値と重みから、軸別difficultyと合成difficultyをまとめて算出する
    （改善計画T138で自転車インフラを独立軸から車ストレスへ統合、T139で安全度を廃止し
    夜間軸へ置き換え、T149で交差点密度を停止密度へ統合、9軸→7軸）。

    RoutePreference型（domain/evaluation.py）をここで受け取らないのは、evaluation.pyが
    本モジュールへ依存しているため（循環import回避）。重みは呼び出し元が
    `preference.elevation_weight`等をそのまま渡す。car_stress_level_valueの引数名が
    `car_stress_level`（関数名）と衝突するため`_value`サフィックスを付けている。
    `intersection_count_per_km`は独立軸の重みを持たず`stop_difficulty`へ渡すだけの
    補助入力（改善計画T149）。`night_tags`は`night_difficulty`（domain/night.py）へ
    そのまま渡す材料タグ（他軸のように事前解決した数値/bool単体ではなくtagsのまま渡すのは、
    night_difficulty自体がlit/tunnelの2タグを内部で読むため。way_tags未取得ならNone）。
    """
    elevation = gradient_difficulty(gradient_percent)
    wind = wind_difficulty(wind_penalty)
    road = road_difficulty(road_surface_good)
    stop = stop_difficulty(stop_count_per_km, intersection_count_per_km)
    car_stress = car_stress_difficulty(car_stress_level_value)
    accident = accident_difficulty(accident_count_per_km_year)
    night = night_difficulty(night_tags)
    composite = composite_difficulty(
        [
            (elevation, elevation_weight),
            (wind, wind_weight),
            (road, road_weight),
            (stop, stop_weight),
            (car_stress, car_stress_weight),
            (accident, accident_weight),
            (night, night_weight),
        ]
    )
    return AxisDifficulties(
        elevation=elevation,
        wind=wind,
        road=road,
        stop=stop,
        car_stress=car_stress,
        accident=accident,
        night=night,
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
