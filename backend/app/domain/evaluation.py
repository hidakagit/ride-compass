"""Edge Costの算出（仕様書26-33章）。

Road Attribute（`domain/attributes.py`）とRoute PreferenceからEdge Costを算出する。
Route Engineから独立させ、Route Engine自身は「勾配がきつい」「路面が悪い」といった
評価の中身を一切知らない設計を目指す（仕様書33章）。

**同じ評価を3つの表現で持つ**のがこのモジュールの責務で、3つは常に同じ結果を返す
（`tests/test_evaluation_bulk.py`が突き合わせる）:

| 表現 | 入口 | 使う場面 |
|---|---|---|
| スカラー（Edge1本） | `compute_edge_cost` / `compute_edge_axis_scores` | 区間表示、ベクトル版のオラクル |
| ベクトル（Edge群） | `compute_edge_costs_bulk` | bbox全体の一括評価 |
| タイル単位の静的行列 | `build_static_edge_score_matrix` | タイルキャッシュ（動的軸の列はNaNのまま持つ） |

材料の解決はどの表現も`MATERIAL_CATALOG`のextractor宣言1つ（`resolve_materials`）を通る。

変更理由の異なる以下は別モジュールにある:
`domain/route_preference.py`（重み指定）・`domain/hard_filters.py`（0次フィルタ）・
`domain/dynamic_materials.py`（風などリクエスト時に決まる材料）・
`domain/axis_inspector.py`（区間インスペクタ、Way単位の材料解決）。

Score（難易度換算）は`domain/difficulty.py`（0-100、値が大きいほど走りにくい絶対基準）を
そのまま再利用する。ルート単位の可視化とEdge単位の評価が同じ「難易度」の意味・スケールを
共有することで、新しい正規化方式を発明せず、評価基準の食い違いも避ける。
"""

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
from pydantic import BaseModel

from app.domain.attributes import (
    EdgeKeyedMetrics,
    EdgeMaterialBundle,
    EdgeMaterialTable,
    ElevationAttribute,
    edge_metrics_from_bundles,
)
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    REQUEST_DYNAMIC_MATERIAL_IDS,
    AxisDefinition,
    axis_raw_value_array,
    evaluate_axes_scalar,
    evaluate_axis_array,
    topological_axis_order,
)
from app.domain.axis_display import axis_material_shares, raw_value_unit
from app.domain.axis_templates import round1_array
from app.domain.difficulty import composite_difficulty, distance_weighted_difficulty_array
from app.domain.dynamic_materials import (
    DynamicAxisRequestContext,
    compute_dynamic_edge_materials,
    evaluate_dynamic_material_arrays,
)
from app.domain.graph import EdgeLike, RoadGraphLike
from app.domain.hard_filters import (
    HARD_FILTER_HIGHWAY_TYPES,
    compute_hard_filter_excluded,
    is_edge_allowed,
)
from app.domain.material_catalog import (
    EXTRACTABLE_MATERIAL_IDS,
    MATERIAL_CATALOG,
    MaterialExtractionContext,
    resolve_materials,
)
from app.domain.route_preference import RoutePreference
from app.domain.recipe import tag_value_is
from app.domain.weather import WeatherConditions


class EdgeCostResult(BaseModel):
    """Edge Costの算出結果。

    difficultyは0-100（大きいほど走りにくい、domain/difficulty.pyと同じ絶対基準）。
    costは距離ベース（メートル相当、小さいほど良い＝Route Engineが最短経路探索に
    そのまま使える単位）。allowed=FalseはHard Constraintによる除外を表し、この場合
    cost/difficultyはNoneになる。

    Road Graphへ恒久保存しない（仕様書32章）。このモデルは呼び出しごとの計算結果を
    表すだけであり、Route Preference・出発時刻（風）が変われば同じEdgeでも異なる
    結果になりうる。
    """

    edge_id: str
    cost: float | None
    difficulty: float | None
    allowed: bool


