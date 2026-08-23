"""評価軸の変換ロジックが還元できる4つの汎用テンプレート（改善計画T221 Stage A、T239）。

`docs/decisions/t221-axis-registry.md`の調査で、現行7軸（勾配・向かい風・路面・停止密度・
車ストレス・事故密度・夜間）の一次属性→軸別difficulty(0-100)変換は、実質以下の4パターンに
還元できると判明した。

- **区分線形補間**（`evaluate_breakpoint_linear`）: 勾配・向かい風・停止密度・事故密度が
  該当。両端でクランプする折れ線補間。
- **カテゴリ→定数**（`evaluate_categorical`）: 路面（舗装/非舗装）が該当。
- **フラグ加算**（`evaluate_flag_sum`）: 夜間（街灯なし・トンネル）が該当。
- **レシピ→レベル→区分線形補間**（`evaluate_recipe_then_breakpoint_linear`）: 車ストレスが
  該当。レベル自体の算出（highway別基準値＋各種タグ補正、`domain/recipe.py: car_closeness`・
  `domain/traffic.py: _compute_car_stress`）は軸固有のレシピ判定として引き続きそちらが担い、
  ここでは算出済みレベルを区分線形補間へ渡すだけ（実装は`evaluate_breakpoint_linear`と同一。
  ADRの命名に合わせて別名として提供する）。

各関数はスカラー（Python float/bool/int）とnumpy配列の両方を受け付ける。スカラー入力には
Pythonのfloat/boolを、配列入力には同じ形状のnumpy配列を返す（欠損値はNaNで表現・伝播する）。
`domain/difficulty.py`・`domain/night.py`の各`*_difficulty`関数（1エッジずつ呼ばれる
スカラー経路、Noneガードは呼び出し側が担う）と、`EvaluationService.evaluate_graph`の
ベクトル化された一括経路（改善計画T240）の両方が同じ実装を共有することで、「軸のロジックは
1箇所にまとめる」という設計原則（`docs/complexity-review-2026-08-16.md`）をベクトル化後も
維持する。
"""

from __future__ import annotations

import numpy as np


def evaluate_breakpoint_linear(value, breakpoints: list[tuple[float, float]]):
    """区分線形補間（breakpointsはx昇順の(x, y)組、両端でクランプ）。

    numpyの`np.interp`（既定でx範囲外はfp[0]/fp[-1]にクランプ）をそのまま使う。配列入力で
    NaN（欠損値）が混じる要素は、`np.interp`がNaNを正しく伝播しない（内部の探索がNaNを
    0番目の区間として扱ってしまう）ため、`np.isnan`でマスクして明示的にNaNへ戻す。
    """
    xp = [p[0] for p in breakpoints]
    fp = [p[1] for p in breakpoints]
    if isinstance(value, np.ndarray):
        result = np.interp(value, xp, fp)
        return np.where(np.isnan(value), np.nan, result)
    return float(np.interp(value, xp, fp))


# レシピ→レベル→区分線形補間（car_stress）。レベル計算自体は呼び出し側（軸固有のレシピ判定）
# の責務で、ここに来た時点では既に区分線形補間そのものになっているため実装を共有する。
evaluate_recipe_then_breakpoint_linear = evaluate_breakpoint_linear


def evaluate_categorical(value, mapping: dict, default: float | None = None):
    """カテゴリ値→定数のマッピング。配列入力は要素ごとに`mapping`を適用し、NaN
    （不明値のプレースホルダ）はそのまま伝播する（`mapping`に一致するキーが無い要素は
    `default`、既定Noneなら数値配列の文脈に合わせてNaN）。
    """
    if isinstance(value, np.ndarray):
        fill = np.nan if default is None else float(default)
        result = np.full(value.shape, fill, dtype=float)
        for key, mapped in mapping.items():
            result = np.where(value == key, float(mapped), result)
        return result
    return mapping.get(value, default)


def evaluate_flag_sum(flags_and_points: list[tuple], cap: float | None = None):
    """(フラグ, 加点)の組を合計する。フラグはスカラー（bool）・numpy配列のどちらでもよい
    （リスト内で混在してはならない——呼び出し元は同じ形状で揃えて渡すこと）。
    """
    is_array = any(isinstance(flag, np.ndarray) for flag, _ in flags_and_points)
    if is_array:
        total = sum(np.asarray(flag, dtype=float) * points for flag, points in flags_and_points)
        return np.minimum(total, cap) if cap is not None else total
    total = sum((1.0 if flag else 0.0) * points for flag, points in flags_and_points)
    return min(total, cap) if cap is not None else total


def round1_array(values: np.ndarray) -> np.ndarray:
    """`round(x, 1)`（Python組み込み、2進浮動小数点の実際の値に対する正しい丸め）と
    ビット単位で一致させるための配列版丸め。`np.round`は内部で「×10→rint→÷10」という
    段階を踏むため、その掛け算で丸め誤差が混入し、値がちょうど.X5の境界にあると
    Python組み込みの`round()`と結果が食い違うことがある（実測: 実データのEdgeで
    `np.round`は41.3、`round()`は41.2。`domain/difficulty.py`の配列版4関数・
    `domain/evaluation.py: compute_edge_costs_bulk`の最終丸めの両方で使う共通実装）。
    NaNはNaNのまま返す。
    """
    return np.array([round(float(v), 1) if not np.isnan(v) else np.nan for v in values])
