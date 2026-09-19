"""Edge Costの算出（仕様書26-33章）。

Road Attribute（`domain/attributes.py`）とRoute PreferenceからEdge Costを算出する。
Route Engineから独立させ、Route Engine自身は「勾配がきつい」「路面が悪い」といった
評価の中身を一切知らない設計を目指す（仕様書33章）。

評価はタイル単位の静的スコア行列（`build_static_edge_score_matrix`）へ一本化してある。
入力はDBが導出した材料の行列（`EdgeMaterialArrays`）で、このモジュールは材料の値を
どう求めるかを知らない。way1本を指す区間インスペクタだけがスカラーで評価する
（`domain/axis_inspector.py`→`evaluate_axes_scalar`）。

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

from dataclasses import dataclass, field
import math
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
    evaluate_axis_array,
    topological_axis_order,
)
from app.domain.axis_display import axis_material_shares, raw_value_unit
from app.domain.axis_templates import round1_array
from app.domain.difficulty import composite_difficulty, distance_weighted_difficulty_array
from app.domain.dynamic_materials import (
    DynamicAxisRequestContext,
    evaluate_dynamic_material_arrays,
)
from app.domain.graph import RoadGraphLike
from app.domain.hard_filters import (
    HARD_FILTER_NAMES,
)
from app.domain.material_catalog import (
    MATERIAL_CATALOG,
)
from app.domain.cycling_speed import ROLLING_RESISTANCE_MATERIAL_ID
from app.domain.traffic import stop_count_material_ids
from app.domain.weather import WeatherConditions
from app.domain.tuning import tuning_value




def compute_cost_from_axis_scores(
    distance_m: float,
    axis_scores: dict[str, float],
    weights: dict[str, float],
    penalty_strength: float = 1.0,
    bbox_mean_difficulty: float | None = None,
) -> tuple[float, float | None]:
    """三次: 重みベクトル×軸別スコアのみからコストを算出する純関数
    （`cost = length × (1 + P × Σᵢ wᵢ × axisᵢ / 100)`、設計プロンプト「評価システムの
    層構造再設計」の三次そのもの。シグネチャに一次属性名を一切含まない）。

    `axis_scores`にキーが存在しない軸は合成から除外され、残りの軸の重みで再正規化される
    （`domain/difficulty.py: composite_difficulty`と同じ「データ無しは除外」方針）。
    `weights`に対応するキーが無い軸は重み0として扱う。

    `penalty_strength`（P、T12 ADR原則1）は割増率の強さを調整するリクエストパラメータ。
    既定1.0の挙動は最悪でも下地2倍。P=0で常に`cost=下地`（難易度を一切考慮しない）、
    Pを上げるほど悪路が強く避けられる（P=4なら最悪の道は5倍相当）。`cost >= 下地`
    （P>=0の間は常に成り立つ）という不変条件は維持し、下地の下界がコストの下界でも
    あるというA*の前提を崩さない。

    `bbox_mean_difficulty`: 重み付き軸すべてが欠損（`difficulty is None`）のときに
    コスト計算だけへ代入する値（呼び出し元がbboxの実データから求めた距離加重平均
    difficulty、`domain/difficulty.py: distance_weighted_difficulty_array`参照）。省略時
    （既定None）は`cost=distance_m`（割増なし）。戻り値の`difficulty`（表示用）はこの
    代入の影響を受けず、欠損なら常にNoneのまま返す——探索コストのみ補完し表示は変えない
    という方針（`compose_costs_from_axis_matrix`と同じ）を、Edge単位のこの関数でも保つ。
    """
    scored_weights = [(score, weights.get(axis_id, 0.0)) for axis_id, score in axis_scores.items()]
    difficulty = composite_difficulty(scored_weights)
    cost_difficulty = difficulty if difficulty is not None else bbox_mean_difficulty
    penalty_multiplier = 1.0 + penalty_strength * (cost_difficulty / 100) if cost_difficulty is not None else 1.0
    cost = round(distance_m * penalty_multiplier, 1)
    return cost, difficulty



def _neumaier_accumulate(terms: list[np.ndarray]) -> np.ndarray:
    """`terms`を先頭から順に加算する（Neumaier補償加算、Kahan加算の改良版）。

    Python組み込み`sum()`はPython 3.12以降、float列を単純な逐次`+=`ではなく
    Neumaier補償加算で合計するよう変更されている（丸め誤差を打ち消す補正項cを
    別途積算し、最後に本体へ足し込む）。スカラー版`composite_difficulty`の
    `sum(score*weight for score,weight in available)`と本関数（配列側の重み付き合成）を
    ビット単位で一致させるには、単純な逐次`+=`ではこのNeumaier補正が
    再現できず、ちょうど.X5境界の値で最終丸め結果が食い違う（例えば単純逐次加算は
    0.8200000000000001、`sum()`は0.82のように異なる浮動小数点値になることがあり、
    composite=41.25の丸めが41.3 vs 41.2に分かれる場合がある）。本関数はNeumaier加算を
    n件分まとめて配列演算で行うことで、`sum()`と同じ結果をEdge数万件規模でもPythonループ
    無しで再現する。
    """
    total = np.zeros_like(terms[0], dtype=float)
    compensation = np.zeros_like(terms[0], dtype=float)
    for term in terms:
        t = total + term
        correction = np.where(np.abs(total) >= np.abs(term), (total - t) + term, (term - t) + total)
        compensation += correction
        total = t
    return total + compensation


def has_route_facing_raw_value(definition: AxisDefinition) -> bool:
    """その軸の生値を静的スコア行列の列として持つか。

    空タイル（列だけを揃える分岐）と通常のタイルが**別々にこの条件を書く**と、片方だけ
    変えた瞬間に列数・列順が食い違い、`combine_static_edge_score_matrices`の
    `np.concatenate`がタイルをまたいで失敗する（またはずれた列で合成される）。
    T536と同型の壊れ方をするため、述語はここ1箇所だけが持つ。

    - 単位が定まらない軸（`raw_value_unit`がNone）は、数字を添えても読み手が意味を取れない。
    - 動的材料（風）を参照する軸は対象外——静的スコア行列は`weather=None`で組み立てるため
      生値がNaNになり、人へ見せる値にならない。
    """
    if raw_value_unit(definition) is None:
        return False
    return not (set(definition.materials) & REQUEST_DYNAMIC_MATERIAL_IDS)


def route_facing_raw_axis_ids() -> list[str]:
    """静的スコア行列が生値の列として持つ軸id（**並びも含めた唯一の定義元**）。

    空タイルの分岐・通常タイルの構築・キャッシュ読み出し時の列検証が別々にこの条件を
    書くと、片方だけ変えた瞬間に列数・列順が食い違い、
    `combine_static_edge_score_matrices`の`np.concatenate`がタイルをまたいで失敗する
    （または、ずれた列で合成されて別の軸の生値を表示する）。
    """
    return [
        axis_id
        for axis_id in topological_axis_order(AXIS_DEFINITIONS)
        if AXIS_DEFINITIONS[axis_id].is_published
        and has_route_facing_raw_value(AXIS_DEFINITIONS[axis_id])
        and has_axis_raw_value_array(AXIS_DEFINITIONS[axis_id])
    ]


def route_facing_material_ids() -> list[str]:
    """内訳として経路へ運ぶ材料id（安定順）。

    単位が定まらない軸（合成軸・真偽値やカテゴリの材料を持つ軸）は`axis_raw_arrays`へ
    載らず、得点だけしか出せない。材料まで分解すれば較正に依存しない絶対の事実を出せる
    （`axis_display.py: axis_material_shares`、docs/tasks/T689.md参照）ため、分解された
    葉の材料を軸の生値と同じ形で列として持つ。

    `has_route_facing_raw_value`と同じ理由でこの述語は**ここ1箇所だけが持つ**——空タイル
    （列だけを揃える分岐）と通常のタイルが別々に条件を書くと、片方だけ変えた瞬間に
    列数・列順が食い違い、`combine_static_edge_score_matrices`の`np.concatenate`が
    タイルをまたいで失敗する（またはずれた列で合成される）。

    対象外:

    - categorical材料（`highway`等）。列は数値行列のため文字列を載せられない。
      値ごとの延長割合は別の器が要る（[T718](docs/tasks/T718.md)）。
    - 動的材料（風）。静的スコア行列は`weather=None`で組み立てるため全行NaNになる。
    - 分解しない軸（参照材料が1件）。軸単位の生値（`axis_raw_arrays`）で足りる。

    軸が1つも参照していなくても、走行モデルが所要時間の算出に使う材料（停止の待ちは
    `domain/traffic.py: stop_count_material_ids`、転がり抵抗は
    `domain/cycling_speed.py: ROLLING_RESISTANCE_MATERIAL_ID`）は常に含める——軸の
    公開/非公開で所要時間の中身が変わってはいけない。
    """
    seen: dict[str, None] = {}
    for material_id in (*stop_count_material_ids(), ROLLING_RESISTANCE_MATERIAL_ID):
        if material_id in MATERIAL_CATALOG:
            seen.setdefault(material_id, None)
    for axis_id in topological_axis_order(AXIS_DEFINITIONS):
        definition = AXIS_DEFINITIONS[axis_id]
        if not definition.is_published:
            continue
        for entry in axis_material_shares(definition):
            spec = MATERIAL_CATALOG.get(entry.material_id)
            if spec is None or spec.dtype == "categorical":
                continue
            if entry.material_id in REQUEST_DYNAMIC_MATERIAL_IDS:
                continue
            seen.setdefault(entry.material_id, None)
    return list(seen)


def route_facing_categorical_material_ids() -> list[str]:
    """内訳として経路へ運ぶcategorical材料id（安定順）。

    `route_facing_material_ids`のcategorical版。数値行列には文字列を載せられないため、
    列は別に持つ（`StaticEdgeScoreMatrix.categorical_material_values`）。区間ごとの値を
    ルート集約で「値ごとの延長割合」へ畳むのは`merge_material_category_shares`
    （docs/tasks/T718.md参照）。

    述語をここ1箇所に置く理由は`has_route_facing_raw_value`と同じ——空タイル（列だけを
    揃える分岐）と通常のタイルが別々に条件を書くと列がずれる。
    """
    seen: dict[str, None] = {}
    for axis_id in topological_axis_order(AXIS_DEFINITIONS):
        definition = AXIS_DEFINITIONS[axis_id]
        if not definition.is_published:
            continue
        for entry in axis_material_shares(definition):
            spec = MATERIAL_CATALOG.get(entry.material_id)
            if spec is None or spec.dtype != "categorical":
                continue
            seen.setdefault(entry.material_id, None)
    return list(seen)


@dataclass(frozen=True, slots=True)
class BulkAxisEvaluation:
    """材料の行列へ`AXIS_DEFINITIONS`を適用した結果
    （`_evaluate_axes_from_material_arrays`）。

    `axis_arrays`は公開軸のみ・依存順（`topological_axis_order`のサブセット）。重み付き
    合成（Neumaier加算・cost算出）は含まない——`weights`が定まった時点で呼び出し元が
    `compose_costs_from_axis_matrix`へ渡す。0次フィルタは`hard_filter_flags`/
    `gradient_percent`の生フラグのみを持ち、`hard_filters`/
    `max_average_grade_percent`（リクエストごとに変わりうる）による絞り込みは
    `compute_hard_filter_excluded`が別途行う。
    """

    edge_ids: list[str]
    distance_m: np.ndarray
    bearing_deg: np.ndarray
    # 0次フィルタ用の生フラグ。`HARD_FILTER_HIGHWAY_TYPES`のフィルタ名→該当するかの真偽値配列
    # （リクエストごとに変わる有効/無効の絞り込みは`compute_hard_filter_excluded`が行う）。
    # フィルタを1つ増やしてもこの構造は変わらない——専用フィールドへ潰すと、
    # dataclass・結合・受け渡しの全段で1本ずつ追加が要る。
    # 0次フィルタ名→該当フラグ（`HARD_FILTER_NAMES`と同じキー集合）。
    hard_filter_flags: dict[str, np.ndarray]
    gradient_percent: np.ndarray
    # Edge中点の緯度経度（from/toノードの平均）。探索前に各Edgeの通過予定時刻を基準点からの
    # 直線距離で推定するために使う。
    mid_lat: np.ndarray
    mid_lon: np.ndarray
    axis_arrays: dict[str, np.ndarray]
    # 折れ点を通す前の生値。単位が定まる軸（`axis_display.py: raw_value_unit`）だけを
    # 持つ——単位の無い値を人へ見せても意味を取れないため、運ぶ必要が無い。
    axis_raw_arrays: dict[str, np.ndarray]
    # 内訳として見せる材料の値（`route_facing_material_ids`の材料だけ）。真偽値材料は
    # 0/1のfloatで持ち、距離加重平均が「該当区間の延長割合」になる。
    material_value_arrays: dict[str, np.ndarray] = field(default_factory=dict)
    # 内訳として見せるcategorical材料の値（文字列のobject配列）。数値と同じ行列へは
    # 載せられないため別に持つ。
    categorical_material_arrays: dict[str, np.ndarray] = field(default_factory=dict)


def _empty_material_arrays(n: int) -> dict[str, np.ndarray]:
    """`MATERIAL_CATALOG`全材料ぶんの配列を、材料ごとの既定値（NaN/False/None）で確保する。

    **extractorやSQL式を持たない材料の列も確保する**。持たない材料（トリガー付きDEFER）を
    `MaterialTerm`等で参照する軸は軸スタジオから素朴に作れてしまい
    （`_check_materials_are_known`はextractorの有無を見ない）、列が無いと
    `evaluate_axis_array`の`materials[term.material]`がKeyErrorで/api/routes/generate
    自体を落とす。確保しておけば「材料はあるがデータが無い」という既存の意味論へ揃い、
    スカラー版と同じグレースフルデグレード（その軸だけ恒久的に欠損扱い）になる。
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