def compute_edge_axis_scores(
    edge: EdgeLike,
    elevation_attribute: ElevationAttribute | None,
    surface_type: str | None,
    weather: WeatherConditions | None = None,
    way_tags: dict[str, str] | None = None,
    metrics: Mapping[str, EdgeKeyedMetrics] | None = None,
    accident_years_covered: int = 0,
    is_designated: bool = False,
    travel_speed_ms: float | None = None,
) -> dict[str, float]:
    """二次: 一次属性から軸別スコア（axis_id→0-100のdifficulty）を算出する
    （設計プロンプト「評価システムの層構造再設計」の二次そのもの）。

    返り値のキーは`AXIS_DEFINITIONS`の公開axis_idで、評価できなかった軸（Noneのdifficulty）は
    キー自体を辞書へ含めない（三次側の`compute_cost_from_axis_scores`が「データ無しは合成から
    除外」する既存方針と対応する）。Hard Constraintの判定（`is_edge_allowed`）はここでは
    行わない（呼び出し元の責務、`compute_edge_cost`のdocstring参照）。

    材料の解決は`MATERIAL_CATALOG`のextractor宣言（`resolve_materials`）へ委ねる。
    ベクトル化経路（`_evaluate_axes_bulk`）と同じ1つの宣言を読むため、材料を1つ増やしても
    この関数は変わらない。

    `metrics`は件数・土地被覆のような「材料と一緒に増える数値」の束
    （群名→edge_id→{キー: 値}、`domain/attributes.py: edge_metrics_from_bundles`が組み立てる）。
    ベクトル化経路が受け取るものと同じ形をEdge1本ぶんで渡す——スカラー引数（件数を1つずつ
    受け取る形）にすると、群が増えるたびにこの関数の引数も増え、追従漏れがそのまま
    「この経路でだけ材料が欠損する」事故になるため。
    `way_tags`はこのEdgeのosm_way_idに対応する許可リストタグ（静的道路属性P0）。Noneは
    データ未取得（repository未注入等）を表し、タグ由来の材料はすべて欠損になる
    （highway由来の車ストレス内部軸もway_tags未取得時は意図的にNoneにして評価しない。
    「way_tags無し=car_stress未評価」を一貫させるため）。
    `accident_years_covered`は事故データの収録年数（`AttributeRepository.
    get_accident_years_covered`）で、密度を件/(km・年)へ正規化するために使う。
    `is_designated`はこのEdgeがKSJ N10/N12（緊急輸送道路・重要物流道路）に該当するか。
    `travel_speed_ms`は風の材料（走行速度依存）に使う走行速度（m/s）。`weather`を渡すときは
    必須（省略すると即座に失敗する）。
    """
    materials = resolve_materials(
        MaterialExtractionContext(
            edge_id=edge.edge_id,
            highway=edge.highway,
            way_tags=way_tags,
            distance_km=edge.distance_m / 1000,
            elevation_attributes={edge.edge_id: elevation_attribute} if elevation_attribute is not None else {},
            surface_attributes={edge.edge_id: surface_type},
            designated_edge_ids={edge.edge_id} if is_designated else set(),
            metrics=metrics or {},
            accident_years_covered=accident_years_covered,
        )
    )
    materials.update(compute_dynamic_edge_materials(edge, weather, travel_speed_ms))
    # 軸は他の軸のdifficultyをmaterialとして参照できる（内部軸→公開軸の階層構造）。
    # 依存先（参照される軸）を先に評価し、結果をmaterialsへ混ぜ込みながら
    # 進めることで、参照する側は追加のAPIなしに`materials.get(axis_id)`で読める
    # （`evaluate_axes_scalar`参照）。ここでは値が算出できなかった公開軸のキー自体を
    # 呼び出し元（RouteSegmentDetail構築側）へ渡さないよう、Noneのキーを落とす
    # （`axis_inspector_breakdown`はavailable判定のためNoneのキーを残したまま返す点が
    # 異なる）。
    scores, _ = evaluate_axes_scalar(materials)
    return {axis_id: value for axis_id, value in scores.items() if value is not None}


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
    既定1.0の挙動は最悪でも距離2倍。P=0で常に`cost=distance_m`（難易度を一切考慮しない
    最短距離探索）、Pを上げるほど悪路が強く避けられる（P=4なら最悪の道は距離5倍相当）。
    `cost >= distance_m`（P>=0の間は常に成り立つ）という不変条件は維持し、将来の探索
    高速化（直線距離を下界とするA*等）の前提を崩さない。

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


