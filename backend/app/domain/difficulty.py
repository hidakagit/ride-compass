# 区間ごとの生データ（勾配・向かい風・路面）を、ロードバイク走行の一般的な目安に基づく
# 絶対基準で0-100の「難易度」に変換する。Step8のtotal_score（候補集合内の相対評価）とは異なり、
# 地図上の色分けは候補間の比較ではなく「客観的にどこが大変か」を示す目的のため絶対基準を採用する。
#
# 改善計画T221 Stage B/C: 各軸の変換パラメータ（breakpoints等）と計算本体は
# `domain/axis_definitions.py`（軸定義データ＋汎用評価関数）へ移した。本モジュールの
# `*_difficulty`関数は、既存呼び出し元（区間表示ビルダー・区間インスペクタ・テスト）向けの
# 外部シグネチャ互換ラッパとして残す（Noneガード・負値ガードという「入力の防御」だけを
# ここで担い、変換自体は軸定義へ委譲する）。配列版（旧`*_difficulty_array`）は
# `evaluate_axis_array`（同一定義から導出）へ置き換えたため削除した。

from typing import Mapping, NamedTuple

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    evaluate_axis_scalar,
)


def gradient_difficulty(gradient_percent: float | None) -> float | None:
    if gradient_percent is None:
        return None
    return evaluate_axis_scalar(AXIS_DEFINITIONS["gradient"], {"gradient_percent": gradient_percent})


def wind_difficulty(wind_penalty: float | None) -> float | None:
    """wind_penaltyは符号付き（正=向かい風、負=追い風）。追い風・無風は難易度0、向かい風が強いほど増加。"""
    if wind_penalty is None:
        return None
    return evaluate_axis_scalar(AXIS_DEFINITIONS["wind"], {"wind_penalty": wind_penalty})


def road_difficulty(is_good_surface: bool | None) -> float | None:
    if is_good_surface is None:
        return None
    return evaluate_axis_scalar(AXIS_DEFINITIONS["surface_q"], {"surface_good": is_good_surface})


def stop_difficulty(
    stop_count_per_km: float | None, intersection_count_per_km: float | None = None
) -> float | None:
    """信号・横断歩道・一時停止・踏切の合計密度(回/km)に、次数3以上のタグなし交差点の
    密度を低い重み（`axis_definitions.UNSIGNALED_INTERSECTION_WEIGHT`）で加算した値を
    難易度へ変換する（改善計画T149で交差点密度の独立軸を廃止しここへ吸収）。

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
    return evaluate_axis_scalar(
        AXIS_DEFINITIONS["stop_density"],
        {"stop_count_per_km": stop_count_per_km, "intersection_count_per_km": intersection_count_per_km},
    )


def car_stress_difficulty(car_stress_level: int | None) -> float | None:
    """車ストレス(1-5、domain/traffic.py: car_stress_level)を難易度へ変換する。
    レベルが高いほど走りにくいため単調増加。判定不能（未知のhighway等）はNone。"""
    if car_stress_level is None:
        return None
    return evaluate_axis_scalar(AXIS_DEFINITIONS["car_stress"], {"car_stress_level": car_stress_level})


def accident_difficulty(accident_count_per_km_year: float | None) -> float | None:
    """事故密度(件/(km・年)、domain/accident.py: distance_weighted_accident_density)を
    難易度へ変換する。密度が高いほど走りにくいため単調増加。データ無し（Noneまたは負値）はNone。
    外部静的データソース T50残作業（8軸目）。"""
    if accident_count_per_km_year is None or accident_count_per_km_year < 0:
        return None
    return evaluate_axis_scalar(
        AXIS_DEFINITIONS["accident"], {"accident_count_per_km_year": accident_count_per_km_year}
    )


class AxisDifficulties(NamedTuple):
    """全評価軸の難易度（axis_idキーの辞書、評価不能な軸はNone）と重み付き合成値。

    改善計画T221 Stage B: 旧実装は軸ごとの固定フィールド（elevation/wind/road/...）を
    持つNamedTupleで、軸の追加・削除のたびにフィールドと呼び出し元の展開を書き換える
    必要があった（T138/T139/T149/T150の軸再編のたびに本クラスも改修されてきた経緯は
    git履歴参照）。axis_idキーの辞書へ一般化し、キー集合は`AXIS_DEFINITIONS`
    （domain/axis_definitions.py）が決める（軸の追加は定義データの追加だけで反映される）。

    「生値セット→軸別difficulty→composite_difficulty」という同一の組み立てが
    複数箇所に重複していたための共通化（改善計画T43）という役割は変わらない。
    呼び出し元は軸別辞書（RouteSegmentDetail用）・compositeのみ（EdgeCostResult用）の
    どちらか一方、または両方を使う。
    """

    axes: dict[str, float | None]
    composite: float | None


def evaluate_axis_difficulties(
    materials: Mapping[str, object], weights: Mapping[str, float]
) -> AxisDifficulties:
    """材料値の辞書と重み辞書から、全軸のdifficultyと合成difficultyをまとめて算出する
    （改善計画T221 Stage B/C: 軸ごとに1行ずつハードコードされた旧実装を、
    `AXIS_DEFINITIONS`をループする薄い関数へ置き換えた）。

    `materials`は材料id→解決済みスカラー値（欠損はNone）。各軸が何を参照するかは
    `domain/axis_definitions.py: AXIS_DEFINITIONS`参照。`weights`はaxis_id→合成重み
    （キーが無い軸は重み0として扱う）。
    """
    axes = {
        axis_id: evaluate_axis_scalar(definition, materials)
        for axis_id, definition in AXIS_DEFINITIONS.items()
    }
    composite = composite_difficulty(
        [(axes[axis_id], weights.get(axis_id, 0.0)) for axis_id in AXIS_DEFINITIONS]
    )
    return AxisDifficulties(axes=axes, composite=composite)


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