def _evaluate_axes_from_material_arrays(
    edge_ids: list[str],
    material_arrays: dict[str, np.ndarray],
    *,
    hard_filter_flags: Mapping[str, np.ndarray],
    distance_m: np.ndarray,
    bearing_deg: np.ndarray,
    mid_lat: np.ndarray,
    mid_lon: np.ndarray,
    weather: WeatherConditions | None = None,
    travel_speed_ms: float | None = None,
) -> BulkAxisEvaluation:
    """材料と区間の列が揃っている状態から先（計算フェーズと軸の評価）。

    材料をどこで導いたか——`MaterialSpec.value_sql`でDBが導いたか、extractorがEdgeごとに
    導いたか——をここは知らない。呼び出し元は`material_arrays`へ**`MATERIAL_CATALOG`全材料
    ぶんの列**を渡す（`_empty_material_arrays`へ重ねる）。

    0次ハードフィルタの生フラグと区間そのものの列（距離・方位・中点）は材料ではないため
    別に受け取る。フィルタは`HARD_FILTER_NAMES`と同じキー集合の辞書で渡す。
    """
    n = len(edge_ids)

    if n == 0:
        # axis_arraysを空dict{}のまま返すと、build_static_edge_score_matrixが構築する
        # axis_scoresの列数が0になり、他タイル（列数=公開軸数、例えば8）と
        # combine_static_edge_score_matricesでnp.concatenateする際に「dimension 1の
        # サイズ不一致」でValueErrorになる（bbox内の1タイルがEdge0件[空タイル、道路
        # データが疎らな区画]の場合に起こりうる）。Edge0件でも「公開軸それぞれに対応
        # する長さ0の配列」を持たせることで、他タイルと同じ列数（shape=(0, 公開軸数)）に
        # 揃える。列の並び順は非空タイルの計算フェーズ（下記for文）と同じ
        # topological_axis_orderを使い、is_published判定も同じにする——
        # combine_static_edge_score_matricesは最初のタイルのaxis_idsをそのまま全体の
        # axis_idsとして採用するため、列の並びが全タイルで一致している必要がある。
        empty_axis_arrays = {
            axis_id: np.array([])
            for axis_id in topological_axis_order(AXIS_DEFINITIONS)
            if AXIS_DEFINITIONS[axis_id].is_published
        }
        empty_raw_arrays = {axis_id: np.array([]) for axis_id in route_facing_raw_axis_ids()}
        return BulkAxisEvaluation(
            edge_ids=[],
            distance_m=np.array([]),
            bearing_deg=np.array([]),
            hard_filter_flags={name: np.array([], dtype=bool) for name in HARD_FILTER_NAMES},
            gradient_percent=np.array([]),
            mid_lat=np.array([]),
            mid_lon=np.array([]),
            axis_arrays=empty_axis_arrays,
            axis_raw_arrays=empty_raw_arrays,
            # **非空タイルと同じ絞り込みを掛ける**（下の計算フェーズと同じ
            # `in MATERIAL_CATALOG`）。片方だけ素通しにすると、空タイルだけが余分な列を
            # 持ち、`combine_static_edge_score_matrices`が列の対応を取れなくなる
            # ——上の軸の列で書いたのと同じ形の食い違いが、材料の列で起きる。
            material_value_arrays={
                material_id: np.array([])
                for material_id in route_facing_material_ids()
                if material_id in MATERIAL_CATALOG
            },
            categorical_material_arrays={
                material_id: np.array([], dtype=object)
                for material_id in route_facing_categorical_material_ids()
                if material_id in MATERIAL_CATALOG
            },
        )
    # --- 計算フェーズ（Pythonループ無し） ---
    # 動的材料はEdge単位のPythonループを経由しない完全ベクトル化計算のためextractorを
    # 持たない（material_catalog.pyのextractorフィールド説明参照）。
    if weather is None:
        material_arrays.update({material_id: np.full(n, np.nan) for material_id in REQUEST_DYNAMIC_MATERIAL_IDS})
    else:
        if travel_speed_ms is None:
            raise ValueError("_evaluate_axes_bulk: travel_speed_ms is required when weather is given")
        dynamic_context = DynamicAxisRequestContext(bearing_deg=bearing_deg, weather=weather, travel_speed_ms=travel_speed_ms)
        material_arrays.update(evaluate_dynamic_material_arrays(dynamic_context))
    # スカラー版compute_edge_axis_scores（`evaluate_axes_scalar`）と同じ依存順評価
    # （軸が他の軸のdifficultyをmaterialとして参照できる階層構造）。
    # material_arrays_with_axesへは内部軸も含め全軸の結果を混ぜ込む（公開軸が内部軸を
    # materialとして参照できる必要があるため）が、axis_arrays（下の合成対象）は
    # 公開軸のみに絞る（内部軸のdefault_weight=0.0のため合成結果への影響自体は無いが、
    # スカラー版のフィルタと揃え、無駄な計算・将来の重み設定変更時の暗黙のリスクを
    # 無くす）。
    axis_arrays: dict[str, np.ndarray] = {}
    axis_raw_arrays: dict[str, np.ndarray] = {}
    material_arrays_with_axes: dict[str, np.ndarray] = dict(material_arrays)
    for axis_id in topological_axis_order(AXIS_DEFINITIONS):
        definition = AXIS_DEFINITIONS[axis_id]
        arr = evaluate_axis_array(definition, material_arrays_with_axes)
        material_arrays_with_axes[axis_id] = arr
        if definition.is_published:
            axis_arrays[axis_id] = arr
    # 生値の列は`route_facing_raw_axis_ids`が決める（空タイル分岐・読み出し時検証と同じ
    # 定義元を使う。ここで条件を書き直すと、片方だけ変えたときに列がずれる）。
    for axis_id in route_facing_raw_axis_ids():
        raw = axis_raw_value_array(AXIS_DEFINITIONS[axis_id], material_arrays_with_axes)
        assert raw is not None, f"route_facing_raw_axis_idsが返した{axis_id}の生値が作れない"
        axis_raw_arrays[axis_id] = raw

    # 絞り込みの条件は空タイル分岐（上）と同じにする——`material_arrays`はここで
    # `MATERIAL_CATALOG`全材料ぶん確保しているため、両者は同じ集合を指す。
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

    return BulkAxisEvaluation(
        edge_ids=edge_ids,
        distance_m=distance_m,
        bearing_deg=bearing_deg,
        hard_filter_flags=dict(hard_filter_flags),
        gradient_percent=material_arrays["gradient_percent"],
        mid_lat=mid_lat,
        mid_lon=mid_lon,
        axis_arrays=axis_arrays,
        axis_raw_arrays=axis_raw_arrays,
        material_value_arrays=material_value_arrays,
        categorical_material_arrays=categorical_material_arrays,
    )