def compute_edge_cost(
    edge: EdgeLike,
    elevation_attribute: ElevationAttribute | None,
    surface_type: str | None,
    preference: RoutePreference,
    weather: WeatherConditions | None = None,
    way_tags: dict[str, str] | None = None,
    metrics: Mapping[str, EdgeKeyedMetrics] | None = None,
    accident_years_covered: int = 0,
    is_designated: bool = False,
    penalty_strength: float = 1.0,
    max_average_grade_percent: float | None = None,
    weights: dict[str, float] | None = None,
    hard_filters: frozenset[str] | None = None,
    bbox_mean_difficulty: float | None = None,
    travel_speed_ms: float | None = None,
) -> EdgeCostResult:
    """RouteEngineが利用できるEdge Costを算出する（仕様書31章）。

    一次属性から一気通貫でコストを算出する薄い合成関数（一次属性→二次[軸別スコア]は
    `compute_edge_axis_scores`、軸別スコア→三次[コスト合成]は`compute_cost_from_axis_scores`
    が担う）。三次のみを直接使いたい場合（例: レジストリ・Recipe駆動の呼び出し）は
    `compute_cost_from_axis_scores`を直接使う。

    パラメータの意味は`compute_edge_axis_scores`のdocstring参照（Hard Constraint判定
    `is_edge_allowed`はこの関数が担う。`max_average_grade_percent`はis_edge_allowedへ
    そのまま渡す）。

    `weights`: 呼び出し元が事前解決した重み辞書を渡すとそのまま使う。省略時（既定None）は
    `preference.weights`を使う。

    `hard_filters`はそのまま`is_edge_allowed`へ渡す（省略時は`DEFAULT_HARD_FILTERS`）。

    `bbox_mean_difficulty`はそのまま`compute_cost_from_axis_scores`へ渡す（同関数の
    docstring参照）。`travel_speed_ms`はそのまま`compute_edge_axis_scores`へ渡す
    （`weather`を渡すときは必須）。
    """
    if not is_edge_allowed(
        edge,
        way_tags,
        hard_filters=hard_filters,
        elevation_attribute=elevation_attribute,
        max_average_grade_percent=max_average_grade_percent,
    ):
        # bulk版（compute_edge_costs_bulk）と同じmodel_construct最適化。この関数は
        # lazy評価で探索のホットパス（訪れたEdgeごとに最大24回）になりうるため、
        # Pydanticバリデーションのコストを避ける（edge_id/cost/difficulty/allowedは
        # すべて内部で計算済みの値で、外部入力の検証は元々不要）。
        return EdgeCostResult.model_construct(edge_id=edge.edge_id, cost=None, difficulty=None, allowed=False)

    axis_scores = compute_edge_axis_scores(
        edge, elevation_attribute, surface_type, weather, way_tags, metrics,
        accident_years_covered, is_designated, travel_speed_ms=travel_speed_ms,
    )
    resolved_weights = weights if weights is not None else preference.weights
    cost, difficulty = compute_cost_from_axis_scores(
        edge.distance_m, axis_scores, resolved_weights, penalty_strength, bbox_mean_difficulty
    )

    return EdgeCostResult.model_construct(edge_id=edge.edge_id, cost=cost, difficulty=difficulty, allowed=True)


