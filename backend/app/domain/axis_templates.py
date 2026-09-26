"""評価軸の変換ロジックが還元できる2つの汎用プリミティブ。

- **連続演算**（`evaluate_breakpoint_linear`）: 材料（または他軸のスコア）を重み付き
  結合し、区分線形カーブ（両端クランプ）でスコア化する（`domain/axis_definitions.py:
  BreakpointLinearShape`docstring参照）。
- **離散演算**（`evaluate_categorical`）: 単一の離散値（bool/カテゴリ文字列）を
  テーブル引きでスコア化する。

「合成」（他軸のスコアを次の軸の入力として使う階層構造）は独立した
プリミティブではなく、連続演算の結合ステップの性質——`terms`の各materialが
材料id・他軸のaxis_idのどちらも区別なく指せることから生じる（`axis_definitions.py:
topological_axis_order`が依存順の評価を担う）。

軸の評価（`axis_definitions.py: evaluate_axis_array`）は配列で呼ぶ（欠損値はNaNで表現・伝播する）。
`evaluate_breakpoint_linear`だけはスカラーも受け付ける——軸スタジオの折れ点のプレビューと地図の段の
しきい値が、1点の得点を求めるのに使う。
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


def evaluate_categorical(value: np.ndarray, mapping: dict) -> np.ndarray:
    """カテゴリ値の配列→定数のマッピング。引けない値（欠損、および`mapping`に無い値）は
    「評価不能」としてNaNを返す。欠損の表現は材料により異なり、dtype=object の配列はNoneで表す。

    キーでソートした`np.searchsorted`（二分探索）で該当インデックスを求める
    （mappingの各キーごとに配列全体を走査するO(要素数×キー数)ではなく、
    highway等キー数が多い多値categorical材料でもO(要素数×log(キー数))で済む）。
    欠損（None）は`keys[0]`の位置へ一時的に
    差し替えてから検索する必要がある（Noneはstr材料と順序比較できずsearchsorted自体が
    例外になるため）が、`keys[0]`はmappingの実在キーなので置き換えただけでは
    「一致した」ことにしてしまう——`missing`マスクを別途保持し、検索結果とは無関係に
    強制的に不一致にする。
    """
    keys = sorted(mapping.keys())
    key_scores = np.array([mapping[key] for key in keys], dtype=float)
    keys_array = np.array(keys, dtype=value.dtype if value.dtype != object else object)
    missing = value == None  # noqa: E711 (numpy配列の要素ごと比較、`is`では動かない)
    safe_value = np.where(missing, keys[0], value)
    idx = np.clip(np.searchsorted(keys_array, safe_value), 0, len(keys) - 1)
    matched = (keys_array[idx] == safe_value) & ~missing
    return np.where(matched, key_scores[idx], np.nan)


def round1_array(values: np.ndarray) -> np.ndarray:
    """`round(x, 1)`（Python組み込み、2進浮動小数点の実際の値に対する正しい丸め）と
    ビット単位で一致させるための配列版丸め。`np.round`は内部で「×10→rint→÷10」という
    段階を踏むため、その掛け算で丸め誤差が混入し、値がちょうど.X5の境界にあると
    Python組み込みの`round()`と結果が食い違うことがある。NaNはNaNのまま返す。
    """
    values = np.asarray(values, dtype=float)
    scaled = values * 10.0
    out = np.rint(scaled) / 10.0
    # ×10の丸め誤差で判定が変わりうるのは、計算後の値がちょうど.5に乗った要素だけ
    # （真の積が.5境界の反対側にあれば、float64の積は必ずちょうど.5へ丸まる）。
    # その要素だけPythonのround()（10進の正しい丸め）で決め直す。NaNはそのまま伝播する。
    tie = (scaled - np.floor(scaled)) == 0.5
    if tie.any():
        idx = np.flatnonzero(tie)
        out[idx] = [round(float(values[i]), 1) for i in idx]
    return out
