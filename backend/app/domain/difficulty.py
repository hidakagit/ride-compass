# 区間ごとの生データ（勾配・向かい風・路面）を、ロードバイク走行の一般的な目安に基づく
# 絶対基準で0-100の「難易度」に変換する。地図上の色分け・候補タブの並び順（overall_
# difficulty）は候補間の相対比較ではなく「客観的にどこが大変か」を示す目的のため
# 絶対基準を採用する。
#
# 各軸の変換パラメータ（breakpoints等）と計算本体は`domain/axis_definitions.py`
# （軸定義データ＋汎用評価関数）が持つ。


import math
from collections.abc import Iterable, Mapping

import numpy as np

from app.domain.axis_templates import round1_array


def weight_share(weight: float, other_weights: Iterable[float]) -> float | None:
    """重み`weight`の軸を、ほかの軸（`other_weights`）と並べて合成したときに占める割合
    （`composite_difficulty_array`が重みの合計で割るのと同じ分母）。合計が0以下ならNone。"""
    total = weight + sum(other_weights)
    return None if total <= 0 else weight / total


def _neumaier_accumulate(terms: list[np.ndarray]) -> np.ndarray:
    """`terms`を先頭から順に加算する（Neumaier補償加算、Kahan加算の改良版）。

    丸め誤差を打ち消す補正項を別に積算し、最後に本体へ足し込む。単純な逐次`+=`では
    誤差が項の数だけ積み上がり、真の値がちょうど.X5境界にある合成値の最終丸めが、誤差の
    向きしだいで別の側へ倒れる。n件分をまとめて配列演算で行い、Edge数万件規模でも
    Pythonループを使わない。
    """
    total = np.zeros_like(terms[0], dtype=float)
    compensation = np.zeros_like(terms[0], dtype=float)
    for term in terms:
        t = total + term
        correction = np.where(np.abs(total) >= np.abs(term), (total - t) + term, (term - t) + total)
        compensation += correction
        total = t
    return total + compensation