def _neumaier_accumulate(terms: list[np.ndarray]) -> np.ndarray:
    """`terms`を先頭から順に加算する（Neumaier補償加算、Kahan加算の改良版）。

    Python組み込み`sum()`はPython 3.12以降、float列を単純な逐次`+=`ではなく
    Neumaier補償加算で合計するよう変更されている（丸め誤差を打ち消す補正項cを
    別途積算し、最後に本体へ足し込む）。スカラー版`composite_difficulty`の
    `sum(score*weight for score,weight in available)`と本関数（`compute_edge_costs_bulk`の
    重み付き合成）をビット単位で一致させるには、単純な逐次`+=`ではこのNeumaier補正が
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
    """
    seen: dict[str, None] = {}
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
    """`compute_edge_costs_bulk`の抽出＋計算フェーズ（`_evaluate_axes_bulk`）の結果。
    bbox全体一括評価（`compute_edge_costs_bulk`本体）と、タイル単位の静的スコア行列構築
    （`build_static_edge_score_matrix`）の両方から共有する。

    `axis_arrays`は公開軸のみ・依存順（`topological_axis_order`のサブセット）。重み付き
    合成（Neumaier加算・cost算出）は含まない——`weights`が定まった時点で呼び出し元が
    `compose_costs_from_axis_matrix`へ渡す。0次フィルタは`highway_filter_flags`/
    `no_bicycle`/`gradient_percent`の生フラグのみを持ち、`hard_filters`/
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
    highway_filter_flags: dict[str, np.ndarray]
    no_bicycle: np.ndarray
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


def _evaluate_axes_bulk(
    graph: RoadGraphLike,
    elevation_attributes: dict[str, ElevationAttribute],
    surface_attributes: dict[str, str | None],
    weather: WeatherConditions | None,
    travel_speed_ms: float | None,
    way_tags: dict[str, dict[str, str]] | None,
    accident_years_covered: int,
    designated_edge_ids: set[str] | None,
    metrics: Mapping[str, EdgeKeyedMetrics] | None = None,
) -> BulkAxisEvaluation:
    """`compute_edge_costs_bulk`と`build_static_edge_score_matrix`が共有する抽出フェーズ
    （`MATERIAL_CATALOG`のextractor宣言経由でEdge単位の辞書・タグアクセスをnumpy配列へ
    落とし込む）と計算フェーズ（`AXIS_DEFINITIONS`を軸ごとに適用してdifficulty配列を
    求める）。

    動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）は`DYNAMIC_MATERIAL_EVALUATORS`が
    bearing配列・`weather`・`travel_speed_ms`から求める（`weather`を渡すときは
    `travel_speed_ms`が必須）。`weather=None`で呼ぶと動的材料がNaN配列になり、それに
    依存する軸の列は`evaluate_axis_array`のrequired項がNaNを演算で自然に伝播させるため、
    動的軸を特別扱いする分岐は不要。`build_static_edge_score_matrix`（タイル単位の
    静的スコア行列）がこの性質を使う。
    """
    designated_edge_ids = designated_edge_ids or set()
    metrics = metrics or {}

    edge_ids = list(graph.edges.keys())
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
        empty_raw_arrays = {
            axis_id: np.array([])
            for axis_id in empty_axis_arrays
            if has_route_facing_raw_value(AXIS_DEFINITIONS[axis_id])
        }
        return BulkAxisEvaluation(
            edge_ids=[],
            distance_m=np.array([]),
            bearing_deg=np.array([]),
            highway_filter_flags={name: np.array([], dtype=bool) for name in HARD_FILTER_HIGHWAY_TYPES},
            no_bicycle=np.array([], dtype=bool),
            gradient_percent=np.array([]),
            mid_lat=np.array([]),
            mid_lon=np.array([]),
            axis_arrays=empty_axis_arrays,
            axis_raw_arrays=empty_raw_arrays,
            material_value_arrays={
                material_id: np.array([]) for material_id in route_facing_material_ids()
            },
            categorical_material_arrays={
                material_id: np.array([], dtype=object)
                for material_id in route_facing_categorical_material_ids()
            },
        )
    edges = [graph.edges[edge_id] for edge_id in edge_ids]

    distance_m = np.array([edge.distance_m for edge in edges], dtype=float)
    nodes = graph.nodes
    mid_lat = np.array(
        [(nodes[edge.from_node_id].latitude + nodes[edge.to_node_id].latitude) / 2 for edge in edges], dtype=float
    )
    mid_lon = np.array(
        [(nodes[edge.from_node_id].longitude + nodes[edge.to_node_id].longitude) / 2 for edge in edges], dtype=float
    )
    bearing_deg = np.array(
        [edge.bearing_deg if edge.bearing_deg is not None else np.nan for edge in edges], dtype=float
    )

    # --- 抽出フェーズ（MATERIAL_CATALOGのextractor宣言へ委譲） ---
    extractable_materials = [MATERIAL_CATALOG[material_id] for material_id in EXTRACTABLE_MATERIAL_IDS]
    # 配列はMATERIAL_CATALOG全材料ぶん確保する（抽出ループはextractable_materialsのみ
    # 回す＝extractor未設定材料[oneway/designation/is_emergency_transport/
    # is_critical_logistics等、トリガー付きDEFER]は既定値[NaN/False]の
    # まま残る）。全材料ぶん確保しないと、そのような材料をMaterialTerm等で参照する
    # GUI作成軸（`_check_materials_are_known`はis_known_materialのみ検証しextractor
    # 有無は見ないため、軸スタジオから素朴に作成できてしまう）を評価した際に
    # evaluate_axis_arrayの`materials[term.material]`がKeyErrorで/api/routes/generate
    # 自体を落とす（スカラー版evaluate_axis_scalarは`materials.get(...)`のためこの経路
    # では発生しない非対称性がある）。全材料ぶん確保することで「材料はあるがデータが
    # 無い」という既存の意味論（欠損）へ揃え、スカラー版と同じグレースフルデグレード
    # （その軸だけ恒久的に欠損扱い）にする。
    material_arrays: dict[str, np.ndarray] = {}
    for spec in MATERIAL_CATALOG.values():
        if spec.dtype == "categorical":
            # np.emptyのdtype=objectは要素をNone初期化する（Python object配列のcalloc特性）。
            material_arrays[spec.material_id] = np.empty(n, dtype=object)
        elif spec.dtype == "boolean" and spec.bool_default == "false":
            material_arrays[spec.material_id] = np.zeros(n, dtype=bool)
        else:  # numeric、またはbool_default="nan"のboolean（surface_good等）
            material_arrays[spec.material_id] = np.full(n, np.nan)

    # 0次フィルタ判定用の生フラグ（highway種別・bicycle=noタグ）は
    # `hard_filters`（リクエストごとに変わりうる）を前提とせず、該当するかどうかの
    # 生の判定結果のみ持つ。有効/無効の絞り込みは呼び出し元（`compute_hard_filter_excluded`）
    # が行う——タイル単位でキャッシュする`build_static_edge_score_matrix`は
    # `hard_filters`をまだ知らない時点でこの関数を呼ぶため。
    highway_filter_flags: dict[str, np.ndarray] = {
        filter_name: np.zeros(n, dtype=bool) for filter_name in HARD_FILTER_HIGHWAY_TYPES
    }
    no_bicycle = np.zeros(n, dtype=bool)

    for i, (edge_id, edge) in enumerate(zip(edge_ids, edges)):
        edge_way_tags = way_tags.get(edge_id) if way_tags is not None else None

        if edge.highway is not None:
            for filter_name, highway_types in HARD_FILTER_HIGHWAY_TYPES.items():
                if edge.highway in highway_types:
                    highway_filter_flags[filter_name][i] = True
        if edge_way_tags is not None and tag_value_is(edge_way_tags, "bicycle", "no"):
            no_bicycle[i] = True

        ctx = MaterialExtractionContext(
            edge_id=edge_id,
            highway=edge.highway,
            way_tags=edge_way_tags,
            distance_km=edge.distance_m / 1000,
            elevation_attributes=elevation_attributes,
            surface_attributes=surface_attributes,
            designated_edge_ids=designated_edge_ids,
            metrics=metrics,
            accident_years_covered=accident_years_covered,
        )
        for spec in extractable_materials:
            value = spec.extractor(ctx)
            array = material_arrays[spec.material_id]
            if spec.dtype == "categorical":
                array[i] = value
            elif spec.dtype == "boolean" and spec.bool_default == "false":
                array[i] = bool(value) if value is not None else False
            elif spec.dtype == "boolean":  # bool_default="nan"
                if value is not None:
                    array[i] = 1.0 if value else 0.0
            elif value is not None:  # numeric
                array[i] = float(value)

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
            if has_route_facing_raw_value(definition):
                raw = axis_raw_value_array(definition, material_arrays_with_axes)
                if raw is not None:
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

    return BulkAxisEvaluation(
        edge_ids=edge_ids,
        distance_m=distance_m,
        bearing_deg=bearing_deg,
        highway_filter_flags=highway_filter_flags,
        no_bicycle=no_bicycle,
        gradient_percent=material_arrays["gradient_percent"],
        mid_lat=mid_lat,
        mid_lon=mid_lon,
        axis_arrays=axis_arrays,
        axis_raw_arrays=axis_raw_arrays,
        material_value_arrays=material_value_arrays,
        categorical_material_arrays=categorical_material_arrays,
    )


def compose_costs_from_axis_matrix(
    distance_m: np.ndarray,
    axis_arrays: Mapping[str, np.ndarray],
    weights: dict[str, float],
    penalty_strength: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """`_evaluate_axes_bulk`/`evaluate_dynamic_axis_arrays`が求めた軸別スコア配列群から、
    重み付き合成のcost・composite difficulty配列・軸別寄与度配列を求める
    （`compute_edge_costs_bulk`から切り出した合成フェーズ）。

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
    n = len(distance_m)
    score_terms = []
    weight_terms = []
    axis_weight_valid: list[tuple[str, np.ndarray, float, np.ndarray]] = []
    for axis_id, arr in axis_arrays.items():
        weight = weights.get(axis_id, 0.0)
        valid = ~np.isnan(arr)
        score_terms.append(np.where(valid, arr * weight, 0.0))
        weight_terms.append(np.where(valid, weight, 0.0))
        axis_weight_valid.append((axis_id, arr, weight, valid))
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
    for axis_id, arr, weight, valid in axis_weight_valid:
        with np.errstate(invalid="ignore", divide="ignore"):
            contribution = np.where(valid, arr * weight / weighted_weight_sums, np.nan)
        axis_contributions[axis_id] = np.where(weighted_weight_sums == 0, np.nan, contribution)

    # costの算出にだけ、重み付き軸が全欠損のEdgeへbbox内平均difficultyを
    # 代入する（composite自体は表示用にNaNのまま返す、上のdocstring参照）。
    bbox_mean = distance_weighted_difficulty_array(composite, distance_m)
    if bbox_mean is None:
        cost_difficulty = composite
    else:
        cost_difficulty = np.where(np.isnan(composite), bbox_mean, composite)
    # compute_cost_from_axis_scoresと同じ: difficultyがNaN(None相当)ならcostは距離そのもの
    # （割増なし）。
    penalty_multiplier = np.where(np.isnan(cost_difficulty), 1.0, 1.0 + penalty_strength * (cost_difficulty / 100))
    cost = round1_array(distance_m * penalty_multiplier)
    return cost, composite, axis_contributions


