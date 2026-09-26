"""Edge Costの算出。

Road Attribute（`domain/attributes.py`）とRoute PreferenceからEdge Costを算出する。
Route Engineから独立させ、Route Engine自身は「勾配がきつい」「路面が悪い」といった
評価の中身を一切知らないようにする。

評価は探索範囲ごとの静的スコア行列（`build_static_edge_score_matrix`）へ一本化してある。
入力はDBが導出した材料の行列（`EdgeMaterialArrays`）で、このモジュールは材料の値を
どう求めるかを知らない。way1本を指す区間インスペクタは、同じ評価を長さ1の配列で通す
（`domain/axis_inspector.py`→`evaluate_axes_values`）。

三次（重み付き合成）は`compose_costs_from_axis_matrix`が単独で使える——軸別スコアが
既にあるなら、材料からやり直さずここだけを呼ぶ。

変更理由の異なる以下は別モジュールにある:
`domain/route_preference.py`（重み指定）・`domain/hard_filters.py`（0次フィルタ）・
`domain/dynamic_materials.py`（風などリクエスト時に決まる材料）・
`domain/axis_inspector.py`（区間インスペクタ、Way単位の材料解決）。

Score（難易度換算）は`domain/difficulty.py`（0-100、値が大きいほど走りにくい絶対基準）を
そのまま再利用する。ルート単位の可視化とEdge単位の評価が同じ「難易度」の意味・スケールを
共有することで、新しい正規化方式を発明せず、評価基準の食い違いも避ける。
"""

from dataclasses import dataclass
from typing import Mapping, NamedTuple

import numpy as np

from app.domain.attributes import (
    EdgeMaterialArrays,
)
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    REQUEST_DYNAMIC_MATERIAL_IDS,
    AxisDefinition,
    axis_raw_value_array,
    has_axis_raw_value_array,
    evaluate_axes_array,
    topological_axis_order,
)
from app.domain.axis_raw_value import axis_material_shares, raw_value_unit
from app.domain.difficulty import composite_difficulty_array, distance_weighted_difficulty_array
from app.domain.material_catalog import (
    GRADIENT_PERCENT,
    MATERIAL_CATALOG,
)
from app.domain.cycling_speed import ROLLING_RESISTANCE_MATERIAL_ID
from app.domain.traffic import stop_count_material_ids
from app.domain.tuning import tuning_value


def has_route_facing_raw_value(definition: AxisDefinition) -> bool:
    """その軸の生値を静的スコア行列の列として持つか。述語はここ1箇所だけが持つ。

    - 単位が定まらない軸（`raw_value_unit`がNone）は、数字を添えても読み手が意味を取れない。
    - 動的材料（風）を参照する軸は対象外——静的スコア行列は`weather=None`で組み立てるため
      生値がNaNになり、人へ見せる値にならない。
    """
    if raw_value_unit(definition) is None:
        return False
    return not (set(definition.materials) & REQUEST_DYNAMIC_MATERIAL_IDS)


def route_facing_raw_axis_ids() -> list[str]:
    """静的スコア行列が生値の列として持つ軸id（**並びも含めた唯一の定義元**）。"""
    return [
        axis_id
        for axis_id in topological_axis_order(AXIS_DEFINITIONS)
        if AXIS_DEFINITIONS[axis_id].is_published
        and has_route_facing_raw_value(AXIS_DEFINITIONS[axis_id])
        and has_axis_raw_value_array(AXIS_DEFINITIONS[axis_id])
    ]


def _published_axis_leaf_material_ids() -> list[str]:
    """公開軸を依存順に辿り、分解された葉の材料idを安定順で返す。

    下の2本（数値列とcategorical列）が同じ順序で列を組み立てるための土台。
    """
    seen: dict[str, None] = {}
    for axis_id in topological_axis_order(AXIS_DEFINITIONS):
        definition = AXIS_DEFINITIONS[axis_id]
        if not definition.is_published:
            continue
        for entry in axis_material_shares(definition):
            seen.setdefault(entry.material_id, None)
    return list(seen)


