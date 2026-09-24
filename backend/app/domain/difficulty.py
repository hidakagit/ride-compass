# 区間ごとの生データ（勾配・向かい風・路面）を、ロードバイク走行の一般的な目安に基づく
# 絶対基準で0-100の「難易度」に変換する。地図上の色分け・候補タブの並び順（overall_
# difficulty）は候補間の相対比較ではなく「客観的にどこが大変か」を示す目的のため
# 絶対基準を採用する。
#
# 各軸の変換パラメータ（breakpoints等）と計算本体は`domain/axis_definitions.py`
# （軸定義データ＋汎用評価関数）が持つ。


import numpy as np


def _available_and_weight_sum(
    scored_weights: list[tuple[float | None, float]],
) -> tuple[list[tuple[float, float]], float] | None:
    """合成に使える(スコア, 重み)と、その重みの合計。畳めないときNone。

    **合成と内訳の分母はここだけが決める**——両方が同じ絞り込みと同じ合計を別々に書くと、
    片方だけ変えた瞬間に内訳が合成と桁で食い違う。
    """
    available = [(score, weight) for score, weight in scored_weights if score is not None]
    weight_sum = sum(weight for _, weight in available)
    if not available or weight_sum == 0:
        return None
    return available, weight_sum


def composite_difficulty(scored_weights: list[tuple[float | None, float]]) -> float | None:
    """(スコア, 重み)のリストから加重平均を求める。Noneのスコアは除外し残りの重みで再正規化する。
    1つも有効なスコアが無ければNone。"""
    resolved = _available_and_weight_sum(scored_weights)
    if resolved is None:
        return None
    available, weight_sum = resolved
    total = sum(score * weight for score, weight in available) / weight_sum
    return round(total, 1)


def composite_contributions(scored_weights: list[tuple[float | None, float]]) -> list[float | None]:
    """`composite_difficulty`を軸ごとへ分解した値。

    入力と同じ並び・同じ長さで返す。スコアがNoneの軸（合成の分母にも入らない）はNone。
    合成が算出できない（有効な軸が無い・重みの合計が0）ときは全てNone。

    各値を小数1桁へ丸めるため、合計は合成スコアと丸め誤差のぶんだけずれうる。
    """
    resolved = _available_and_weight_sum(scored_weights)
    if resolved is None:
        return [None for _ in scored_weights]
    weight_sum = resolved[1]
    return [
        None if score is None else round(score * weight / weight_sum, 1)
        for score, weight in scored_weights
    ]


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