def compute_edge_costs_bulk(
    graph: RoadGraphLike,
    elevation_attributes: dict[str, ElevationAttribute],
    surface_attributes: dict[str, str | None],
    preference: RoutePreference,
    weather: WeatherConditions | None = None,
    way_tags: dict[str, dict[str, str]] | None = None,
    accident_years_covered: int = 0,
    designated_edge_ids: set[str] | None = None,
    penalty_strength: float = 1.0,
    max_average_grade_percent: float | None = None,
    weights: dict[str, float] | None = None,
    hard_filters: frozenset[str] | None = None,
    travel_speed_ms: float | None = None,
    metrics: Mapping[str, EdgeKeyedMetrics] | None = None,
) -> dict[str, EdgeCostResult]:
    """`compute_edge_cost`を全Edge分ループするのと同じ結果を、numpyのベクトル演算で
    算出する（`evaluation_service.evaluate_graph`専用）。

    抽出＋計算フェーズは`_evaluate_axes_bulk`（`build_static_edge_score_matrix`と共有）、
    重み付き合成フェーズは`compose_costs_from_axis_matrix`（同じく共有）が担う薄い
    ラッパー。

    材料を1件追加するときはmaterial_catalog.pyへ抽出関数を書いてカタログへ登録するだけで
    よく、この関数自体の変更は不要。スカラー版`compute_edge_cost`は削除せず、本関数との
    出力一致を検証する回帰テストのオラクルとして残す。

    `stop_count`/`intersection_count`/`accident_count`は実データ上ゼロ以上の整数
    （PostGIS事前集計、`domain/attributes.py: EdgeAttributeCounts`）であることを前提とし、
    「負値ならNone」という防御的ガードはここでは再現しない（実データでは到達しない
    分岐のため、ベクトル化の単純さを優先した）。

    `hard_filters`: `is_edge_allowed`と同じフィルタ名集合による上書き。省略時
    （既定None）は`DEFAULT_HARD_FILTERS`（全フィルタ常時有効）を使う。`travel_speed_ms`は
    風の材料に使う走行速度（m/s）で、`weather`を渡すときは必須。
    """
    resolved_weights = weights if weights is not None else preference.weights

    evaluation = _evaluate_axes_bulk(
        graph, elevation_attributes, surface_attributes, weather, travel_speed_ms, way_tags,
        accident_years_covered, designated_edge_ids, metrics,
    )
    if not evaluation.edge_ids:
        return {}

    hard_filter_excluded = compute_hard_filter_excluded(
        evaluation.highway_filter_flags, evaluation.no_bicycle, evaluation.gradient_percent,
        hard_filters, max_average_grade_percent,
    )
    # axis_contributions（3個目の戻り値）はEdgeCostResultが持たない
    # フィールドのため、この回帰テストオラクル経路では使わない。
    cost, composite, _axis_contributions = compose_costs_from_axis_matrix(
        evaluation.distance_m, evaluation.axis_arrays, resolved_weights, penalty_strength
    )

    # --- 出力構築（EdgeCostResult.model_construct: 値は内部計算済みでバリデーション不要） ---
    results: dict[str, EdgeCostResult] = {}
    for i, edge_id in enumerate(evaluation.edge_ids):
        if hard_filter_excluded[i]:
            results[edge_id] = EdgeCostResult.model_construct(
                edge_id=edge_id, cost=None, difficulty=None, allowed=False
            )
        else:
            difficulty_value = None if np.isnan(composite[i]) else float(composite[i])
            results[edge_id] = EdgeCostResult.model_construct(
                edge_id=edge_id, cost=float(cost[i]), difficulty=difficulty_value, allowed=True
            )
    return results


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
    highway_filter_flags: dict[str, np.ndarray]
    no_bicycle: np.ndarray
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