def route_facing_material_ids() -> list[str]:
    """内訳として経路へ運ぶ材料id（安定順）。

    単位が定まらない軸（合成軸・真偽値やカテゴリの材料を持つ軸）は`axis_raw_arrays`へ
    載らず、得点だけしか出せない。材料まで分解すれば較正に依存しない絶対の事実を出せる
    （`axis_raw_value.py: axis_material_shares`）ため、分解された葉の材料を軸の生値と
    同じ形で列として持つ。

    対象外:

    - categorical材料（`highway`等）。列は数値行列のため文字列を載せられない。
      値ごとの延長割合は別の器（`merge_material_category_shares`）が要る。
    - 動的材料（風）。静的スコア行列は`weather=None`で組み立てるため全行NaNになる。
    - 分解しない軸（参照材料が1件）。軸単位の生値（`axis_raw_arrays`）で足りる。

    軸が1つも参照していなくても、走行モデルが所要時間の算出に使う材料（停止の待ちは
    `domain/traffic.py: stop_count_material_ids`）は常に含める——軸の
    公開/非公開で所要時間の中身が変わってはいけない。
    """
    seen: dict[str, None] = {}
    for material_id in stop_count_material_ids():
        seen.setdefault(material_id, None)
    for material_id in _published_axis_leaf_material_ids():
        spec = MATERIAL_CATALOG.get(material_id)
        if spec is None or spec.dtype == "categorical":
            continue
        if material_id in REQUEST_DYNAMIC_MATERIAL_IDS:
            continue
        seen.setdefault(material_id, None)
    return list(seen)


def route_facing_categorical_material_ids() -> list[str]:
    """内訳として経路へ運ぶcategorical材料id（安定順）。

    `route_facing_material_ids`のcategorical版。数値行列には文字列を載せられないため、
    列は別に持つ（`StaticEdgeScoreMatrix.categorical_material_values`）。区間ごとの値を
    ルート集約で「値ごとの延長割合」へ畳むのは`merge_material_category_shares`。

    走行モデルが転がり抵抗に使う材料（`domain/cycling_speed.py: ROLLING_RESISTANCE_MATERIAL_ID`）は、
    軸が参照していなくても常に含める（理由は`route_facing_material_ids`の停止の待ちと同じ）。
    """
    seen: dict[str, None] = {ROLLING_RESISTANCE_MATERIAL_ID: None}
    for material_id in _published_axis_leaf_material_ids():
        spec = MATERIAL_CATALOG.get(material_id)
        if spec is None or spec.dtype != "categorical":
            continue
        seen.setdefault(material_id, None)
    return list(seen)


def _empty_material_arrays(n: int) -> dict[str, np.ndarray]:
    """`MATERIAL_CATALOG`全材料ぶんの配列を、材料ごとの既定値（NaN/False/None）で確保する。

    **SQL式（`value_sql`）を持たない材料の列も確保する**。持たない材料（トリガー付きDEFER）を
    `MaterialTerm`等で参照する軸は軸スタジオから素朴に作れてしまい
    （`_check_materials_are_known`は`value_sql`の有無を見ない）、列が無いと
    `evaluate_axis_array`の`materials[term.material]`がKeyErrorで/api/routes/generate
    自体を落とす。確保しておけば「材料はあるがデータが無い」という既存の意味論へ揃い、
    その軸だけ恒久的に欠損扱いになる（`evaluate_axis_values`が無い材料を欠損として扱うのと同じ）。
    """
    arrays: dict[str, np.ndarray] = {}
    for spec in MATERIAL_CATALOG.values():
        if spec.dtype == "categorical":
            # np.emptyのdtype=objectは要素をNone初期化する（Python object配列のcalloc特性）。
            arrays[spec.material_id] = np.empty(n, dtype=object)
        elif spec.dtype == "boolean" and spec.bool_default == "false":
            arrays[spec.material_id] = np.zeros(n, dtype=bool)
        else:  # numeric、またはbool_default="nan"のboolean（surface_good等）
            arrays[spec.material_id] = np.full(n, np.nan)
    return arrays


# 主観的割増と時間の換算レート（P）の既定値。`難易度100の道は体感で所要時間の(1+P)倍`の
# 意味で、コスト式は`所要時間 × (1 + P × difficulty/100)`。
#
# 走行モデルへ入っている現象を写した軸の既定重みは0のため（docs/architecture/design-principles.md
# 構造仕様13）、difficultyは主観的な軸だけの加重平均になり、物理の軸で薄まらないぶん
# 値が大きく出る。Pはその物差しに合わせた値で、**実走から較正した値ではない**。
def resolve_penalty_strength(requested: float | None) -> float:
    """リクエストが省略したときの換算レート（P）を、**呼ばれた時点で**較正値から読む。

    **モジュール直下で束ねない**。`TUNING_VALUES`へDBの上書きを重ねる
    `refresh_tuning_values`は起動時のlifespan（＝全importの後）で走るため、import時に
    束ねた値にはDBの上書きが一度も入らない——プロセスを入れ替えても同じ順序を繰り返す
    だけで、管理画面は変えた値を「いま効いている値」として表示しながら、探索はずっと
    宣言の既定値で動く。
    """
    if requested is not None:
        return requested
    return tuning_value("evaluation.penalty_strength")


