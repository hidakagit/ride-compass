# 区間ごとの生データ（勾配・向かい風・路面）を、ロードバイク走行の一般的な目安に基づく
# 絶対基準で0-100の「難易度」に変換する。地図上の色分け・候補タブの並び順（overall_
# difficulty）は候補間の相対比較ではなく「客観的にどこが大変か」を示す目的のため
# 絶対基準を採用する。
#
# 各軸の変換パラメータ（breakpoints等）と計算本体は`domain/axis_definitions.py`
# （軸定義データ＋汎用評価関数）が持つ。

from typing import Mapping, NamedTuple

import numpy as np

from app.domain.axis_definitions import evaluate_axes_scalar


class AxisDifficulties(NamedTuple):
    """全評価軸の難易度（axis_idキーの辞書、評価不能な軸はNone）と重み付き合成値。

    キー集合は`AXIS_DEFINITIONS`（domain/axis_definitions.py）が決める（軸の追加は
    定義データの追加だけで反映される）。

    「生値セット→軸別difficulty→composite_difficulty」という組み立てを複数箇所で
    共通化する役割を持つ。呼び出し元は軸別辞書（RouteSegmentDetail用）・compositeのみ
    （EdgeCostResult用）のどちらか一方、または両方を使う。
    """

    axes: dict[str, float | None]
    composite: float | None


def evaluate_axis_difficulties(
    materials: Mapping[str, object], weights: Mapping[str, float]
) -> AxisDifficulties:
    """材料値の辞書と重み辞書から、全軸のdifficultyと合成difficultyをまとめて算出する
    （`AXIS_DEFINITIONS`をループする）。

    `materials`は材料id→解決済みスカラー値（欠損はNone）。各軸が何を参照するかは
    `domain/axis_definitions.py: AXIS_DEFINITIONS`参照。`weights`はaxis_id→合成重み
    （キーが無い軸は重み0として扱う）。

    軸が他の軸のdifficultyをmaterialとして参照できる（内部軸→公開軸の
    階層構造）ため、依存先を先に評価し結果をmaterialsへ混ぜ込みながら進める
    （`domain/axis_definitions.py: evaluate_axes_scalar`が
    `compute_edge_axis_scores`/`axis_inspector_breakdown`[domain/evaluation.py]と
    共有する実装）。内部軸（is_published=False）は実装詳細のため、返り値のaxesには
    含めない。
    """
    axes, _ = evaluate_axes_scalar(materials)
    composite = composite_difficulty(
        [(axes[axis_id], weights.get(axis_id, 0.0)) for axis_id in axes]
    )
    return AxisDifficulties(axes=axes, composite=composite)


def composite_difficulty(scored_weights: list[tuple[float | None, float]]) -> float | None:
    """(スコア, 重み)のリストから加重平均を求める。Noneのスコアは除外し残りの重みで再正規化する。
    1つも有効なスコアが無ければNone。"""
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
