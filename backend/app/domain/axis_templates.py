"""評価軸の変換ロジックが還元できる4つの汎用テンプレート（改善計画T221 Stage A、T239）。

`docs/decisions/t221-axis-registry.md`の調査で、旧7軸（勾配・向かい風・路面・停止密度・
車ストレス・事故密度・夜間）の一次属性→軸別difficulty(0-100)変換は、実質以下の4パターンに
還元できると判明した。

- **区分線形補間**（`evaluate_breakpoint_linear`）: 勾配・向かい風・停止密度・事故密度・
  車ストレスを支える内部軸の一部（highway基本値・制限速度補正・車線数補正）が該当。
  両端でクランプする折れ線補間。
- **カテゴリ→定数**（`evaluate_categorical`）: 路面（舗装/非舗装）、車ストレスを支える
  内部軸の一部（自転車インフラ補正・指定路線補正・motor_vehicle=no優先確定）が該当。
- **フラグ加算**（`evaluate_flag_sum`）: 夜間（街灯なし・トンネル）が該当。
- **レシピ→レベル→区分線形補間**（`evaluate_recipe_then_breakpoint_linear`）: 導入当時は
  専用Pythonレシピ（highway別基準値＋各種タグ補正を1関数で算出する車ストレス判定）を
  想定していたが、改善計画T292でその専用レシピ自体を廃止し、car_stress軸を
  `domain/axis_definitions.py`の内部軸6つ+公開軸1つの階層構造（区分線形補間・
  カテゴリ→定数の組み合わせ）へ再設計したため、現在この種別を使う軸は無い
  （実装自体は`evaluate_breakpoint_linear`のエイリアスとしてそのまま残置。
  `kind="recipe_then_breakpoint_linear"`という語彙は目論見書の歯止め③
  [テンプレート4種の線引き]に触れるため、未使用であっても保守的に残す設計判断）。

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
    """カテゴリ値→定数のマッピング。配列入力は要素ごとに`mapping`を適用し、NaN・None
    （不明値のプレースホルダ、材料により表現が異なる。dtype=object の文字列配列は
    欠損をNoneで表す）はそのまま伝播する（`mapping`に一致するキーが無い要素は
    `default`、既定Noneなら数値配列の文脈に合わせてNaN）。

    配列入力はキーでソートした`np.searchsorted`（二分探索）で該当インデックスを求める
    （コードレビュー指摘の修正: 以前はmappingの各キーごとに配列全体を`np.where`で
    走査するO(要素数×キー数)のループだったが、highway等キー数が多い多値categorical
    材料でO(要素数×log(キー数))へ改善）。欠損（None）は`keys[0]`の位置へ一時的に
    差し替えてから検索する必要がある（Noneはstr材料と順序比較できずsearchsorted自体が
    例外になるため）が、`keys[0]`はmappingの実在キーなので置き換えただけでは
    「一致した」ことにしてしまう——`missing`マスクを別途保持し、検索結果とは無関係に
    強制的に不一致（=`default`）にする。
    """
    if isinstance(value, np.ndarray):
        fill = np.nan if default is None else float(default)
        if not mapping:
            return np.full(value.shape, fill, dtype=float)
        keys = sorted(mapping.keys())
        key_scores = np.array([mapping[key] for key in keys], dtype=float)
        keys_array = np.array(keys, dtype=value.dtype if value.dtype != object else object)
        missing = value == None  # noqa: E711 (numpy配列の要素ごと比較、`is`では動かない)
        safe_value = np.where(missing, keys[0], value)
        idx = np.clip(np.searchsorted(keys_array, safe_value), 0, len(keys) - 1)
        matched = (keys_array[idx] == safe_value) & ~missing
        return np.where(matched, key_scores[idx], fill)
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