class AxisComposition(NamedTuple):
    """`compose_costs_from_axis_matrix`の戻り値。"""

    cost: np.ndarray
    difficulty: np.ndarray
    # 区間ごとの「データのある軸の重みの合計」。軸別寄与度（`axis_contributions_at_row`）の分母。
    weight_sums: np.ndarray


def compose_costs_from_axis_matrix(
    distance_m: np.ndarray,
    axis_arrays: Mapping[str, np.ndarray],
    weights: dict[str, float],
    penalty_strength: float,
    *,
    base: np.ndarray,
    static_sums: tuple[np.ndarray, np.ndarray] | None = None,
) -> AxisComposition:
    """`build_static_edge_score_matrix`/`evaluate_dynamic_axis_arrays`が求めた軸別
    スコア配列群から、重み付き合成のcost・composite difficulty配列を求める。

    `base`は割増を掛ける下地で、探索は区間ごとの所要時間（秒）を渡す——コストは
    `所要時間 × (1 + P × difficulty/100)`＝**体感の所要時間**になり、`penalty_strength`は
    「difficulty 100の道は体感で何倍の時間に感じるか−1」を意味する（逆算は
    `difficulty_from_cost`）。difficultyの合成自体（`composite_difficulty_array`）は下地に依らない。
    costは丸めない——0.1秒は短い区間の所要時間の数%にあたり、逆算した値に丸めの差が現れる。

    `static_sums`は`axis_arrays`に**含めなかった**軸ぶんの`(重み付きスコアの和, 重みの和)`。
    時刻ビンごとに合成し直すとき、時刻で変わらない軸の和を1回だけ求めて使い回すために渡す
    （合成の時間は軸数にほぼ比例するため、動的な軸だけを毎回足す形にすると大きく減る）。

    0次フィルタによる除外（cost=inf/None）は呼び出し元の責務（`compute_hard_filter_excluded`
    参照、Edgeの通行可否そのものであり軸別スコアの合成とは独立した判定のため）。戻り値の
    difficultyはNaN=データ無し、costは0次フィルタを考慮しない「仮に許可された場合のコスト」、
    weight_sumsは軸別寄与度の分母。

    重み付き軸がすべてデータ欠損（composite=NaN）のEdgeは、costの算出だけ`distance_m`
    加重の`domain/difficulty.py: distance_weighted_difficulty_array`で求めたbbox内平均
    difficultyを代入する（呼び出し元のリクエストごとに実データから求まる値で、
    固定定数は使わない）。戻り値の`composite_difficulty`（表示用）はこの代入の影響を
    受けず、欠損なら常にNaNのまま返す。bbox内が全Edge欠損
    （代入する平均値自体が無い）ならcost=下地（割増なし）。
    """
    composite, weight_sums = composite_difficulty_array(axis_arrays, weights, len(distance_m), static_sums)

    # costの算出にだけ、重み付き軸が全欠損のEdgeへbbox内平均difficultyを
    # 代入する（composite自体は表示用にNaNのまま返す、上のdocstring参照）。
    bbox_mean = distance_weighted_difficulty_array(composite, distance_m)
    if bbox_mean is None:
        cost_difficulty = composite
    else:
        cost_difficulty = np.where(np.isnan(composite), bbox_mean, composite)
    # difficultyがNaN(None相当)ならcostは下地そのもの（割増なし）。
    penalty_multiplier = np.where(np.isnan(cost_difficulty), 1.0, 1.0 + penalty_strength * (cost_difficulty / 100))
    return AxisComposition(base * penalty_multiplier, composite, weight_sums)


def difficulty_from_cost(cost: np.ndarray, seconds: np.ndarray, penalty_strength: float) -> np.ndarray:
    """コスト`所要時間 × (1 + P × difficulty/100)`（`compose_costs_from_axis_matrix`）から、
    所要時間あたりのdifficultyを逆算する。求まらない要素（所要時間0・到達不能）は0。

    P<=0ではコストが所要時間そのもので難易度を含まないため、全要素0（全候補同点）。
    """
    if penalty_strength <= 0:
        return np.zeros(len(cost))
    with np.errstate(invalid="ignore", divide="ignore"):
        difficulty = (cost / seconds - 1.0) / penalty_strength * 100.0
    return np.where(np.isfinite(difficulty), difficulty, 0.0)


