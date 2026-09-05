"""Evaluation Engine（仕様書26-33章）。

Road Attribute（domain/attributes.py）とRoute PreferenceからEdge Costを算出する。
Route Engineから独立させ、Route Engine自身は「勾配がきつい」「路面が悪い」といった
評価の中身を一切知らない設計を目指す（仕様書33章）。

Score（難易度換算）は既存の`domain/difficulty.py`（Step9で導入、地図の難易度レイヤー用。
0-100、値が大きいほど走りにくい絶対基準）をそのまま再利用する。ルート単位の可視化と
Edge単位のEvaluation Engineが同じ「難易度」の意味・スケールを共有することで、新しい
正規化方式を発明せず、評価基準の食い違いも避ける。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

import numpy as np
from pydantic import BaseModel, Field, model_validator

from app.domain.attributes import EdgeMaterialBundle, EdgeMaterialTable, ElevationAttribute, WayAttributeCounts
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    REQUEST_DYNAMIC_MATERIAL_IDS,
    default_axis_weights,
    dynamic_axis_topological_order,
    evaluate_axes_scalar,
    evaluate_axis_array,
    evaluate_axis_scalar,
    time_scoped_weights,
    topological_axis_order,
)
from app.domain.axis_templates import round1_array
from app.domain.difficulty import composite_difficulty, distance_weighted_difficulty_array
from app.domain.graph import EdgeLike, RoadGraphLike
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialExtractionContext
from app.domain.night import night_materials
from app.domain.recipe import bicycle_infra_flags_or_none, parse_lanes, parse_maxspeed, tag_value_is
from app.domain.road import classify_osm_surface
from app.domain.weather import WeatherConditions
from app.domain.wind import WindForecastSeries, wind_drag_ratio_array

# 〇次: ハード制約（設計プロンプト「評価システムの層構造再設計」の〇次フィルタ、
# 改善計画T140。仕様書29章のHard Constraintと同じ概念）。スコア計算には一切登場させず、
# ルーティンググラフから除外する。Costを上げるのではなく探索対象から除外する点は
# 従来どおりだが、T140でフィルタごとに名前を付け、将来レシピ単位（T141で導入する
# `hard_filters: list[str]`）で個別に有効/無効を選択できる構造にした。
#
# `motorway`は設計プロンプトが明示する高速道路（法的に自転車通行不可）。`trunk`は
# 設計プロンプトの〇次フィルタ表には無いが、既存実装がT100より前から除外対象に
# 含めていた判断（コメント「法的・実質的に通行できない」）を維持する。日本のtrunk
# （国道等の幹線道路）は法的には自転車通行可能な場合が多いが、本アプリの用途
# （ロードバイクの周回ルート生成）にとって「実質的に走りにくい・危険」という
# 実務判断として据え置く（挙動変更なし、T140は既存動作の名前付け・明文化のみ）。
# `no_bicycle`はOSMの`bicycle=no`タグ（改善計画T100で追加）。
HARD_FILTER_HIGHWAY_TYPES: dict[str, frozenset[str]] = {
    "motorway": frozenset({"motorway", "motorway_link"}),
    "trunk": frozenset({"trunk", "trunk_link"}),
}

# 現時点の既定レシピは全フィルタを常時有効にする（T141でレシピJSON化するまでの間、
# is_edge_allowedの`hard_filters`省略時のデフォルト値としても使う）。
DEFAULT_HARD_FILTERS: frozenset[str] = frozenset({"no_bicycle", "motorway", "trunk"})


class RoutePreference(BaseModel):
    """Evaluation Engineが使う重み（仕様書27章）。

    改善計画T221 Stage B: 軸ごとの固定フィールド（`elevation_weight`等）をやめ、
    axis_id（`domain/axis_definitions.py: AXIS_DEFINITIONS`のキー）をキーとする重み辞書へ
    一般化した。旧フィールド名→axis_idの手書き対応表（`AXIS_WEIGHT_FIELD_TO_AXIS_ID`）と
    変換関数`preference_to_axis_weights`は不要になり削除（呼び出し元は`preference.weights`を
    直接使う）。軸の増減はAXIS_DEFINITIONSの変更だけで本モデルへ自動反映される。

    `weights`は部分指定を許す（不足キーは各軸の`default_weight`で補完。ドメイン内部・
    テストの利便のため）。未知のキーはエラー。**API境界の「上書きするなら全軸を明示する」
    検証は`api/routers/routes.py: RoutePreferenceWeights`が担う**（省略時にクラス既定値が
    黙って入ることを避ける従来方針のまま）。

    軸再編の経緯（T138自転車インフラ統合・T139安全度廃止/night分離・T149交差点密度統合）は
    `docs/architecture.md` 7章とgit履歴参照。
    """

    weights: dict[str, float] = Field(default_factory=default_axis_weights)

    @model_validator(mode="after")
    def _validate_and_fill_weights(self) -> "RoutePreference":
        # 改善計画T292: 内部軸（is_published=False、他の公開軸から参照される専用の
        # 推定軸）は一般ユーザー・リクエストからの重み付け対象外。3次合成
        # （compute_edge_costs_bulk側）も公開軸のみをループするため、weights辞書の
        # キー集合をここで揃えておく。
        published_axis_ids = {axis_id for axis_id, d in AXIS_DEFINITIONS.items() if d.is_published}
        unknown = sorted(set(self.weights) - published_axis_ids)
        if unknown:
            raise ValueError(f"unknown axis_id in weights: {unknown} (known: {sorted(published_axis_ids)})")
        merged = default_axis_weights()
        merged.update(self.weights)
        # キー順をAXIS_DEFINITIONSの定義順（＝合成の加算順）へ正規化する。
        self.weights = {axis_id: merged[axis_id] for axis_id in AXIS_DEFINITIONS if axis_id in published_axis_ids}
        return self

    def with_weight(self, axis_id: str, value: float) -> "RoutePreference":
        """1軸の重みだけを差し替えたコピーを返す（T173のnight重み動的化等、
        リクエスト間で共有するインスタンスを汚染しないための生成ヘルパー）。

        改善計画T316フォローアップ: `axis_id`が現在の`weights`（＝現在の公開軸集合、
        `default_axis_weights()`参照）に無い場合は無変更の`self`をそのまま返す。
        以前はどんなaxis_idでも強制的にweightsへ追加してRoutePreferenceを再構築して
        おり、対象軸（night）が軸スタジオで非公開化されると`_validate_and_fill_weights`
        の「未知のaxis_id」チェックに引っかかり、road_graph_engine.pyのnight動的化
        （日中の全リクエストで必ず通る経路）が丸ごと500になる実障害があった
        （2026-08-25）。差し替え対象の軸自体が存在しない以上、差し替える意味も無いため、
        無変更で返すのが正しい既定動作。
        """
        if axis_id not in self.weights:
            return self
        return RoutePreference(weights={**self.weights, axis_id: value})

    def with_time_scope(self, active_scopes: frozenset[str] = frozenset()) -> "RoutePreference":
        """time_scope（AXIS_DEFINITIONS参照）が"always"以外の軸のうち、
        `active_scopes`に含まれないものの重みを0倍にしたコピーを返す
        （T173のnight動的化を汎用化したもの、改善計画T352。`with_weight`と同じく
        リクエスト間で共有するインスタンスを汚染しない生成ヘルパー）。"""
        overridden = time_scoped_weights(self.weights, active_scopes)
        if overridden == self.weights:
            return self
        return RoutePreference(weights=overridden)


# 区間インスペクタ（改善計画T146）。「一次属性→二次軸→三次合成コスト」をレジストリの
# axis-catalog.jsonが持つラベル・単位と対で、単独でクリックされたway（ルート文脈が無い）
# について算出する。gradient/windはルート沿いの区間context（標高・出発時刻）が必要なため
# 常にavailable=Falseで返す（データ欠損ではなく、単独wayでは原理的に算出不能という区別。
# T145bで「事実はタイルに、解釈はクライアントに」方針を採ったが、ここでの合成コストは
# クリックのたびに1回計算するだけの参照用途で共有キャッシュに乗らないため、サーバー側で
# 正確に計算してよい＝タイル焼き込みの制約は適用されない）。


class AxisInspectorAxis(BaseModel):
    axis_id: str
    difficulty: float | None
    weight: float
    available: bool


class AxisInspectorResult(BaseModel):
    highway: str | None
    tags: dict[str, str]
    is_designated: bool
    axes: list[AxisInspectorAxis]
    # 取得可能な軸だけの加重平均（`composite_difficulty`と同じ「データ無しは除外し
    # 残りの重みで再正規化」方針）。1つも取得できなければNone。
    composite_difficulty: float | None
    # 全8軸の重み合計に対する、取得できた軸の重み合計の割合（0-1）。フロントが
    # 「◯%相当の軸のみで算出」という参考値である旨を示すために使う。
    covered_weight_fraction: float | None


def axis_inspector_breakdown(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool,
    way_counts: WayAttributeCounts | None,
    accident_years_covered: int,
    preference: RoutePreference | None = None,
) -> AxisInspectorResult:
    """区間インスペクタの内訳を算出する純関数。`way_counts`は
    `RoadGraphRepository.get_way_attribute_counts`の戻り値で、Noneなら事故密度・
    停止密度は算出不能（available=False）として扱う。
    """
    weights = (preference or RoutePreference()).weights

    surface_good = classify_osm_surface(tags.get("surface"))
    car_stress_bicycle_infra_flags = bicycle_infra_flags_or_none(tags, highway) or {}
    maxspeed_kmh = parse_maxspeed(tags)
    lanes_count = parse_lanes(tags)
    motor_vehicle_no = tag_value_is(tags, "motor_vehicle", "no")

    length_km = None
    accident_count = stop_count = intersection_count = None
    if way_counts is not None:
        accident_count, stop_count, intersection_count = (
            way_counts.accident_count, way_counts.stop_count, way_counts.intersection_count,
        )
        if way_counts.length_m > 0:
            length_km = way_counts.length_m / 1000.0

    stop_per_km = stop_count / length_km if length_km and stop_count is not None else None
    intersection_per_km = intersection_count / length_km if length_km and intersection_count is not None else None
    accident_per_km_year = None
    if length_km and accident_count is not None and accident_years_covered > 0:
        accident_per_km_year = (accident_count / length_km) / accident_years_covered

    # 改善計画T221 Stage B/C: 軸ごとのハードコードをやめ、AXIS_DEFINITIONSをループする。
    # gradient/windの材料（勾配%・風ペナルティ）は単独wayでは算出不能（ルート文脈が必要）
    # なためNoneのまま渡す＝常にavailable=Falseとして扱われる（データ欠損の軸と同じ
    # 「Noneは合成から除外」動作に自然に乗る）。改善計画T292: car_stress軸が内部軸5つを
    # 参照する階層構造になったため、compute_edge_axis_scoresと同じ依存順評価
    # （topological_axis_order）を使う。内部軸は`available=False`相当の扱いのため
    # 最終結果（axes）からは除外し、公開軸のみを返す（旧来のAPI応答形状を維持）。
    # 改善計画T341: categorical材料bicycle_infraはT336でcar_stress軸から外れ
    # 正規化フラグ（car_stress_bicycle_infra_flags）へ置き換わったため、ここでは渡さない
    # （どの軸も参照しない値をここで計算・格納するのは無駄なため削除した）。
    materials: dict[str, object] = {
        "gradient_percent": None,
        **{material_id: None for material_id in REQUEST_DYNAMIC_MATERIAL_IDS},
        "surface_good": surface_good,
        "stop_count_per_km": stop_per_km,
        "intersection_count_per_km": intersection_per_km,
        "accident_count_per_km_year": accident_per_km_year,
        "highway": highway,
        **car_stress_bicycle_infra_flags,
        "maxspeed_kmh": maxspeed_kmh,
        "lanes_count": lanes_count,
        "is_designated": is_designated,
        "motor_vehicle_no": motor_vehicle_no,
        **night_materials(tags),
    }
    scores, _ = evaluate_axes_scalar(materials)

    axes = [
        AxisInspectorAxis(axis_id=axis_id, difficulty=score, weight=weights.get(axis_id, 0.0), available=score is not None)
        for axis_id, score in scores.items()
    ]

    composite = composite_difficulty([(score, weights.get(axis_id, 0.0)) for axis_id, score in scores.items()])
    total_weight = sum(weights.values())
    covered_weight = sum(weights.get(axis_id, 0.0) for axis_id, score in scores.items() if score is not None)
    covered_fraction = round(covered_weight / total_weight, 3) if total_weight > 0 else None

    return AxisInspectorResult(
        highway=highway,
        tags=tags,
        is_designated=is_designated,
        axes=axes,
        composite_difficulty=composite,
        covered_weight_fraction=covered_fraction,
    )


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


def is_edge_allowed(
    edge: EdgeLike,
    way_tags: dict[str, str] | None = None,
    hard_filters: frozenset[str] | None = None,
    elevation_attribute: ElevationAttribute | None = None,
    max_average_grade_percent: float | None = None,
) -> bool:
    """Hard Constraint（仕様書29章、〇次フィルタ）。highwayタグが`hard_filters`で有効な
    道路種別フィルタに該当するか、または`bicycle=no`（`no_bicycle`フィルタ、改善計画T100で
    追加）が明示されているかを判定する。

    `hard_filters`省略時は`DEFAULT_HARD_FILTERS`（現行の全フィルタ常時有効、改善計画T140）を
    使う。T141でレシピJSON化した際、レシピの`hard_filters`フィールドをそのまま渡せる形。

    highwayタグが無い（不明）場合、way_tagsが無い（未取得）場合は除外しない。判断材料が
    無いEdgeまで一律除外すると経路探索対象が過度に狭まるため、不明な場合は許可し
    Soft Constraint側の評価に委ねる（carStress/bicycle_infra評価と同じway_tags=None時の
    扱い、compute_edge_costのdocstring参照）。

    `motor_vehicle=no`（自転車可の車両通行禁止）はここでは扱わない。自転車は法的に
    通行可能なため〇次のハード除外対象にはせず、二次軸（車ストレス・旧安全度）側の
    「該当区間は最善値へ固定」という特例として維持する（改善計画T140での方針確認、
    docs/architecture.md 7章参照）。

    `max_average_grade_percent`（改善計画T218a、T12 ADR原則5: 0次ハードフィルタの
    しきい値調整可能化）が指定され、かつ`elevation_attribute.average_grade`が取得済み
    （事前計算バッチ未実行のEdgeはNoneのため対象外＝許可のまま）の場合、その絶対値
    （登り・下りどちらの急勾配も対象）がしきい値を超えるEdgeを除外する。未指定
    （既定None）なら従来どおり勾配による除外は行わない。
    """
    active_filters = hard_filters if hard_filters is not None else DEFAULT_HARD_FILTERS
    if edge.highway is not None:
        for filter_name, highway_types in HARD_FILTER_HIGHWAY_TYPES.items():
            if filter_name in active_filters and edge.highway in highway_types:
                return False
    if "no_bicycle" in active_filters and way_tags is not None and tag_value_is(way_tags, "bicycle", "no"):
        return False
    if (
        max_average_grade_percent is not None
        and elevation_attribute is not None
        and elevation_attribute.average_grade is not None
        and abs(elevation_attribute.average_grade) > max_average_grade_percent
    ):
        return False
    return True


def compute_routable_node_ids(
    graph: RoadGraphLike,
    edge_ids: list[str],
    hard_filter_excluded: np.ndarray,
) -> set[str]:
    """0次ハードフィルタで除外されなかった（`hard_filter_excluded[i]`がFalse）Edgeが
    1本以上あるNode ID集合を返す（改善計画T256の主旨をlazy評価向けに移植したもの、
    `docs/tasks/T529.md`。改善計画T546でEdgeMaterialBundle経由の判定からスコア行列の
    生配列ベースへ置き換え）。

    探索用グラフ（`domain/routing.py: LazyRoadGraph`）はHard Constraintをグラフ構造では
    なくコスト（`math.inf`）で表現するため、「実際に経路探索可能なNode」の判定は
    Hard Constraintだけを別途・軽量に評価して得る必要がある。

    改善計画T546: 以前は`materials`（EdgeMaterialBundle辞書）へ`.get(edge_id)`した上で
    `is_edge_allowed`をEdgeごとに呼んでいたが、この判定は`StaticEdgeScoreMatrix`の
    `is_motorway`/`is_trunk`/`no_bicycle`/`gradient_percent`列から`compute_hard_filter_
    excluded`が求める`excluded`配列と全く同じ内容（呼び出し元
    `road_graph_engine.py: _build_search_graph`がコスト配列を`inf`にする判定に使うのと
    同じ配列）である。呼び出し元がその配列をそのまま渡すことで、本関数は
    `EdgeMaterialTable`/`EdgeMaterialBundle`辞書への依存を持たない
    （タイル材料キャッシュの復元コストとは独立になる、docs/tasks/T546.md「対応方針」
    項目5参照）。`edge_ids`は`hard_filter_excluded`と同じ行順（`StaticEdgeScoreMatrix.
    edge_ids`）。
    """
    routable: set[str] = set()
    edges = graph.edges
    for edge_id, excluded in zip(edge_ids, hard_filter_excluded.tolist()):
        if excluded:
            continue
        edge = edges.get(edge_id)
        if edge is None:
            continue
        routable.add(edge.from_node_id)
        routable.add(edge.to_node_id)
    return routable


def compute_dynamic_edge_materials(
    edge: EdgeLike, weather: WeatherConditions | None, travel_speed_ms: float | None
) -> dict[str, float | None]:
    """Edge1本ぶんの動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`の各材料id→値）を、Edgeの
    進行方向（`edge.bearing_deg`、from_node→to_node）・出発時点の風・走行速度から求める。
    風が無い、またはbearing未計算のEdgeは全材料None（データ無し）。

    `DYNAMIC_MATERIAL_EVALUATORS`（配列版）を長さ1の配列で呼ぶ薄いラッパーのため、
    スカラー経路とbulk/動的軸経路の式が乖離しない。風はEdgeに永続保存しない（動的データで
    ありRoad Attributeとして扱わない）。
    """
    if weather is None or edge.bearing_deg is None:
        return {material_id: None for material_id in REQUEST_DYNAMIC_MATERIAL_IDS}
    if travel_speed_ms is None:
        raise ValueError("compute_dynamic_edge_materials: travel_speed_ms is required when weather is given")
    context = DynamicAxisRequestContext(
        bearing_deg=np.array([edge.bearing_deg], dtype=float), weather=weather, travel_speed_ms=travel_speed_ms,
    )
    result: dict[str, float | None] = {}
    for material_id, array in evaluate_dynamic_material_arrays(context).items():
        value = float(array[0])
        result[material_id] = None if np.isnan(value) else value
    return result


def compute_edge_axis_scores(
    edge: EdgeLike,
    elevation_attribute: ElevationAttribute | None,
    surface_type: str | None,
    weather: WeatherConditions | None = None,
    stop_count: int | None = None,
    way_tags: dict[str, str] | None = None,
    intersection_count: int | None = None,
    accident_count: int | None = None,
    accident_years_covered: int = 0,
    is_designated: bool = False,
    travel_speed_ms: float | None = None,
) -> dict[str, float]:
    """二次: 一次属性から軸別スコア（axis_id→0-100のdifficulty）を算出する
    （改善計画T142、設計プロンプト「評価システムの層構造再設計」の二次そのもの）。

    返り値のキーは`domain/registry_defaults.py`が登録するaxis_id
    （`gradient`/`wind`/`surface_q`/`stop_density`/`car_stress`/`accident`/`night`）と一致する。
    評価できなかった軸（Noneのdifficulty）はキー自体を辞書へ含めない（三次側の
    `compute_cost_from_axis_scores`が「データ無しは合成から除外」する既存方針と対応する）。
    Hard Constraintの判定（`is_edge_allowed`）はここでは行わない（呼び出し元の責務、
    `compute_edge_cost`のdocstring参照）。

    `stop_count`はこのEdge上の信号・横断歩道・一時停止・踏切の合計個数（静的道路属性P1）。
    Noneはデータ無し（未評価、0個と区別する）。
    `way_tags`はこのEdgeのosm_way_idに対応する許可リストタグ（静的道路属性P0、
    車ストレス・夜間評価の入力）。Noneはデータ未取得（repository未注入等）を表し両軸とも
    評価しない（改善計画T292: highway由来の車ストレス内部軸もway_tags未取得時は
    意図的にNoneにして評価しない。旧ロジックと同じ「way_tags無し=car_stress未評価」を
    維持するため）。
    `intersection_count`はこのEdge周辺の交差点（次数3以上のNode）の件数（静的道路属性P1残り、
    改善計画T149でstop_density軸への補助入力へ変更）。Noneはデータ無し（未評価、0件と区別する）。
    `accident_count`はこのEdge周辺の事故（accident_points）の件数（外部静的データソース
    T50）。Noneはデータ無し（未評価、0件と区別する）。`accident_years_covered`は事故データの
    収録年数（`AttributeRepository.get_accident_years_covered`）で、密度を件/(km・年)へ
    正規化するために使う。
    `is_designated`はこのEdgeがKSJ N10/N12（緊急輸送道路・重要物流道路）に該当するか
    （外部静的データソース T51）。車ストレスへの補正のみに使う。
    `travel_speed_ms`は風の材料（走行速度依存）に使う走行速度（m/s）。`weather`を渡すときは
    必須（省略すると即座に失敗する）。
    """
    materials = _resolve_static_edge_materials(
        edge, elevation_attribute, surface_type, stop_count, way_tags,
        intersection_count, accident_count, accident_years_covered, is_designated,
    )
    materials.update(compute_dynamic_edge_materials(edge, weather, travel_speed_ms))
    # 改善計画T292: 軸は他の軸のdifficultyをmaterialとして参照できる（内部軸→公開軸の
    # 階層構造）。依存先（参照される軸）を先に評価し、結果をmaterialsへ混ぜ込みながら
    # 進めることで、参照する側は追加のAPIなしに`materials.get(axis_id)`で読める
    # （`evaluate_axes_scalar`参照）。ここでは値が算出できなかった公開軸のキー自体を
    # 呼び出し元（RouteSegmentDetail構築側）へ渡さないよう、Noneのキーを落とす
    # （`axis_inspector_breakdown`はavailable判定のためNoneのキーを残したまま返す点が
    # 異なる）。
    scores, _ = evaluate_axes_scalar(materials)
    return {axis_id: value for axis_id, value in scores.items() if value is not None}


def _resolve_static_edge_materials(
    edge: EdgeLike,
    elevation_attribute: ElevationAttribute | None,
    surface_type: str | None,
    stop_count: int | None,
    way_tags: dict[str, str] | None,
    intersection_count: int | None,
    accident_count: int | None,
    accident_years_covered: int,
    is_designated: bool,
) -> dict[str, object]:
    """`compute_edge_axis_scores`が使う、風以外の一次属性→材料解決ロジック。
    戻り値は動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）のキーを含まない——Edgeの材料だけで
    決まりリクエスト間で不変な部分のみを担当する（風の組み込みは呼び出し元の責務）。
    パラメータの意味は`compute_edge_axis_scores`のdocstring参照。
    """
    gradient_percent = elevation_attribute.average_grade if elevation_attribute else None
    is_good_surface = classify_osm_surface(surface_type)
    stop_count_per_km = stop_count / (edge.distance_m / 1000) if stop_count is not None and edge.distance_m > 0 else None
    intersection_count_per_km = (
        intersection_count / (edge.distance_m / 1000) if intersection_count is not None and edge.distance_m > 0 else None
    )
    accident_count_per_km_year = (
        accident_count / (edge.distance_m / 1000) / accident_years_covered
        if accident_count is not None and edge.distance_m > 0 and accident_years_covered > 0
        else None
    )
    # 改善計画T292: 車ストレスは専用Pythonレシピ（car_stress_level等）を廃止し、
    # AXIS_DEFINITIONSの内部軸5つ+公開軸1つの階層構造（axis_definitions.py:
    # "car_stress_highway_base"等のコメント参照）で再現する。ここでは一次材料
    # （highway/自転車インフラ正規化フラグ4種/maxspeed_kmh/lanes_count/is_designated/
    # motor_vehicle_no）を素直に抽出するだけで、highway基準値以外の判定式は一切持たない。
    #
    # way_tagsがNone（データ未取得）の場合、旧ロジックはcar_stress全体を評価しなかった
    # （car_stress_level(...) if way_tags is not None else None）。この挙動を保つため、
    # "highway"材料自体をway_tags未取得時はNoneにする（edge.highwayが分かっていても
    # あえて使わない）。highway基準値軸はrequired=Trueで公開軸car_stressの最初のterm
    # のため、これがNoneなら公開軸全体がNoneになり旧挙動と一致する。
    highway_for_car_stress = edge.highway if way_tags is not None else None
    car_stress_bicycle_infra_flags = bicycle_infra_flags_or_none(way_tags, edge.highway) or {}
    maxspeed_kmh = parse_maxspeed(way_tags) if way_tags is not None else None
    lanes_count = parse_lanes(way_tags) if way_tags is not None else None
    motor_vehicle_no = tag_value_is(way_tags, "motor_vehicle", "no") if way_tags is not None else None
    # 改善計画T220: 合成composite計算はここでは行わない（実際の合成は
    # `compute_cost_from_axis_scores`が実重みで別途行う。以前ダミー重みの
    # `evaluate_axis_difficulties`を呼んで無駄な合成が発生していた経緯はT220参照）。
    # 改善計画T221 Stage B/C: 軸ごとに変換関数を1行ずつ呼ぶハードコードをやめ、
    # 解決済み材料の辞書に対してAXIS_DEFINITIONS（domain/axis_definitions.py）を
    # ループする。既存テンプレート＋既存材料で表現できる新しい軸は、定義データの
    # 追加だけでここへ反映される。
    return {
        "gradient_percent": gradient_percent,
        "surface_good": is_good_surface,
        "stop_count_per_km": stop_count_per_km,
        "intersection_count_per_km": intersection_count_per_km,
        "accident_count_per_km_year": accident_count_per_km_year,
        "highway": highway_for_car_stress,
        **car_stress_bicycle_infra_flags,
        "maxspeed_kmh": maxspeed_kmh,
        "lanes_count": lanes_count,
        "is_designated": is_designated,
        "motor_vehicle_no": motor_vehicle_no,
        **night_materials(way_tags),
    }


def compute_cost_from_axis_scores(
    distance_m: float,
    axis_scores: dict[str, float],
    weights: dict[str, float],
    penalty_strength: float = 1.0,
    bbox_mean_difficulty: float | None = None,
) -> tuple[float, float | None]:
    """三次: 重みベクトル×軸別スコアのみからコストを算出する純関数
    （`cost = length × (1 + P × Σᵢ wᵢ × axisᵢ / 100)`、設計プロンプト「評価システムの
    層構造再設計」の三次そのもの。改善計画T142の完了条件どおり、シグネチャに一次属性名を
    一切含まない）。

    `axis_scores`にキーが存在しない軸は合成から除外され、残りの軸の重みで再正規化される
    （`domain/difficulty.py: composite_difficulty`と同じ「データ無しは除外」方針）。
    `weights`に対応するキーが無い軸は重み0として扱う。

    `penalty_strength`（P、改善計画T218・T12 ADR原則1）は割増率の強さを調整するリクエスト
    パラメータ。既定1.0は従来どおりの挙動（最悪でも距離2倍）。P=0で常に`cost=distance_m`
    （難易度を一切考慮しない最短距離探索）、Pを上げるほど悪路が強く避けられる
    （P=4なら最悪の道は距離5倍相当）。`cost >= distance_m`（P>=0の間は常に成り立つ）という
    不変条件は維持し、将来の探索高速化（直線距離を下界とするA*等）の前提を崩さない。

    `bbox_mean_difficulty`（改善計画T552）: 重み付き軸すべてが欠損（`difficulty is None`）の
    ときにコスト計算だけへ代入する値（呼び出し元がbboxの実データから求めた距離加重平均
    difficulty、`domain/difficulty.py: distance_weighted_difficulty_array`参照）。省略時
    （既定None）は従来どおり`cost=distance_m`（割増なし）。戻り値の`difficulty`（表示用）は
    この代入の影響を受けず、欠損なら常にNoneのまま返す——探索コストのみ補完し表示は変えない
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
    stop_count: int | None = None,
    way_tags: dict[str, str] | None = None,
    intersection_count: int | None = None,
    accident_count: int | None = None,
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

    改善計画T142で、一次属性→二次（軸別スコア）の算出を`compute_edge_axis_scores`へ、
    軸別スコア→三次（コスト合成）を`compute_cost_from_axis_scores`へ分離した。この関数
    自体は「一次属性を受け取って一気通貫でコストを出したい」既存呼び出し元向けの
    薄い合成関数として残す（挙動は分離前と完全に同一、`test_evaluation.py`で回帰確認済み）。
    三次のみを直接使いたい場合（例: レジストリ・Recipe駆動の呼び出し）は
    `compute_cost_from_axis_scores`を直接使う。

    パラメータの意味は`compute_edge_axis_scores`のdocstring参照（Hard Constraint判定
    `is_edge_allowed`はこの関数が担う。`max_average_grade_percent`はis_edge_allowedへ
    そのまま渡す、改善計画T218a）。

    `weights`（改善計画T220、T12 Stage 2）: 呼び出し元が事前解決した重み辞書を渡すと
    そのまま使う。省略時（既定None）は`preference.weights`を使う（T221 Stage Bで
    RoutePreference自体がaxis_idキーの辞書になったため、旧`preference_to_axis_weights`の
    ような変換は不要になった。T220当時の毎Edge変換オーバーヘッドの経緯は
    `backend/benchmarks/README.md`参照）。

    `hard_filters`（改善計画T266）はそのまま`is_edge_allowed`へ渡す（省略時は
    `DEFAULT_HARD_FILTERS`）。

    `bbox_mean_difficulty`（改善計画T552）はそのまま`compute_cost_from_axis_scores`へ渡す
    （同関数のdocstring参照）。`travel_speed_ms`はそのまま`compute_edge_axis_scores`へ渡す
    （`weather`を渡すときは必須）。
    """
    if not is_edge_allowed(
        edge,
        way_tags,
        hard_filters=hard_filters,
        elevation_attribute=elevation_attribute,
        max_average_grade_percent=max_average_grade_percent,
    ):
        # 改善計画T533フォローアップ: bulk版（compute_edge_costs_bulk）が既に採用している
        # model_construct（値は内部計算済みでバリデーション不要）と同じ最適化。lazy評価
        # （改善計画T529）でこの関数が探索のホットパス（訪れたEdgeごとに最大24回）に
        # なったため、cProfile実測でPydanticバリデーションが無視できないコストと判明した
        # （edge_id/cost/difficulty/allowedはすべて内部で計算済みの値で、外部入力の検証は
        # 元々不要だった）。
        return EdgeCostResult.model_construct(edge_id=edge.edge_id, cost=None, difficulty=None, allowed=False)

    axis_scores = compute_edge_axis_scores(
        edge, elevation_attribute, surface_type, weather, stop_count, way_tags,
        intersection_count, accident_count, accident_years_covered, is_designated,
        travel_speed_ms=travel_speed_ms,
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
    再現できず、ちょうど.X5境界の値で最終丸め結果が食い違う（実測: 実データのEdgeで
    単純逐次加算は0.8200000000000001、`sum()`は0.82と異なる浮動小数点値になり、
    composite=41.25の丸めが41.3 vs 41.2に分かれた）。本関数はNeumaier加算をn件分まとめて
    配列演算で行うことで、`sum()`と同じ結果をEdge数万件規模でもPythonループ無しで再現する。
    """
    total = np.zeros_like(terms[0], dtype=float)
    compensation = np.zeros_like(terms[0], dtype=float)
    for term in terms:
        t = total + term
        correction = np.where(np.abs(total) >= np.abs(term), (total - t) + term, (term - t) + total)
        compensation += correction
        total = t
    return total + compensation


@dataclass(frozen=True, slots=True)
class BulkAxisEvaluation:
    """`compute_edge_costs_bulk`の抽出＋計算フェーズ（改善計画T536で`_evaluate_axes_bulk`
    として切り出し）の結果。bbox全体一括評価（`compute_edge_costs_bulk`本体）と、タイル
    単位の静的スコア行列構築（`build_static_edge_score_matrix`）の両方から共有する。

    `axis_arrays`は公開軸のみ・依存順（`topological_axis_order`のサブセット）。重み付き
    合成（Neumaier加算・cost算出）は含まない——`weights`が定まった時点で呼び出し元が
    `compose_costs_from_axis_matrix`へ渡す。0次フィルタは`is_motorway`/`is_trunk`/
    `no_bicycle`/`gradient_percent`の生フラグのみを持ち、`hard_filters`/
    `max_average_grade_percent`（リクエストごとに変わりうる）による絞り込みは
    `compute_hard_filter_excluded`が別途行う。
    """

    edge_ids: list[str]
    distance_m: np.ndarray
    bearing_deg: np.ndarray
    is_motorway: np.ndarray
    is_trunk: np.ndarray
    no_bicycle: np.ndarray
    gradient_percent: np.ndarray
    # Edge中点の緯度経度（from/toノードの平均）。探索前に各Edgeの通過予定時刻を基準点からの
    # 直線距離で推定するために使う。
    mid_lat: np.ndarray
    mid_lon: np.ndarray
    axis_arrays: dict[str, np.ndarray]


def _evaluate_axes_bulk(
    graph: RoadGraphLike,
    elevation_attributes: dict[str, ElevationAttribute],
    surface_attributes: dict[str, str | None],
    weather: WeatherConditions | None,
    travel_speed_ms: float | None,
    stop_counts: dict[str, int] | None,
    way_tags: dict[str, dict[str, str]] | None,
    intersection_counts: dict[str, int] | None,
    accident_counts: dict[str, int] | None,
    accident_years_covered: int,
    designated_edge_ids: set[str] | None,
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
    stop_counts = stop_counts or {}
    intersection_counts = intersection_counts or {}
    accident_counts = accident_counts or {}
    designated_edge_ids = designated_edge_ids or set()

    edge_ids = list(graph.edges.keys())
    n = len(edge_ids)
    if n == 0:
        # 改善計画T536フォローアップ（本番実測で判明、2026-09-02）: axis_arraysを空dict
        # {}のまま返すと、build_static_edge_score_matrixが構築するaxis_scoresの列数が
        # 0になり、他タイル（列数=公開軸数、例えば8）とcombine_static_edge_score_matrices
        # でnp.concatenateする際に「dimension 1のサイズ不一致」でValueErrorになる
        # （本番Oracle VM、東京駅30km・split済み条件で実際に発生。bbox内の1タイルが
        # Edge0件[空タイル、道路データが疎らな区画]だったケース）。Edge0件でも
        # 「公開軸それぞれに対応する長さ0の配列」を持たせることで、他タイルと同じ列数
        # （shape=(0, 公開軸数)）に揃える。列の並び順は非空タイルの計算フェーズ
        # （下記for文）と同じtopological_axis_orderを使い、is_published判定も同じにする
        # ——combine_static_edge_score_matricesは最初のタイルのaxis_idsをそのまま
        # 全体のaxis_idsとして採用するため、列の並びが全タイルで一致している必要がある。
        empty_axis_arrays = {
            axis_id: np.array([])
            for axis_id in topological_axis_order(AXIS_DEFINITIONS)
            if AXIS_DEFINITIONS[axis_id].is_published
        }
        return BulkAxisEvaluation(
            edge_ids=[],
            distance_m=np.array([]),
            bearing_deg=np.array([]),
            is_motorway=np.array([], dtype=bool),
            is_trunk=np.array([], dtype=bool),
            no_bicycle=np.array([], dtype=bool),
            gradient_percent=np.array([]),
            mid_lat=np.array([]),
            mid_lon=np.array([]),
            axis_arrays=empty_axis_arrays,
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

    # --- 抽出フェーズ（改善計画T280: MATERIAL_CATALOGのextractor宣言へ委譲） ---
    extractable_materials = [spec for spec in MATERIAL_CATALOG.values() if spec.extractor is not None]
    # 改善計画T343: 配列はMATERIAL_CATALOG全材料ぶん確保する（抽出ループは
    # extractable_materialsのみ回す＝extractor未設定材料[oneway/designation/
    # is_emergency_transport/is_critical_logistics等、「トリガー付きDEFER」設計原則9]は
    # 既定値[NaN/False]のまま残る）。以前はextractable_materialsのみ確保しており、
    # そのような材料をMaterialTerm等で参照するGUI作成軸（`_check_materials_are_known`は
    # is_known_materialのみ検証しextractor有無は見ないため、軸スタジオから素朴に作成
    # できてしまう）を評価するとevaluate_axis_arrayの`materials[term.material]`が
    # KeyErrorで/api/routes/generate自体を落としていた（スカラー版evaluate_axis_scalarは
    # `materials.get(...)`のためこの経路では発生しない非対称性があった）。全材料ぶん
    # 確保することで「材料はあるがデータが無い」という既存の意味論（欠損）へ揃え、
    # スカラー版と同じグレースフルデグレード（その軸だけ恒久的に欠損扱い）にする。
    material_arrays: dict[str, np.ndarray] = {}
    for spec in MATERIAL_CATALOG.values():
        if spec.dtype == "categorical":
            # np.emptyのdtype=objectは要素をNone初期化する（Python object配列のcalloc特性）。
            material_arrays[spec.material_id] = np.empty(n, dtype=object)
        elif spec.dtype == "boolean" and spec.bool_default == "false":
            material_arrays[spec.material_id] = np.zeros(n, dtype=bool)
        else:  # numeric、またはbool_default="nan"のboolean（surface_good等）
            material_arrays[spec.material_id] = np.full(n, np.nan)

    # 改善計画T536: 0次フィルタ判定用の生フラグ（highway種別・bicycle=noタグ）は
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
            edge=edge,
            edge_id=edge_id,
            way_tags=edge_way_tags,
            distance_km=edge.distance_m / 1000,
            elevation_attributes=elevation_attributes,
            surface_attributes=surface_attributes,
            stop_counts=stop_counts,
            intersection_counts=intersection_counts,
            accident_counts=accident_counts,
            accident_years_covered=accident_years_covered,
            designated_edge_ids=designated_edge_ids,
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
    # 改善計画T292: スカラー版compute_edge_axis_scores（`evaluate_axes_scalar`）と同じ
    # 依存順評価（軸が他の軸のdifficultyをmaterialとして参照できる階層構造）。
    # material_arrays_with_axesへは内部軸も含め全軸の結果を混ぜ込む（公開軸が内部軸を
    # materialとして参照できる必要があるため）が、axis_arrays（下の合成対象）は
    # 公開軸のみに絞る（コードレビュー指摘の修正: 以前は内部軸もaxis_arraysへ含めて
    # いたが、内部軸のdefault_weight=0.0のため合成結果への影響自体は無かった
    # ——スカラー版のフィルタと揃え、無駄な計算・将来の重み設定変更時の暗黙の
    # リスクを無くす）。
    axis_arrays: dict[str, np.ndarray] = {}
    material_arrays_with_axes: dict[str, np.ndarray] = dict(material_arrays)
    for axis_id in topological_axis_order(AXIS_DEFINITIONS):
        definition = AXIS_DEFINITIONS[axis_id]
        arr = evaluate_axis_array(definition, material_arrays_with_axes)
        material_arrays_with_axes[axis_id] = arr
        if definition.is_published:
            axis_arrays[axis_id] = arr

    return BulkAxisEvaluation(
        edge_ids=edge_ids,
        distance_m=distance_m,
        bearing_deg=bearing_deg,
        is_motorway=highway_filter_flags.get("motorway", np.zeros(n, dtype=bool)),
        is_trunk=highway_filter_flags.get("trunk", np.zeros(n, dtype=bool)),
        no_bicycle=no_bicycle,
        gradient_percent=material_arrays["gradient_percent"],
        mid_lat=mid_lat,
        mid_lon=mid_lon,
        axis_arrays=axis_arrays,
    )


def compute_hard_filter_excluded(
    is_motorway: np.ndarray,
    is_trunk: np.ndarray,
    no_bicycle: np.ndarray,
    gradient_percent: np.ndarray,
    hard_filters: frozenset[str] | None = None,
    max_average_grade_percent: float | None = None,
) -> np.ndarray:
    """`_evaluate_axes_bulk`が返す生フラグから、リクエスト時点の`hard_filters`/
    `max_average_grade_percent`を反映した0次フィルタ除外の真偽値配列を求める
    （改善計画T536、`is_edge_allowed`のベクトル版）。省略時（既定None）は
    `DEFAULT_HARD_FILTERS`（全フィルタ常時有効）を使う。
    """
    active_hard_filters = hard_filters if hard_filters is not None else DEFAULT_HARD_FILTERS
    excluded = np.zeros(len(is_motorway), dtype=bool)
    if "motorway" in active_hard_filters:
        excluded |= is_motorway
    if "trunk" in active_hard_filters:
        excluded |= is_trunk
    if "no_bicycle" in active_hard_filters:
        excluded |= no_bicycle
    # 勾配の〇次ハードフィルタ（NaNとの比較は常にFalseになるため、勾配不明のEdgeへは
    # 従来どおり適用されない）。
    if max_average_grade_percent is not None:
        with np.errstate(invalid="ignore"):
            excluded |= np.abs(gradient_percent) > max_average_grade_percent
    return excluded


def compose_costs_from_axis_matrix(
    distance_m: np.ndarray,
    axis_arrays: Mapping[str, np.ndarray],
    weights: dict[str, float],
    penalty_strength: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """`_evaluate_axes_bulk`/`evaluate_dynamic_axis_arrays`が求めた軸別スコア配列群から、
    重み付き合成のcost・composite difficulty配列・軸別寄与度配列を求める（改善計画T536、
    `compute_edge_costs_bulk`から切り出した合成フェーズ。改善計画T550で軸別寄与度を追加）。

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
    difficultyを代入する（改善計画T552。呼び出し元のリクエストごとに実データから求まる
    値で、固定定数は使わない）。戻り値の`composite_difficulty`・`axis_contributions`
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
    # 改善計画T463: 公開軸が1つも無い場合はn件ぶんのゼロ配列を直接使う（下の
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
    # （実測: 385.949999999999988...→np.roundは386.0、round()は385.9）。
    # スカラー版composite_difficulty/compute_cost_from_axis_scoresの`round(x, 1)`と
    # 完全一致させるため、最終丸めのみ要素ごとにPythonの`round()`を適用する。
    composite = round1_array(composite)

    # 改善計画T550: 軸ごとの区間寄与度。compositeとは異なり、ここでは丸めない
    # （区間単位ではなくルート単位に距離加重平均した後、そちらで最終丸めする——
    # `RouteSegmentDetail.axis_difficulties`/`domain/route.py: merge_axis_difficulties`と
    # 同じ「区間単位は生値、ルート単位で丸め」という既存の扱いに揃える）。
    axis_contributions: dict[str, np.ndarray] = {}
    for axis_id, arr, weight, valid in axis_weight_valid:
        with np.errstate(invalid="ignore", divide="ignore"):
            contribution = np.where(valid, arr * weight / weighted_weight_sums, np.nan)
        axis_contributions[axis_id] = np.where(weighted_weight_sums == 0, np.nan, contribution)

    # 改善計画T552: costの算出にだけ、重み付き軸が全欠損のEdgeへbbox内平均difficultyを
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
    stop_counts: dict[str, int] | None = None,
    way_tags: dict[str, dict[str, str]] | None = None,
    intersection_counts: dict[str, int] | None = None,
    accident_counts: dict[str, int] | None = None,
    accident_years_covered: int = 0,
    designated_edge_ids: set[str] | None = None,
    penalty_strength: float = 1.0,
    max_average_grade_percent: float | None = None,
    weights: dict[str, float] | None = None,
    hard_filters: frozenset[str] | None = None,
    travel_speed_ms: float | None = None,
) -> dict[str, EdgeCostResult]:
    """`compute_edge_cost`を全Edge分ループするのと同じ結果を、numpyのベクトル演算で
    算出する（改善計画T221/T240、`EvaluationService.evaluate_graph`専用）。

    改善計画T536: 抽出＋計算フェーズは`_evaluate_axes_bulk`（`build_static_edge_score_matrix`
    と共有）、重み付き合成フェーズは`compose_costs_from_axis_matrix`（同じく共有）へ
    切り出した薄いラッパー。挙動は分離前と完全に同一（`tests/test_evaluation_bulk.py`の
    既存回帰テストで確認済み）。

    材料を1件追加するときはmaterial_catalog.pyへ抽出関数を書いてカタログへ登録するだけで
    よく、この関数自体の変更は不要。スカラー版`compute_edge_cost`は削除せず、本関数との
    出力一致を検証する回帰テストのオラクルとして残す。

    `stop_count`/`intersection_count`/`accident_count`は実データ上ゼロ以上の整数
    （PostGIS事前集計、`domain/attributes.py: EdgeAttributeCounts`）であることを前提とし、
    「負値ならNone」という防御的ガード（テスト専用の異常値入力を想定したもの、改善計画
    T320で削除済みのスカラー版互換ラッパが持っていた）はここでは再現しない（実データでは
    到達しない分岐のため、ベクトル化の単純さを優先した）。

    `hard_filters`（改善計画T266）: `is_edge_allowed`と同じフィルタ名集合による上書き。
    省略時（既定None）は`DEFAULT_HARD_FILTERS`（全フィルタ常時有効）を使う。
    `travel_speed_ms`は風の材料に使う走行速度（m/s）で、`weather`を渡すときは必須。
    """
    resolved_weights = weights if weights is not None else preference.weights

    evaluation = _evaluate_axes_bulk(
        graph, elevation_attributes, surface_attributes, weather, travel_speed_ms, stop_counts, way_tags,
        intersection_counts, accident_counts, accident_years_covered, designated_edge_ids,
    )
    if not evaluation.edge_ids:
        return {}

    hard_filter_excluded = compute_hard_filter_excluded(
        evaluation.is_motorway, evaluation.is_trunk, evaluation.no_bicycle, evaluation.gradient_percent,
        hard_filters, max_average_grade_percent,
    )
    # 改善計画T550: axis_contributions（3個目の戻り値）はEdgeCostResultが持たない
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
    ヒューリスティック用の生配列（改善計画T536）。全ての配列は`edge_ids`と同じ行順で
    揃う。`infrastructure/axis_score_cache.py`（Edge単位の辞書キャッシュ、T534。約1.3KB/
    Edge）の後継——本行列はEdgeあたり軸の数×8バイト程度で収まる。

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
    is_motorway: np.ndarray
    is_trunk: np.ndarray
    no_bicycle: np.ndarray
    gradient_percent: np.ndarray
    # Edge中点の緯度経度（`BulkAxisEvaluation.mid_lat`/`mid_lon`と同じ）。
    mid_lat: np.ndarray
    mid_lon: np.ndarray


def build_static_edge_score_matrix(
    graph: RoadGraphLike,
    materials: "EdgeMaterialTable | Mapping[str, EdgeMaterialBundle]",
    accident_years_covered: int = 0,
) -> StaticEdgeScoreMatrix:
    """改善計画T536: タイル読込時（`GraphService._get_or_build_tile_materials`）に1回だけ
    呼び、`StaticEdgeScoreMatrix`を構築する。`_evaluate_axes_bulk`（`compute_edge_costs_bulk`
    と共有する抽出＋計算フェーズ）へ`weather=None`で渡すことで、動的軸の列は自然にNaNのまま
    持たせる。

    `materials`は`EdgeMaterialTable`（改善計画T546、タイルキャッシュ経路が持つ列指向表現）
    または`dict[str, EdgeMaterialBundle]`（`_build_search_materials_uncached`等、テスト・
    タイルキャッシュを経由しない経路）のいずれかを受け取る。`_evaluate_axes_bulk`が
    要求する個別辞書（way_tags/elevation_attributes/...）へここで分解する——
    `compute_edge_costs_bulk`の既存の公開シグネチャ（個別辞書引数）を崩さないための
    変換で、タイル読込時に1回だけ発生する（探索のホットパスには乗らない）。
    `EdgeMaterialTable`は`to_legacy_dicts()`で自身が既に列指向で保持する内容を一括変換する。
    """
    if isinstance(materials, EdgeMaterialTable):
        legacy = materials.to_legacy_dicts()
        elevation_attributes = legacy.elevation_attributes
        surface_attributes = legacy.surface_attributes
        way_tags = legacy.way_tags
        stop_counts = legacy.stop_counts
        intersection_counts = legacy.intersection_counts
        accident_counts = legacy.accident_counts
        designated_edge_ids = legacy.designated_edge_ids
    else:
        elevation_attributes = {
            edge_id: bundle.elevation_attribute
            for edge_id, bundle in materials.items() if bundle.elevation_attribute is not None
        }
        surface_attributes = {edge_id: bundle.surface for edge_id, bundle in materials.items()}
        way_tags = {edge_id: bundle.way_tags for edge_id, bundle in materials.items()}
        stop_counts = {
            edge_id: bundle.attribute_counts.stop_count
            for edge_id, bundle in materials.items() if bundle.attribute_counts is not None
        }
        intersection_counts = {
            edge_id: bundle.attribute_counts.intersection_count
            for edge_id, bundle in materials.items() if bundle.attribute_counts is not None
        }
        accident_counts = {
            edge_id: bundle.attribute_counts.accident_count
            for edge_id, bundle in materials.items() if bundle.attribute_counts is not None
        }
        designated_edge_ids = {edge_id for edge_id, bundle in materials.items() if bundle.is_designated}

    evaluation = _evaluate_axes_bulk(
        graph, elevation_attributes, surface_attributes, None, None, stop_counts, way_tags,
        intersection_counts, accident_counts, accident_years_covered, designated_edge_ids,
    )
    axis_ids = list(evaluation.axis_arrays.keys())
    axis_scores = (
        np.stack([evaluation.axis_arrays[axis_id] for axis_id in axis_ids], axis=1)
        if axis_ids
        else np.empty((len(evaluation.edge_ids), 0))
    )
    return StaticEdgeScoreMatrix(
        edge_ids=evaluation.edge_ids,
        axis_ids=axis_ids,
        axis_scores=axis_scores,
        distance_m=evaluation.distance_m,
        bearing_deg=evaluation.bearing_deg,
        is_motorway=evaluation.is_motorway,
        is_trunk=evaluation.is_trunk,
        no_bicycle=evaluation.no_bicycle,
        gradient_percent=evaluation.gradient_percent,
        mid_lat=evaluation.mid_lat,
        mid_lon=evaluation.mid_lon,
    )


def combine_static_edge_score_matrices(matrices: list[StaticEdgeScoreMatrix]) -> StaticEdgeScoreMatrix:
    """複数タイルぶんの`StaticEdgeScoreMatrix`を、bbox全体1件分へ結合する（改善計画T536、
    `GraphService._build_search_materials_from_tile_cache`が複数z12タイルを1つの探索用
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
            is_motorway=np.array([], dtype=bool), is_trunk=np.array([], dtype=bool),
            no_bicycle=np.array([], dtype=bool), gradient_percent=np.array([]),
            mid_lat=np.array([]), mid_lon=np.array([]),
        )
    if len(matrices) == 1:
        return matrices[0]

    axis_ids = matrices[0].axis_ids
    all_edge_ids = [edge_id for matrix in matrices for edge_id in matrix.edge_ids]
    axis_scores = np.concatenate([matrix.axis_scores for matrix in matrices], axis=0)
    distance_m = np.concatenate([matrix.distance_m for matrix in matrices])
    bearing_deg = np.concatenate([matrix.bearing_deg for matrix in matrices])
    is_motorway = np.concatenate([matrix.is_motorway for matrix in matrices])
    is_trunk = np.concatenate([matrix.is_trunk for matrix in matrices])
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
        distance_m=distance_m[final_indices],
        bearing_deg=bearing_deg[final_indices],
        is_motorway=is_motorway[final_indices],
        is_trunk=is_trunk[final_indices],
        no_bicycle=no_bicycle[final_indices],
        gradient_percent=gradient_percent[final_indices],
        mid_lat=mid_lat[final_indices],
        mid_lon=mid_lon[final_indices],
    )


@dataclass(frozen=True, slots=True)
class DynamicAxisRequestContext:
    """動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）をリクエスト時にベクトル評価するための
    統一入力。Edgeの幾何配列とリクエスト単位の動的データ（風・走行速度）を束ねる。

    `DYNAMIC_MATERIAL_EVALUATORS`へ登録する各材料のevaluatorはこの1引数だけを受け取り
    材料配列を返す統一シグネチャにすることで、動的材料が増えても呼び出し側
    （`evaluate_dynamic_axis_arrays`、静的行列のNaN列を埋める処理）へ軸名・材料名の分岐を
    追加せず、この辞書へ1エントリ追加するだけで対応できる（フロントの
    `RAMP_AXES`/`buildAxisOverlayLayers`と同種の汎用ディスパッチ）。呼び出しはリクエスト
    あたり動的材料の数だけの設定フェーズであり、Edge単位のホットループには入らない。
    """

    bearing_deg: np.ndarray
    weather: WeatherConditions | None
    # 走行速度（m/s、リクエスト単位）。既定値を置かないのは、走行速度に依存する材料へ
    # 伝播漏れがあったとき既定値で黙って計算せず、構築時点で失敗させるため。
    travel_speed_ms: float
    # 時刻依存の材料向け: 起点の時別予報系列と、各Edgeの通過予定時刻（`start`からの経過
    # 時間[h]、`bearing_deg`と同じ行順）。3つとも揃っていればEdgeごとに通過予定時刻の値を
    # 引き、揃っていなければ`weather`（出発時点のスナップショット）を全Edgeへ一様に使う。
    wind_series: WindForecastSeries | None = None
    start: datetime | None = None
    passage_hours: np.ndarray | None = None

    def time_varying(self) -> bool:
        return self.wind_series is not None and self.start is not None and self.passage_hours is not None

    def wind_inputs(self) -> tuple[np.ndarray, np.ndarray] | None:
        """各Edgeに適用する（風速, 風向）。時別系列と通過予定時刻が揃っていればEdgeごとに
        その時刻の値、揃っていなければ出発時点のスナップショット（全Edge共通のスカラー）。
        風が無ければNone。"""
        if self.time_varying():
            return self.wind_series.sample(self.start, self.passage_hours)
        if self.weather is None:
            return None
        return np.asarray(self.weather.wind_speed_ms, dtype=float), np.asarray(self.weather.wind_direction_deg, dtype=float)


def _evaluate_wind_drag_ratio_array(context: DynamicAxisRequestContext) -> np.ndarray:
    inputs = context.wind_inputs()
    if inputs is None:
        return np.full(context.bearing_deg.shape, np.nan)
    speed, direction = inputs
    return wind_drag_ratio_array(speed, direction, context.bearing_deg, context.travel_speed_ms)


# `REQUEST_DYNAMIC_MATERIAL_IDS`（axis_definitions.py）の各材料idを、リクエスト時点の
# 幾何配列＋動的contextからベクトル評価する関数への唯一の登録点（式の実体は
# `domain/wind.py`にあり、ここは配線のみ）。`REQUEST_DYNAMIC_MATERIAL_IDS`自体が
# 「材料id」の集合として宣言されている（軸idの集合ではない）ため、ここも材料idで
# キーイングする——`dynamic_axis_topological_order`・`evaluate_axis_array`（いずれも軸名を
# ハードコードしない汎用実装）が「動的材料さえ埋まればどんな軸（軸スタジオが動的材料を
# 直接参照して作成したカスタム軸を含む）でも正しく合成する」ため、材料id単位の登録だけで
# 軸全体をカバーできる。`REQUEST_DYNAMIC_MATERIAL_IDS`と1対1に揃える（動的材料が増えたら
# 両方へ1エントリずつ追加する。片方だけだと`evaluate_dynamic_material_arrays`が失敗する）。
DYNAMIC_MATERIAL_EVALUATORS: dict[str, Callable[[DynamicAxisRequestContext], np.ndarray]] = {
    "wind_drag_ratio": _evaluate_wind_drag_ratio_array,
}


def evaluate_dynamic_material_arrays(context: DynamicAxisRequestContext) -> dict[str, np.ndarray]:
    """`REQUEST_DYNAMIC_MATERIAL_IDS`の全材料を`context`から評価する（材料id→配列、
    `context.bearing_deg`と同じ行順）。スカラー経路（`compute_dynamic_edge_materials`）・
    bulk経路（`_evaluate_axes_bulk`）・静的行列への動的軸合成（`evaluate_dynamic_axis_arrays`）
    の3経路がすべてここを通る。"""
    return {
        material_id: DYNAMIC_MATERIAL_EVALUATORS[material_id](context)
        for material_id in REQUEST_DYNAMIC_MATERIAL_IDS
    }


def evaluate_dynamic_axis_arrays(
    static_axis_scores: Mapping[str, np.ndarray], context: DynamicAxisRequestContext,
) -> dict[str, np.ndarray]:
    """タイル単位でキャッシュ済みの`StaticEdgeScoreMatrix.axis_scores`（NaN列を含む）から、
    動的軸（`dynamic_axis_topological_order`が返す軸）だけをリクエスト時点の値で上書き
    した軸別スコア辞書を返す。戻り値には動的材料の配列も含む（呼び出し元が区間表示用に
    材料値を読めるようにするため）。

    `evaluate_dynamic_material_arrays`で動的材料を求め、そこから
    `dynamic_axis_topological_order`の順で`evaluate_axis_array`を適用する（材料→軸の
    汎用トポロジカル合成のベクトル版で、動的軸の軸名自体は本関数もハードコードしない）。
    """
    materials_with_axes: dict[str, np.ndarray] = dict(static_axis_scores)
    materials_with_axes.update(evaluate_dynamic_material_arrays(context))
    for axis_id in dynamic_axis_topological_order(AXIS_DEFINITIONS):
        materials_with_axes[axis_id] = evaluate_axis_array(AXIS_DEFINITIONS[axis_id], materials_with_axes)
    return materials_with_axes