# 主観的割増と時間の換算レート（P）の既定値。`難易度100の道は体感で所要時間の(1+P)倍`の
# 意味で、コスト式は`所要時間 × (1 + P × difficulty/100)`。
#
# 走行モデルへ入っている現象を写した軸の既定重みは0のため（docs/design-principles.md
# 構造仕様13）、difficultyは主観的な軸だけの加重平均になり、物理の軸で薄まらないぶん
# 値が大きく出る。Pはその物差しに合わせた値で、**実走での較正が要る暫定値**。
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


def axis_contributions_at_row(
    axis_arrays: Mapping[str, np.ndarray],
    weights: Mapping[str, float],
    weight_sums: np.ndarray,
    row: int,
) -> dict[str, float]:
    """1区間ぶんの軸別寄与度。`compose_costs_from_axis_matrix`の配列版と同じ式。

    配列版は全区間ぶん（数十万×軸数）作るが、読むのは経路上の数百区間だけのため、
    区間表示は先に作らずここで1行だけ求める。
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


class AxisComposition(NamedTuple):
    """`compose_costs_from_axis_matrix`の戻り値。"""

    cost: np.ndarray
    difficulty: np.ndarray
    contributions: dict[str, np.ndarray]
    # 区間ごとの「データのある軸の重みの合計」。軸別寄与度は`軸の値 × 重み ÷ これ`のため、
    # 寄与度の配列を作らずに後から1行だけ求めたい呼び出し元が使う。
    weight_sums: np.ndarray


def _axis_terms(
    axis_arrays: Mapping[str, np.ndarray], weights: dict[str, float]
) -> tuple[list[np.ndarray], list[np.ndarray], list[tuple[str, np.ndarray, float, np.ndarray]]]:
    """軸ごとの「重み付きスコアの項」「重みの項」と、寄与度の内訳に要る素材。

    データ欠損（NaN）の軸はその区間だけ項を0にする＝和から外す（「データ無しは除外し
    残りの重みで再正規化」）。**この式を2箇所に書かない**——先に和だけ求める経路と合成の
    本体で式がずれると、寄与度の内訳と合成difficultyが静かに食い違う。
    """
    score_terms: list[np.ndarray] = []
    weight_terms: list[np.ndarray] = []
    axis_weight_valid: list[tuple[str, np.ndarray, float, np.ndarray]] = []
    for axis_id, arr in axis_arrays.items():
        weight = weights.get(axis_id, 0.0)
        valid = ~np.isnan(arr)
        score_terms.append(np.where(valid, arr * weight, 0.0))
        weight_terms.append(np.where(valid, weight, 0.0))
        axis_weight_valid.append((axis_id, arr, weight, valid))
    return score_terms, weight_terms, axis_weight_valid


def axis_weighted_sums(
    axis_arrays: Mapping[str, np.ndarray], weights: dict[str, float], length: int
) -> tuple[np.ndarray, np.ndarray]:
    """`compose_costs_from_axis_matrix`の`static_sums`へ渡す`(重み付きスコアの和, 重みの和)`。

    データ欠損（NaN）の軸はその区間だけ和から外す（項の作り方は`_axis_terms`が単一の情報源）。
    """
    if not axis_arrays:
        return np.zeros(length), np.zeros(length)
    score_terms, weight_terms, _ = _axis_terms(axis_arrays, weights)
    return _neumaier_accumulate(score_terms), _neumaier_accumulate(weight_terms)


def compose_costs_from_axis_matrix(
    distance_m: np.ndarray,
    axis_arrays: Mapping[str, np.ndarray],
    weights: dict[str, float],
    penalty_strength: float = 1.0,
    base: np.ndarray | None = None,
    static_sums: tuple[np.ndarray, np.ndarray] | None = None,
    with_contributions: bool = True,
) -> AxisComposition:
    """`_evaluate_axes_from_material_arrays`/`evaluate_dynamic_axis_arrays`が求めた軸別
    スコア配列群から、重み付き合成のcost・composite difficulty配列・軸別寄与度配列を
    求める。

    `base`は割増を掛ける下地で、探索は区間ごとの所要時間（秒）を渡す——コストは
    `所要時間 × (1 + P × difficulty/100)`＝**体感の所要時間**になり、`penalty_strength`は
    「difficulty 100の道は体感で何倍の時間に感じるか−1」を意味する。省略時は`distance_m`
    を下地にする（距離そのものを下地にしたいとき）。difficultyの合成自体は下地に依らない。

    `static_sums`は`axis_arrays`に**含めなかった**軸ぶんの`(重み付きスコアの和, 重みの和)`。
    時刻ビンごとに合成し直すとき、時刻で変わらない軸の和を1回だけ求めて使い回すために渡す
    （合成の時間は軸数にほぼ比例するため、動的な軸だけを毎回足す形にすると大きく減る）。
    `with_contributions=False`は軸別寄与度（表示用）を組み立てない——探索へ渡すだけの
    ビンでは要らない。`static_sums`と併用できないのは、寄与度は`axis_arrays`へ渡した軸ぶん
    しか作れず、和へ畳んだ軸の内訳が黙って欠けるため。

    Neumaier加算・`round1_array`はスカラー版`composite_difficulty`/
    `compute_cost_from_axis_scores`とビット単位で一致させるために必須
    （`_neumaier_accumulate`のdocstring参照）。0次フィルタによる除外（cost=inf/None）は
    呼び出し元の責務（`compute_hard_filter_excluded`参照、Edgeの通行可否そのものであり
    軸別スコアの合成とは独立した判定のため）。戻り値は`(cost, composite_difficulty,
    axis_contributions)`（difficultyはNaN=データ無し、costは0次フィルタを考慮しない
    「仮に許可された場合のコスト」、axis_contributionsはaxis_id→寄与度配列
    ——validな軸のみ`arr*weight/weighted_weight_sums`、invalidな区間はNaN。全軸の
    寄与度を丸め前で合計すると丸め前のcompositeと一致する——`RouteCandidate.
    overall_difficulty`とその内訳`axis_contributions`を数学的に一致させるための値
    ）。

    重み付き軸がすべてデータ欠損（composite=NaN）のEdgeは、costの算出だけ`distance_m`
    加重の`domain/difficulty.py: distance_weighted_difficulty_array`で求めたbbox内平均
    difficultyを代入する（呼び出し元のリクエストごとに実データから求まる値で、
    固定定数は使わない）。戻り値の`composite_difficulty`・`axis_contributions`
    （表示用）はこの代入の影響を受けず、欠損なら常にNaNのまま返す。bbox内が全Edge欠損
    （代入する平均値自体が無い）ならこれまでどおりcost=distance_m（割増なし）。
    """
    if static_sums is not None and with_contributions:
        raise ValueError(
            "static_sumsへ畳んだ軸の寄与度は作れないため、with_contributionsとは併用できない"
        )
    n = len(distance_m)
    dynamic_scores, dynamic_weights, axis_weight_valid = _axis_terms(axis_arrays, weights)
    score_terms = ([] if static_sums is None else [static_sums[0]]) + dynamic_scores
    weight_terms = ([] if static_sums is None else [static_sums[1]]) + dynamic_weights
    # 公開軸が1つも無い場合はn件ぶんのゼロ配列を直接使う（下の
    # weighted_weight_sums==0判定が既にNaN合成へ倒す設計のため、この分岐を通しても
    # 後続処理は変更不要）。
    if score_terms:
        weighted_scores = _neumaier_accumulate(score_terms)
        weighted_weight_sums = _neumaier_accumulate(weight_terms)
    else:
        weighted_scores = np.zeros(n)
        weighted_weight_sums = np.zeros(n)
    with np.errstate(invalid="ignore", divide="ignore"):
        composite = weighted_scores / weighted_weight_sums
    composite = np.where(weighted_weight_sums == 0, np.nan, composite)
    # np.roundは内部で「×10→rint→÷10」という段階を踏むため、その中間の掛け算で
    # 丸め誤差が混入し、ちょうど.X5の境界にある値でPythonの`round(x, 1)`
    # （2進浮動小数点の実際の値に対する正しい丸め）と結果が食い違うことがある
    # （例えば385.949999999999988...のような値でnp.roundは386.0、round()は385.9に
    # なることがある）。
    # スカラー版composite_difficulty/compute_cost_from_axis_scoresの`round(x, 1)`と
    # 完全一致させるため、最終丸めのみ要素ごとにPythonの`round()`を適用する。
    composite = round1_array(composite)

    # 軸ごとの区間寄与度。compositeとは異なり、ここでは丸めない
    # （区間単位ではなくルート単位に距離加重平均した後、そちらで最終丸めする——
    # `RouteSegmentDetail.axis_difficulties`/`domain/route.py: merge_axis_difficulties`と
    # 同じ「区間単位は生値、ルート単位で丸め」という既存の扱いに揃える）。
    axis_contributions: dict[str, np.ndarray] = {}
    if with_contributions:
        for axis_id, arr, weight, valid in axis_weight_valid:
            with np.errstate(invalid="ignore", divide="ignore"):
                contribution = np.where(valid, arr * weight / weighted_weight_sums, np.nan)
            axis_contributions[axis_id] = np.where(weighted_weight_sums == 0, np.nan, contribution)

    # costの算出にだけ、重み付き軸が全欠損のEdgeへbbox内平均difficultyを
    # 代入する（composite自体は表示用にNaNのまま返す、上のdocstring参照）。
    cost_base = distance_m if base is None else base
    bbox_mean = distance_weighted_difficulty_array(composite, distance_m)
    if bbox_mean is None:
        cost_difficulty = composite
    else:
        cost_difficulty = np.where(np.isnan(composite), bbox_mean, composite)
    # compute_cost_from_axis_scoresと同じ: difficultyがNaN(None相当)ならcostは下地そのもの
    # （割増なし）。
    penalty_multiplier = np.where(np.isnan(cost_difficulty), 1.0, 1.0 + penalty_strength * (cost_difficulty / 100))
    cost = cost_base * penalty_multiplier
    if base is None:
        # 下地が距離のときだけ0.1m単位へ丸める（スカラー版のオラクルと一致させるため）。
        # 秒を下地にすると0.1秒は短い区間の数%にあたり、`cost/所要時間`からdifficultyを
        # 逆算する側（折返し点・経由Nodeの並べ替え）に丸め由来の差が現れる。
        cost = round1_array(cost)
    return AxisComposition(cost, composite, axis_contributions, weighted_weight_sums)



@dataclass(frozen=True, slots=True)
class StaticEdgeScoreMatrix:
    """タイル単位でキャッシュする「Edge×公開軸」の静的スコア行列＋0次フィルタ・A*
    ヒューリスティック用の生配列。全ての配列は`edge_ids`と同じ行順で揃う（Edge単位の
    辞書キャッシュに比べ、本行列はEdgeあたり軸の数×8バイト程度で収まる）。

    `axis_scores`の列（`axis_ids`）は風などREQUEST_DYNAMIC_MATERIAL_IDSに依存する軸を
    含む全公開軸だが、そのような軸の列は常にNaN（`_evaluate_axes_bulk`をweather=Noneで
    呼ぶことで自然にそうなる）。リクエスト時に`evaluate_dynamic_axis_arrays`が該当列だけを
    実際の動的データ（風・走行速度）で上書きする。

    既知の制約（意図的なスコープ限定、docs/tasks/T536.md参照）: 動的軸が参照できる材料は
    `REQUEST_DYNAMIC_MATERIAL_IDS`のみを前提にしている（風軸が風の材料1つだけを参照する
    構成と一致）。将来、動的材料と他の静的材料を組み合わせる軸が必要になった場合は
    別途設計が要る。
    """

    edge_ids: list[str]
    axis_ids: list[str]
    axis_scores: np.ndarray  # shape (len(edge_ids), len(axis_ids))
    distance_m: np.ndarray
    bearing_deg: np.ndarray
    # 0次フィルタ用の生フラグ。`HARD_FILTER_HIGHWAY_TYPES`のフィルタ名→該当するかの真偽値配列
    # （リクエストごとに変わる有効/無効の絞り込みは`compute_hard_filter_excluded`が行う）。
    # フィルタを1つ増やしてもこの構造は変わらない——専用フィールドへ潰すと、
    # dataclass・結合・受け渡しの全段で1本ずつ追加が要る。
    # 0次フィルタ名→該当フラグ（`HARD_FILTER_NAMES`と同じキー集合）。
    hard_filter_flags: dict[str, np.ndarray]
    gradient_percent: np.ndarray
    # Edge中点の緯度経度（`BulkAxisEvaluation.mid_lat`/`mid_lon`と同じ）。
    mid_lat: np.ndarray
    mid_lon: np.ndarray
    # 折れ点を通す前の生値。単位が定まる軸だけを持つため`axis_ids`とは別の並びで、
    # 対応する列は`raw_axis_ids`の順。軸単体で経路を判断するための絶対値
    # （docs/tasks/T687.md参照）。
    raw_axis_ids: list[str] = field(default_factory=list)
    axis_raw_values: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))
    # 内訳として見せる材料の値。対応する列は`material_ids`の順
    # （`route_facing_material_ids`が列の集合と並びの唯一の定義元）。
    material_ids: list[str] = field(default_factory=list)
    material_values: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))
    # 内訳として見せるcategorical材料の値（文字列のobject配列、列は
    # `categorical_material_ids`の順）。数値の行列へは載せられないため別に持つ。
    categorical_material_ids: list[str] = field(default_factory=list)
    categorical_material_values: np.ndarray = field(default_factory=lambda: np.empty((0, 0), dtype=object))


def _static_edge_score_matrix_from(evaluation: BulkAxisEvaluation) -> StaticEdgeScoreMatrix:
    """軸ごとの配列を行列へ束ねる。材料をどこで導いたかに依らない共通の後段。"""
    axis_ids = list(evaluation.axis_arrays.keys())
    axis_scores = (
        np.stack([evaluation.axis_arrays[axis_id] for axis_id in axis_ids], axis=1)
        if axis_ids
        else np.empty((len(evaluation.edge_ids), 0))
    )
    raw_axis_ids = list(evaluation.axis_raw_arrays.keys())
    axis_raw_values = (
        np.stack([evaluation.axis_raw_arrays[axis_id] for axis_id in raw_axis_ids], axis=1)
        if raw_axis_ids
        else np.empty((len(evaluation.edge_ids), 0))
    )
    material_ids = list(evaluation.material_value_arrays.keys())
    material_values = (
        np.stack([evaluation.material_value_arrays[material_id] for material_id in material_ids], axis=1)
        if material_ids
        else np.empty((len(evaluation.edge_ids), 0))
    )
    categorical_material_ids = list(evaluation.categorical_material_arrays.keys())
    categorical_material_values = (
        np.stack(
            [evaluation.categorical_material_arrays[material_id] for material_id in categorical_material_ids],
            axis=1,
        )
        if categorical_material_ids
        else np.empty((len(evaluation.edge_ids), 0), dtype=object)
    )
    return StaticEdgeScoreMatrix(
        edge_ids=evaluation.edge_ids,
        axis_ids=axis_ids,
        axis_scores=axis_scores,
        raw_axis_ids=raw_axis_ids,
        axis_raw_values=axis_raw_values,
        material_ids=material_ids,
        material_values=material_values,
        categorical_material_ids=categorical_material_ids,
        categorical_material_values=categorical_material_values,
        distance_m=evaluation.distance_m,
        bearing_deg=evaluation.bearing_deg,
        hard_filter_flags=evaluation.hard_filter_flags,
        gradient_percent=evaluation.gradient_percent,
        mid_lat=evaluation.mid_lat,
        mid_lon=evaluation.mid_lon,
    )


def build_static_edge_score_matrix(
    graph: RoadGraphLike,
    materials: EdgeMaterialArrays,
    accident_years_covered: int = 0,
) -> StaticEdgeScoreMatrix:
    """タイル読込時（`GraphService._get_or_build_tile_materials`）に1回だけ呼び、
    `StaticEdgeScoreMatrix`を構築する。

    材料はDBが導出済み（`MaterialSpec.value_sql`）で、`accident_years_covered`はその導出の
    中で既に効いているためここでは使わない（引数は呼び出し側の読みやすさのために残す）。
    動的軸（風）の列はここではNaNのままで、リクエスト時に
    `evaluate_dynamic_axis_arrays`が埋める。
    """
    arrays = _empty_material_arrays(len(materials))
    arrays.update(materials.columns())
    return _static_edge_score_matrix_from(
        _evaluate_axes_from_material_arrays(
            materials.edge_ids,
            arrays,
            hard_filter_flags=materials.hard_filter_columns(),
            distance_m=materials.distance_m,
            bearing_deg=materials.bearing_deg,
            mid_lat=materials.mid_lat,
            mid_lon=materials.mid_lon,
        )
    )


def combine_static_edge_score_matrices(matrices: list[StaticEdgeScoreMatrix]) -> StaticEdgeScoreMatrix:
    """複数タイルぶんの`StaticEdgeScoreMatrix`を、bbox全体1件分へ結合する
    （`GraphService._build_search_materials_from_tile_cache`が複数z12タイルを1つの探索用
    グラフへ結合するのと同じタイミングで使う）。

    タイル同士でEdgeが重複する場合（境界付近等、稀）は**後のタイルを優先**する
    （`combined_edges.update(tile.graph.edges)`と同じ「後勝ち」セマンティクスに揃える）。
    行の並べ替えはEdge数十万件規模でもO(N)のnumpy fancy indexingで済み、Edge単位の
    Pythonループ（探索のホットパスで避けたい処理そのもの）はここでは発生しない
    （タイル→結合Edge indexの対応付けだけがPython dictループだが、これは`dict.update`
    ベースの既存のグラフ結合処理と同じオーダーの一度きりのコスト）。
    """
    if not matrices:
        return StaticEdgeScoreMatrix(
            edge_ids=[], axis_ids=[], axis_scores=np.empty((0, 0)),
            distance_m=np.array([]), bearing_deg=np.array([]),
            hard_filter_flags={name: np.array([], dtype=bool) for name in HARD_FILTER_NAMES}, gradient_percent=np.array([]),
            mid_lat=np.array([]), mid_lon=np.array([]),
        )
    if len(matrices) == 1:
        return matrices[0]

    axis_ids = matrices[0].axis_ids
    raw_axis_ids = matrices[0].raw_axis_ids
    material_ids = matrices[0].material_ids
    categorical_material_ids = matrices[0].categorical_material_ids
    # 先頭タイルの列をそのまま全体の列として採用する以上、全タイルで一致していることを
    # ここで確かめる。食い違ったまま`np.concatenate`すると、列数が違えばValueErrorで落ち、
    # 偶然一致すれば**別の軸の生値を表示する**（後者は例外にならないぶん質が悪い）。
    for index, matrix in enumerate(matrices[1:], start=1):
        mismatched = [
            name
            for name, first, other in (
                ("axis_ids", axis_ids, matrix.axis_ids),
                ("raw_axis_ids", raw_axis_ids, matrix.raw_axis_ids),
                ("material_ids", material_ids, matrix.material_ids),
                ("categorical_material_ids", categorical_material_ids, matrix.categorical_material_ids),
            )
            if first != other
        ]
        if mismatched:
            raise ValueError(
                f"静的スコア行列の列がタイル間で一致しません index={index} 不一致={mismatched}"
            )
    all_edge_ids = [edge_id for matrix in matrices for edge_id in matrix.edge_ids]
    axis_scores = np.concatenate([matrix.axis_scores for matrix in matrices], axis=0)
    axis_raw_values = np.concatenate([matrix.axis_raw_values for matrix in matrices], axis=0)
    material_values = np.concatenate([matrix.material_values for matrix in matrices], axis=0)
    categorical_material_values = np.concatenate(
        [matrix.categorical_material_values for matrix in matrices], axis=0
    )
    distance_m = np.concatenate([matrix.distance_m for matrix in matrices])
    bearing_deg = np.concatenate([matrix.bearing_deg for matrix in matrices])
    # フィルタ名の集合は全タイルで同じ（`HARD_FILTER_NAMES`から一律に作る）ため、
    # 先頭タイルのキーで揃える。
    hard_filter_flags = {
        name: np.concatenate([matrix.hard_filter_flags[name] for matrix in matrices])
        for name in matrices[0].hard_filter_flags
    }
    gradient_percent = np.concatenate([matrix.gradient_percent for matrix in matrices])
    mid_lat = np.concatenate([matrix.mid_lat for matrix in matrices])
    mid_lon = np.concatenate([matrix.mid_lon for matrix in matrices])

    # 重複edge_idは後勝ち（後から登場した行のindexで上書き）。
    last_index_for_edge_id: dict[str, int] = {edge_id: i for i, edge_id in enumerate(all_edge_ids)}
    final_edge_ids = list(last_index_for_edge_id.keys())
    final_indices = np.array(list(last_index_for_edge_id.values()), dtype=int)

    return StaticEdgeScoreMatrix(
        edge_ids=final_edge_ids,
        axis_ids=axis_ids,
        axis_scores=axis_scores[final_indices],
        raw_axis_ids=raw_axis_ids,
        axis_raw_values=axis_raw_values[final_indices],
        material_ids=material_ids,
        material_values=material_values[final_indices],
        categorical_material_ids=categorical_material_ids,
        categorical_material_values=categorical_material_values[final_indices],
        distance_m=distance_m[final_indices],
        bearing_deg=bearing_deg[final_indices],
        hard_filter_flags={name: flags[final_indices] for name, flags in hard_filter_flags.items()},
        gradient_percent=gradient_percent[final_indices],
        mid_lat=mid_lat[final_indices],
        mid_lon=mid_lon[final_indices],
    )