@dataclass(frozen=True, slots=True)
class StaticEdgeScoreMatrix:
    """探索範囲の区間ごとの「Edge×公開軸」の静的スコア行列＋0次フィルタ・A*
    ヒューリスティック用の生配列。全ての配列は同じ行順（切り出した区間の順）で揃う。

    `axis_scores`の列（`axis_ids`）は風などREQUEST_DYNAMIC_MATERIAL_IDSに依存する軸を
    含む全公開軸だが、そのような軸の列は常にNaN（`build_static_edge_score_matrix`が
    動的材料の列をNaNで埋める）。リクエスト時に`evaluate_dynamic_axis_arrays`が該当列だけを
    実際の動的データ（風・走行速度）で上書きする。

    動的軸が参照できる材料は`REQUEST_DYNAMIC_MATERIAL_IDS`だけを前提にしている。
    動的材料と静的材料を混ぜる軸はこの形では表現できない。
    """

    axis_ids: list[str]
    axis_scores: np.ndarray  # shape (区間, len(axis_ids))
    distance_m: np.ndarray
    bearing_deg: np.ndarray
    # 0次フィルタ名→該当フラグ（`HARD_FILTER_NAMES`と同じキー集合）。リクエストごとに
    # 変わる有効/無効の絞り込みは`compute_hard_filter_excluded`が行う。
    # フィルタを1つ増やしてもこの構造は変わらない——専用フィールドへ潰すと、
    # dataclass・結合・受け渡しの全段で1本ずつ追加が要る。
    hard_filter_flags: dict[str, np.ndarray]
    gradient_percent: np.ndarray
    # Edge中点の緯度経度（from/toノードの平均）。探索前に各Edgeの通過予定時刻を基準点からの
    # 直線距離で推定するために使う。
    mid_lat: np.ndarray
    mid_lon: np.ndarray
    # 折れ点を通す前の生値。単位が定まる軸（`axis_raw_value.py: raw_value_unit`）だけを持つ
    # ——単位の無い値を人へ見せても意味を取れないため運ばない。そのため`axis_ids`とは別の並びで、
    # 対応する列は`raw_axis_ids`の順。軸単体で経路を判断するための絶対値。
    raw_axis_ids: list[str]
    axis_raw_values: np.ndarray
    # 内訳として見せる材料の値。対応する列は`material_ids`の順
    # （`route_facing_material_ids`が列の集合と並びの唯一の定義元）。真偽値材料は0/1のfloatで
    # 持ち、距離加重平均が「該当区間の延長割合」になる。
    material_ids: list[str]
    material_values: np.ndarray
    # 内訳として見せるcategorical材料の値（文字列のobject配列、列は
    # `categorical_material_ids`の順）。数値の行列へは載せられないため別に持つ。
    categorical_material_ids: list[str]
    categorical_material_values: np.ndarray

    def __post_init__(self) -> None:
        """行と列が揃っていることを、組み立てた場所で確かめる。

        揃っていないまま先へ進むと、行がずれた区間のコストと難易度を**別のEdgeのもの**として
        返し、列がずれれば別の軸の生値を表示する。どちらも例外にならない。
        """
        rows = len(self.distance_m)
        matrices = (
            ("axis_scores", self.axis_scores, self.axis_ids),
            ("axis_raw_values", self.axis_raw_values, self.raw_axis_ids),
            ("material_values", self.material_values, self.material_ids),
            ("categorical_material_values", self.categorical_material_values, self.categorical_material_ids),
        )
        wrong_columns = {
            name: (matrix.shape[1], len(ids)) for name, matrix, ids in matrices if matrix.shape[1] != len(ids)
        }
        if wrong_columns:
            raise ValueError(f"静的スコア行列の列数がid列と違います（列数, id数）= {wrong_columns}")
        wrong_rows = {
            name: array.shape
            for name, array in (
                ("distance_m", self.distance_m),
                ("bearing_deg", self.bearing_deg),
                ("gradient_percent", self.gradient_percent),
                ("mid_lat", self.mid_lat),
                ("mid_lon", self.mid_lon),
                *((f"hard_filter_flags[{name}]", flags) for name, flags in self.hard_filter_flags.items()),
                *((name, matrix) for name, matrix, _ in matrices),
            )
            if array.shape[0] != rows
        }
        if wrong_rows:
            raise ValueError(f"静的スコア行列の行数が区間数と違います 区間={rows} {wrong_rows}")

    def axis_arrays(self) -> dict[str, np.ndarray]:
        """軸id→スコア配列。合成（`compose_costs_from_axis_matrix`）と動的軸の上書き
        （`evaluate_dynamic_axis_arrays`）はこの形で受け取る。"""
        return {axis_id: self.axis_scores[:, i] for i, axis_id in enumerate(self.axis_ids)}


