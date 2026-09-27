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

from app.domain.attributes import CategoricalColumn, MaterialColumn


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


def evaluate_categorical(value: MaterialColumn, mapping: dict) -> np.ndarray:
    """カテゴリ値の配列→定数のマッピング。引けない値（欠損、および`mapping`に無い値）は
    「評価不能」としてNaNを返す。欠損の表現は材料により異なり、dtype=object の配列はNoneで表す。

    分類の材料の列（`CategoricalColumn`、ルート選びの経路）は語彙ごとに1回引いて番号で配る。
    それ以外（真偽の材料の配列と、Pythonの値から作ったobjectの配列）は
    キーでソートした`np.searchsorted`（二分探索）で該当インデックスを求める
    （mappingの各キーごとに配列全体を走査するO(要素数×キー数)ではなく、
    highway等キー数が多い多値categorical材料でもO(要素数×log(キー数))で済む）。
    欠損（None）は`keys[0]`の位置へ一時的に
    差し替えてから検索する必要がある（Noneはstr材料と順序比較できずsearchsorted自体が
    例外になるため）が、`keys[0]`はmappingの実在キーなので置き換えただけでは
    「一致した」ことにしてしまう——`missing`マスクを別途保持し、検索結果とは無関係に
    強制的に不一致にする。
    """
    if isinstance(value, CategoricalColumn):
        return value.lookup(mapping)
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
    # その要素だけ決め直す。NaNはそのまま伝播する。
    tie = (scaled - np.floor(scaled)) == 0.5
    if tie.any():
        out[tie] = _round1_on_half(values[tie], np.floor(scaled[tie]))
    return out


def _round1_on_half(values: np.ndarray, lower: np.ndarray) -> np.ndarray:
    """×10がちょうど`lower + 0.5`になった値を、`round(x, 1)`と同じ値へ丸める。

    重み0.5ずつの和のように、小数1桁の得点を半分にした値は半数近くの要素がここへ来るため、
    要素ごとにPythonの`round()`を呼ばず配列のまま決める。値と10進の中点`(2*lower + 1)/20`の大小を
    整数で正確に比べる——値は`仮数 × 2**-shift`と正確に書けるので、`20 × 仮数`と
    `(2*lower + 1) × 2**shift`の比較になる。中点に等しい（中点が2進で正確に表せる、例: 0.25）ときは
    `round()`と同じく偶数の側へ丸める。×10がちょうど.5に乗るのは|値|が0.05以上で×10が2**52未満の
    ときだけなので、shiftは57以下で、両辺は2**59未満に収まりint64であふれない。
    """
    mantissa, exponent = np.frexp(values)
    significand = np.ldexp(mantissa, 53).astype(np.int64)
    scale = np.left_shift(np.int64(1), 53 - exponent.astype(np.int64))
    midpoint = (2.0 * lower + 1.0).astype(np.int64)
    difference = 20 * significand - midpoint * scale
    round_up = (difference > 0) | ((difference == 0) & (np.mod(lower, 2.0) == 1.0))
    return np.copysign((lower + round_up) / 10.0, values)