def _axis_terms(
    axis_arrays: Mapping[str, np.ndarray], weights: Mapping[str, float]
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """軸ごとの「重み付きスコアの項」「重みの項」。

    データ欠損（NaN）の軸はその区間だけ項を0にする＝和から外す（「データ無しは除外し
    残りの重みで再正規化」）。**この式を2箇所に書かない**——先に和だけ求める経路と合成の
    本体で式がずれると、先に求めた和を使い回した合成だけが静かに食い違う。
    """
    score_terms: list[np.ndarray] = []
    weight_terms: list[np.ndarray] = []
    for axis_id, arr in axis_arrays.items():
        weight = weights.get(axis_id, 0.0)
        valid = ~np.isnan(arr)
        score_terms.append(np.where(valid, arr * weight, 0.0))
        weight_terms.append(np.where(valid, weight, 0.0))
    return score_terms, weight_terms


def axis_weighted_sums(
    axis_arrays: Mapping[str, np.ndarray], weights: Mapping[str, float], length: int
) -> tuple[np.ndarray, np.ndarray]:
    """`composite_difficulty_array`の`static_sums`へ渡す`(重み付きスコアの和, 重みの和)`。

    データ欠損（NaN）の軸はその区間だけ和から外す（項の作り方は`_axis_terms`が単一の情報源）。
    """
    if not axis_arrays:
        return np.zeros(length), np.zeros(length)
    score_terms, weight_terms = _axis_terms(axis_arrays, weights)
    return _neumaier_accumulate(score_terms), _neumaier_accumulate(weight_terms)


def composite_difficulty_array(
    axis_arrays: Mapping[str, np.ndarray],
    weights: Mapping[str, float],
    length: int,
    static_sums: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """軸別の得点の配列から、区間ごとの合成difficulty（重み付き平均、小数1桁）と、その分母の
    「データのある軸の重みの合計」を返す。**合成の式はここ1本**。

    データ欠損（NaN）の軸はその区間だけ分母からも外して残りの重みで割り直し、重みの合計が0の
    区間はNaN。`static_sums`は`axis_arrays`に**含めなかった**軸ぶんの
    `(重み付きスコアの和, 重みの和)`（`axis_weighted_sums`）。
    """
    dynamic_scores, dynamic_weights = _axis_terms(axis_arrays, weights)
    score_terms = ([] if static_sums is None else [static_sums[0]]) + dynamic_scores
    weight_terms = ([] if static_sums is None else [static_sums[1]]) + dynamic_weights
    if score_terms:
        weighted_scores = _neumaier_accumulate(score_terms)
        weight_sums = _neumaier_accumulate(weight_terms)
    else:
        weighted_scores = np.zeros(length)
        weight_sums = np.zeros(length)
    with np.errstate(invalid="ignore", divide="ignore"):
        composite = weighted_scores / weight_sums
    composite = np.where(weight_sums == 0, np.nan, composite)
    return round1_array(composite), weight_sums


def axis_contributions_at_row(
    axis_arrays: Mapping[str, np.ndarray],
    weights: Mapping[str, float],
    weight_sums: np.ndarray,
    row: int,
) -> dict[str, float]:
    """1区間ぶんの軸別寄与度（データのある軸の`値 × 重み ÷ weight_sums[row]`）。

    全区間ぶんは作らない——読むのは経路上の数百区間だけのため。全軸を足すと丸め前の
    合成difficultyに一致する（合成とその内訳を食い違わせないための式）。区間の値は丸めない。
    """
    total = float(weight_sums[row])
    if total == 0 or math.isnan(total):
        return {}
    values: dict[str, float] = {}
    for axis_id, arr in axis_arrays.items():
        value = arr[row]
        if math.isnan(value):
            continue
        values[axis_id] = float(value) * weights.get(axis_id, 0.0) / total
    return values


def composite_difficulty(
    scores: Mapping[str, float | None], weights: Mapping[str, float]
) -> tuple[float | None, dict[str, float | None]]:
    """1区間ぶんの軸の得点（欠損=None）から、合成difficultyと軸ごとの寄与度（小数1桁）を返す。
    計算は`composite_difficulty_array`・`axis_contributions_at_row`を長さ1で通す。

    寄与度は`scores`と同じキーで、得点の無い軸（分母にも入らない）はNone。合成が求まらない
    （得点のある軸が無い・重みの合計が0）ときは合成も寄与度もすべてNone。各寄与度を丸めるため、
    合計は合成と丸め誤差のぶんだけずれうる。
    """
    axis_arrays = {
        axis_id: np.array([np.nan if score is None else score], dtype=float) for axis_id, score in scores.items()
    }
    composite, weight_sums = composite_difficulty_array(axis_arrays, weights, 1)
    at_row = axis_contributions_at_row(axis_arrays, weights, weight_sums, 0)
    value = float(composite[0])
    contributions = {axis_id: None if axis_id not in at_row else round(at_row[axis_id], 1) for axis_id in scores}
    return (None if math.isnan(value) else value), contributions


def weighted_mean_by_distance(segments: list[tuple[float | None, float]]) -> float | None:
    """(区間の値, 区間distance_km)のリストから距離加重平均を求める（**丸めない**）。

    値がNoneの区間は除外し残りの距離で再正規化する（composite_difficultyと同じ考え方）。
    1つも有効な区間が無い、または距離の合計が0ならNone。

    丸めを含まないのは、difficulty（0〜100）と物理量の生値（スケールが軸ごとに違う）で
    必要な粒度が違うため——固定の小数桁で丸めると桁の小さい軸で値がまるごと潰れる。
    丸め方は呼び出し側が決める。
    """
    available = [(value, distance) for value, distance in segments if value is not None]
    if not available:
        return None

    distance_sum = sum(distance for _, distance in available)
    if distance_sum <= 0:
        return None

    return sum(value * distance for value, distance in available) / distance_sum


def distance_weighted_difficulty(segments: list[tuple[float | None, float]]) -> float | None:
    """(区間difficulty, 区間distance_km)のリストから距離加重平均を求める。
    0〜100のdifficulty向けに小数1桁へ丸める。"""
    mean = weighted_mean_by_distance(segments)
    return None if mean is None else round(mean, 1)


def difficulty_load(segments: list[tuple[float | None, float]]) -> float | None:
    """(区間difficulty, 区間distance_km)のリストから難易度の総量を求める。

    距離加重平均（`distance_weighted_difficulty`）が距離で正規化されるのに対し、総量は
    距離が伸びればそのまま増える——「走り切るのにどれだけしんどいか」に近く、遠回りが
    正直に不利に出る。候補の順位付けには使わず、平均と併せて判断材料として示す。

    difficultyがNoneの区間の扱いは平均と一致させる（平均×全区間の距離合計）。区間ごとに
    積分して欠損区間を単純に飛ばすと「データが無い区間が多いほど総量が小さい」ことに
    なり、欠損の多いルートが有利に見えてしまう。平均が出るのは値のある区間の距離の合計が
    正のときだけで、区間の距離は負にならないため、平均が出れば全区間の距離合計も正になる。
    """
    average = distance_weighted_difficulty(segments)
    if average is None:
        return None
    return round(average * sum(distance for _, distance in segments), 1)


def distance_weighted_difficulty_array(difficulty: np.ndarray, distance_m: np.ndarray) -> float | None:
    """`distance_weighted_difficulty`のnumpyベクトル化版。`difficulty`の
    NaN要素は除外し残りの距離で再正規化する。1つも有効な要素が無い、または距離の合計が
    0以下ならNone。呼び出し元は数万〜十数万件規模のEdge配列を想定し、Pythonループを避ける。
    """
    valid = ~np.isnan(difficulty)
    distance_sum = float(distance_m[valid].sum())
    if not valid.any() or distance_sum <= 0:
        return None
    return round(float(np.sum(difficulty[valid] * distance_m[valid]) / distance_sum), 1)