def _stack_columns(columns: dict[str, np.ndarray], rows: int, dtype: type = np.float64) -> tuple[list[str], np.ndarray]:
    """id→列の辞書を、idの並びと`(行, id)`の行列へ束ねる。"""
    ids = list(columns)
    matrix = np.stack([columns[i] for i in ids], axis=1) if ids else np.empty((rows, 0), dtype=dtype)
    return ids, matrix


def build_static_edge_score_matrix(materials: EdgeMaterialArrays) -> StaticEdgeScoreMatrix:
    """切り出した範囲の材料から`StaticEdgeScoreMatrix`を構築する（生成のたびに1回）。

    材料はDBが導出済み（`MaterialSpec.value_sql`）で、事故の収録年数による正規化もその
    導出の中で既に効いている。軸が読む材料の列は`MATERIAL_CATALOG`全材料ぶん確保する
    （`_empty_material_arrays`へ重ねる）。

    重み付き合成は含まない——重みが定まった時点で呼び出し元が`compose_costs_from_axis_matrix`へ
    渡す。0次フィルタは生フラグだけを持ち、リクエストごとに変わる絞り込みは
    `compute_hard_filter_excluded`が別途行う。

    **動的材料（風）の列は常にNaN**。風は区間の通過時刻で変わるため、この行列では値を持てず、
    リクエスト時に`evaluate_dynamic_axis_arrays`が該当列を通過時刻ごとに上書きする。
    """
    n = len(materials)
    material_arrays = _empty_material_arrays(n)
    material_arrays.update(materials.columns())
    material_arrays.update({material_id: np.full(n, np.nan) for material_id in REQUEST_DYNAMIC_MATERIAL_IDS})
    # 合成の対象（axis_arrays）は公開軸だけ。内部軸は公開軸の材料として読まれるだけで、
    # 利用者の重みの対象ではない。
    material_arrays_with_axes = evaluate_axes_array(material_arrays)
    axis_arrays = {
        axis_id: material_arrays_with_axes[axis_id]
        for axis_id in topological_axis_order(AXIS_DEFINITIONS)
        if AXIS_DEFINITIONS[axis_id].is_published
    }
    axis_raw_arrays: dict[str, np.ndarray] = {}
    for axis_id in route_facing_raw_axis_ids():
        raw = axis_raw_value_array(AXIS_DEFINITIONS[axis_id], material_arrays_with_axes)
        assert raw is not None, f"route_facing_raw_axis_idsが返した{axis_id}の生値が作れない"
        axis_raw_arrays[axis_id] = raw
    material_value_arrays = {
        material_id: material_arrays[material_id].astype(float, copy=False)
        for material_id in route_facing_material_ids()
        if material_id in material_arrays
    }
    categorical_material_arrays = {
        material_id: material_arrays[material_id]
        for material_id in route_facing_categorical_material_ids()
        if material_id in material_arrays
    }

    axis_ids, axis_scores = _stack_columns(axis_arrays, n)
    raw_axis_ids, axis_raw_values = _stack_columns(axis_raw_arrays, n)
    material_ids, material_values = _stack_columns(material_value_arrays, n)
    categorical_material_ids, categorical_material_values = _stack_columns(categorical_material_arrays, n, object)
    return StaticEdgeScoreMatrix(
        axis_ids=axis_ids,
        axis_scores=axis_scores,
        raw_axis_ids=raw_axis_ids,
        axis_raw_values=axis_raw_values,
        material_ids=material_ids,
        material_values=material_values,
        categorical_material_ids=categorical_material_ids,
        categorical_material_values=categorical_material_values,
        distance_m=materials.distance_m,
        bearing_deg=materials.bearing_deg,
        hard_filter_flags=materials.hard_filter_columns(),
        gradient_percent=material_arrays[GRADIENT_PERCENT],
        mid_lat=materials.mid_lat,
        mid_lon=materials.mid_lon,
    )