def build_static_edge_score_matrix(
    graph: RoadGraphLike,
    materials: "EdgeMaterialTable | Mapping[str, EdgeMaterialBundle]",
    accident_years_covered: int = 0,
) -> StaticEdgeScoreMatrix:
    """タイル読込時（`GraphService._get_or_build_tile_materials`）に1回だけ呼び、
    `StaticEdgeScoreMatrix`を構築する。`_evaluate_axes_bulk`（`compute_edge_costs_bulk`
    と共有する抽出＋計算フェーズ）へ`weather=None`で渡すことで、動的軸の列は自然にNaNのまま
    持たせる。

    `materials`は`EdgeMaterialTable`（タイルキャッシュ経路が持つ列指向表現）
    または`dict[str, EdgeMaterialBundle]`（`_build_search_materials_uncached`等、テスト・
    タイルキャッシュを経由しない経路）のいずれかを受け取る。`_evaluate_axes_bulk`が
    要求する形（way_tags・elevation_attributes・surface_attributes・designated_edge_idsと、
    数値の束`metrics`）へここで分解する。タイル読込時に1回だけ発生する変換で、探索の
    ホットパスには乗らない。`EdgeMaterialTable`は`to_legacy_dicts()`が、bundleの辞書は
    `edge_metrics_from_bundles`が、それぞれ同じ`metrics`を組み立てる。
    """
    if isinstance(materials, EdgeMaterialTable):
        legacy = materials.to_legacy_dicts()
        elevation_attributes = legacy.elevation_attributes
        surface_attributes = legacy.surface_attributes
        way_tags = legacy.way_tags
        designated_edge_ids = legacy.designated_edge_ids
        metrics = legacy.metrics
    else:
        elevation_attributes = {
            edge_id: bundle.elevation_attribute
            for edge_id, bundle in materials.items() if bundle.elevation_attribute is not None
        }
        surface_attributes = {edge_id: bundle.surface for edge_id, bundle in materials.items()}
        way_tags = {edge_id: bundle.way_tags for edge_id, bundle in materials.items()}
        designated_edge_ids = {edge_id for edge_id, bundle in materials.items() if bundle.is_designated}
        metrics = edge_metrics_from_bundles(materials)

    evaluation = _evaluate_axes_bulk(
        graph, elevation_attributes, surface_attributes, None, None, way_tags,
        accident_years_covered, designated_edge_ids, metrics,
    )
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
        highway_filter_flags=evaluation.highway_filter_flags,
        no_bicycle=evaluation.no_bicycle,
        gradient_percent=evaluation.gradient_percent,
        mid_lat=evaluation.mid_lat,
        mid_lon=evaluation.mid_lon,
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
            highway_filter_flags={name: np.array([], dtype=bool) for name in HARD_FILTER_HIGHWAY_TYPES},
            no_bicycle=np.array([], dtype=bool), gradient_percent=np.array([]),
            mid_lat=np.array([]), mid_lon=np.array([]),
        )
    if len(matrices) == 1:
        return matrices[0]

    axis_ids = matrices[0].axis_ids
    raw_axis_ids = matrices[0].raw_axis_ids
    material_ids = matrices[0].material_ids
    categorical_material_ids = matrices[0].categorical_material_ids
    all_edge_ids = [edge_id for matrix in matrices for edge_id in matrix.edge_ids]
    axis_scores = np.concatenate([matrix.axis_scores for matrix in matrices], axis=0)
    axis_raw_values = np.concatenate([matrix.axis_raw_values for matrix in matrices], axis=0)
    material_values = np.concatenate([matrix.material_values for matrix in matrices], axis=0)
    categorical_material_values = np.concatenate(
        [matrix.categorical_material_values for matrix in matrices], axis=0
    )
    distance_m = np.concatenate([matrix.distance_m for matrix in matrices])
    bearing_deg = np.concatenate([matrix.bearing_deg for matrix in matrices])
    # フィルタ名の集合は全タイルで同じ（`_evaluate_axes_bulk`が
    # `HARD_FILTER_HIGHWAY_TYPES`から一律に作る）ため、先頭タイルのキーで揃える。
    highway_filter_flags = {
        name: np.concatenate([matrix.highway_filter_flags[name] for matrix in matrices])
        for name in matrices[0].highway_filter_flags
    }
    no_bicycle = np.concatenate([matrix.no_bicycle for matrix in matrices])
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
        highway_filter_flags={name: flags[final_indices] for name, flags in highway_filter_flags.items()},
        no_bicycle=no_bicycle[final_indices],
        gradient_percent=gradient_percent[final_indices],
        mid_lat=mid_lat[final_indices],
        mid_lon=mid_lon[final_indices],
    )
