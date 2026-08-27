"""Evaluation Engine（仕様書26-33章）。

Road Attribute（domain/attributes.py）とRoute PreferenceからEdge Costを算出する。
Route Engineから独立させ、Route Engine自身は「勾配がきつい」「路面が悪い」といった
評価の中身を一切知らない設計を目指す（仕様書33章）。

Score（難易度換算）は既存の`domain/difficulty.py`（Step9で導入、地図の難易度レイヤー用。
0-100、値が大きいほど走りにくい絶対基準）をそのまま再利用する。ルート単位の可視化と
Edge単位のEvaluation Engineが同じ「難易度」の意味・スケールを共有することで、新しい
正規化方式を発明せず、評価基準の食い違いも避ける。
"""

import numpy as np
from pydantic import BaseModel, Field, model_validator

from app.domain.attributes import ElevationAttribute
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    default_axis_weights,
    evaluate_axes_scalar,
    evaluate_axis_array,
    time_scoped_weights,
    topological_axis_order,
)
from app.domain.axis_templates import round1_array
from app.domain.difficulty import composite_difficulty
from app.domain.graph import EdgeLike, RoadGraphLike
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialExtractionContext
from app.domain.night import night_materials
from app.domain.recipe import bicycle_infra_flags_or_none, parse_lanes, parse_maxspeed, tag_value_is
from app.domain.road import classify_osm_surface
from app.domain.weather import WeatherConditions
from app.domain.wind import WindCalculator

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
    `docs/architecture.md` 7章とgit履歴参照。car_stress/accident/nightの重みは区間難易度・
    探索コスト（本モデル）にのみ効き、scoring.yaml（total_score＝おすすめ度、候補集合内の
    相対評価）には含めない（ユーザー承認済みのスコープ判断、静的道路属性P1参照）。
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
    way_counts: tuple[float, float, int, int] | None,
    accident_years_covered: int,
    preference: RoutePreference | None = None,
) -> AxisInspectorResult:
    """区間インスペクタの内訳を算出する純関数。`way_counts`は
    `RoadGraphRepository.get_way_attribute_counts`の戻り値
    （length_m, accident_count, stop_count, intersection_count）で、Noneなら
    事故密度・停止密度は算出不能（available=False）として扱う。
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
        length_m, accident_count, stop_count, intersection_count = way_counts
        if length_m and length_m > 0:
            length_km = length_m / 1000.0

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
        "wind_penalty": None,
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


def compute_wind_penalty(edge: EdgeLike, wind: WeatherConditions | None) -> float | None:
    """Edgeの進行方向（from_node→to_node）と風向風速からwind_penaltyを算出する
    （Dynamic Data対応、仕様書20・44章：Edge + Travel Direction + Timeから評価する）。

    正=向かい風、負=追い風（domain/wind.py: WindCalculatorをそのまま再利用）。風は
    Edgeに永続保存しない（動的データでありRoad Attributeとして扱わない、仕様書20章）。

    改善計画T218（T12 Stage 0）: 進行方向はEdgeのgeometry（形状点列）から都度計算せず、
    事前計算済みの`edge.bearing_deg`（domain/graph.py: build_road_graph参照）をそのまま
    使う。探索フェーズではgeometry自体を取得しない（geometry decodeが不要になる）ため、
    この関数もgeometryへ依存しない形にしている。

    既知の簡略化: 本来は出発時刻とEdgeまでの推定累積走行時間から「そのEdgeを実際に
    通過するであろう時刻」の風を使うべきだが（ルート単位評価の`WindService`
    （`services/wind_service.py`、`routing_engine=="openrouteservice"`のときは今も
    `OpenRouteServiceEngine`が使う）はこの方式）、経路探索中（Dijkstra探索の途中）は
    まだ累積走行時間が確定していないため、探索対象領域全体で単一の風（出発時点・
    起点付近の風）を一様に適用する簡略化を採用している。将来、時間展開グラフ等で
    より精密化する余地がある（docs/architecture.md参照）。
    """
    if wind is None or edge.bearing_deg is None:
        return None
    return WindCalculator.wind_penalty(wind.wind_speed_ms, wind.wind_direction_deg, edge.bearing_deg)


def compute_edge_axis_scores(
    edge: EdgeLike,
    elevation_attribute: ElevationAttribute | None,
    surface_type: str | None,
    wind: WeatherConditions | None = None,
    stop_count: int | None = None,
    way_tags: dict[str, str] | None = None,
    intersection_count: int | None = None,
    accident_count: int | None = None,
    accident_years_covered: int = 0,
    is_designated: bool = False,
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
    """
    gradient_percent = elevation_attribute.average_grade if elevation_attribute else None
    is_good_surface = classify_osm_surface(surface_type)
    wind_penalty = compute_wind_penalty(edge, wind)
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
    materials: dict[str, object] = {
        "gradient_percent": gradient_percent,
        "wind_penalty": wind_penalty,
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
    # 改善計画T292: 軸は他の軸のdifficultyをmaterialとして参照できる（内部軸→公開軸の
    # 階層構造）。依存先（参照される軸）を先に評価し、結果をmaterialsへ混ぜ込みながら
    # 進めることで、参照する側は追加のAPIなしに`materials.get(axis_id)`で読める
    # （`evaluate_axes_scalar`参照）。ここでは値が算出できなかった公開軸のキー自体を
    # 呼び出し元（RouteSegmentDetail構築側）へ渡さないよう、Noneのキーを落とす
    # （`axis_inspector_breakdown`はavailable判定のためNoneのキーを残したまま返す点が
    # 異なる）。
    scores, _ = evaluate_axes_scalar(materials)
    return {axis_id: value for axis_id, value in scores.items() if value is not None}


def compute_cost_from_axis_scores(
    distance_m: float, axis_scores: dict[str, float], weights: dict[str, float], penalty_strength: float = 1.0
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
    """
    scored_weights = [(score, weights.get(axis_id, 0.0)) for axis_id, score in axis_scores.items()]
    difficulty = composite_difficulty(scored_weights)
    penalty_multiplier = 1.0 + penalty_strength * (difficulty / 100) if difficulty is not None else 1.0
    cost = round(distance_m * penalty_multiplier, 1)
    return cost, difficulty


def compute_edge_cost(
    edge: EdgeLike,
    elevation_attribute: ElevationAttribute | None,
    surface_type: str | None,
    preference: RoutePreference,
    wind: WeatherConditions | None = None,
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
    """
    if not is_edge_allowed(
        edge,
        way_tags,
        hard_filters=hard_filters,
        elevation_attribute=elevation_attribute,
        max_average_grade_percent=max_average_grade_percent,
    ):
        return EdgeCostResult(edge_id=edge.edge_id, cost=None, difficulty=None, allowed=False)

    axis_scores = compute_edge_axis_scores(
        edge, elevation_attribute, surface_type, wind, stop_count, way_tags,
        intersection_count, accident_count, accident_years_covered, is_designated,
    )
    resolved_weights = weights if weights is not None else preference.weights
    cost, difficulty = compute_cost_from_axis_scores(edge.distance_m, axis_scores, resolved_weights, penalty_strength)

    return EdgeCostResult(edge_id=edge.edge_id, cost=cost, difficulty=difficulty, allowed=True)


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


def compute_edge_costs_bulk(
    graph: RoadGraphLike,
    elevation_attributes: dict[str, ElevationAttribute],
    surface_attributes: dict[str, str | None],
    preference: RoutePreference,
    wind: WeatherConditions | None = None,
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
) -> dict[str, EdgeCostResult]:
    """`compute_edge_cost`を全Edge分ループするのと同じ結果を、numpyのベクトル演算で
    算出する（改善計画T221/T240、`EvaluationService.evaluate_graph`専用）。

    構造は「抽出フェーズ」と「計算フェーズ」の2段:

    - 抽出フェーズ（1回のPythonループ）: Edge単位の辞書・タグアクセスを`MATERIAL_CATALOG`
      （改善計画T280、`domain/material_catalog.py: MaterialSpec.extractor`）へ委譲し、
      以降で使う数値をすべてnumpy配列へ落とし込む。欠損値は数値材料がNaN、文字列材料
      （highway・surface等、dtype=object）がNoneで表現する。材料を1件追加する
      ときはmaterial_catalog.pyへ抽出関数を書いてカタログへ登録するだけでよく、
      この関数自体の変更は不要（0次ハードフィルタ判定はEdgeの通行可否そのものであり
      材料の値ではないため、対象外のままここに残す）。
    - 計算フェーズ（Pythonループ無し）: 材料id→配列の辞書に対して`AXIS_DEFINITIONS`
      （domain/axis_definitions.py、改善計画T221 Stage B/C）を軸ごとに適用して
      difficulty配列を求め、重み配列とのマスク付き加重平均（`composite_difficulty`の
      ベクトル版）→cost算出まで、すべて配列演算で行う。スカラー経路
      （`compute_edge_axis_scores`）と同じ軸定義データを読むため、軸の追加は
      定義データの追加だけで両経路へ同時に反映される。

    スカラー版`compute_edge_cost`は削除せず、本関数との出力一致を検証する回帰テスト
    （`tests/test_evaluation_bulk.py`）のオラクルとして残す。

    `stop_count`/`intersection_count`/`accident_count`は実データ上ゼロ以上の整数
    （PostGIS事前集計、`domain/attributes.py: EdgeAttributeCounts`）であることを前提とし、
    「負値ならNone」という防御的ガード（テスト専用の異常値入力を想定したもの、改善計画
    T320で削除済みのスカラー版互換ラッパが持っていた）はここでは再現しない（実データでは
    到達しない分岐のため、ベクトル化の単純さを優先した）。

    `hard_filters`（改善計画T266）: `is_edge_allowed`と同じフィルタ名集合による上書き。
    省略時（既定None）は`DEFAULT_HARD_FILTERS`（全フィルタ常時有効）を使う。
    """
    stop_counts = stop_counts or {}
    intersection_counts = intersection_counts or {}
    accident_counts = accident_counts or {}
    designated_edge_ids = designated_edge_ids or set()
    resolved_weights = weights if weights is not None else preference.weights
    active_hard_filters = hard_filters if hard_filters is not None else DEFAULT_HARD_FILTERS

    edge_ids = list(graph.edges.keys())
    n = len(edge_ids)
    if n == 0:
        return {}
    edges = [graph.edges[edge_id] for edge_id in edge_ids]

    distance_m = np.array([edge.distance_m for edge in edges], dtype=float)
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

    hard_filter_excluded = np.zeros(n, dtype=bool)

    for i, (edge_id, edge) in enumerate(zip(edge_ids, edges)):
        edge_way_tags = way_tags.get(edge_id) if way_tags is not None else None

        # 0次ハードフィルタ（is_edge_allowedと同じ判定、改善計画T266でactive_hard_filters
        # 引数による上書きに対応）。材料の値ではなくEdgeの通行可否そのものなので、
        # 材料抽出とは独立にここへ残す。
        if edge.highway is not None:
            for filter_name, highway_types in HARD_FILTER_HIGHWAY_TYPES.items():
                if filter_name in active_hard_filters and edge.highway in highway_types:
                    hard_filter_excluded[i] = True
                    break
        if (
            "no_bicycle" in active_hard_filters
            and edge_way_tags is not None
            and tag_value_is(edge_way_tags, "bicycle", "no")
        ):
            hard_filter_excluded[i] = True

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

    # 勾配の〇次ハードフィルタ（改善計画T280: 抽出済みgradient_percent配列に対する
    # ベクトル演算1本に分離。NaNとの比較は常にFalseになるため、勾配不明のEdgeへは
    # 従来どおり適用されない）。
    if max_average_grade_percent is not None:
        with np.errstate(invalid="ignore"):
            hard_filter_excluded |= np.abs(material_arrays["gradient_percent"]) > max_average_grade_percent

    # --- 計算フェーズ（Pythonループ無し） ---
    wind_penalty = (
        np.full(n, np.nan)
        if wind is None
        else wind.wind_speed_ms * np.cos(np.radians(wind.wind_direction_deg - bearing_deg))
    )
    # wind_penaltyはEdge単位のPythonループを経由しない完全ベクトル化計算のため
    # extractorを持たない（material_catalog.pyのextractorフィールド説明参照）。
    material_arrays["wind_penalty"] = wind_penalty
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

    # composite_difficultyのベクトル版: Noneの軸（NaN）は除外し残りの重みで再正規化する
    # （辞書挿入順=上のaxis_arraysと同じgradient→wind→...→nightの順、無効な軸はスカラー版の
    # `available`リストでは最初から除外されるが、ここでは0.0を加算するのと数学的に等価
    # ——Neumaier加算でも0.0項の加算は補正項に影響しないため、スカラー版と同じ結果になる）。
    # スカラー版composite_difficultyの`sum(score*weight for score,weight in available)`は
    # Python組み込み`sum()`（3.12以降、Neumaier補償加算）であり、単純な逐次`+=`とは
    # 異なる浮動小数点結果になりうる（`_neumaier_accumulate`のdocstring参照）。
    score_terms = []
    weight_terms = []
    for axis_id, arr in axis_arrays.items():
        weight = resolved_weights.get(axis_id, 0.0)
        valid = ~np.isnan(arr)
        score_terms.append(np.where(valid, arr * weight, 0.0))
        weight_terms.append(np.where(valid, weight, 0.0))
    weighted_scores = _neumaier_accumulate(score_terms)
    weighted_weight_sums = _neumaier_accumulate(weight_terms)
    with np.errstate(invalid="ignore", divide="ignore"):
        composite = weighted_scores / weighted_weight_sums
    composite = np.where(weighted_weight_sums == 0, np.nan, composite)
    # np.roundは内部で「×10→rint→÷10」という段階を踏むため、その中間の掛け算で
    # 丸め誤差が混入し、ちょうど.X5の境界にある値でPythonの`round(x, 1)`
    # （2進浮動小数点の実際の値に対する正しい丸め）と結果が食い違うことがある
    # （実測: 385.949999999999988...→np.roundは386.0、round()は385.9）。
    # スカラー版composite_difficulty/compute_cost_from_axis_scoresの`round(x, 1)`と
    # 完全一致させるため、最終丸めのみ要素ごとにPythonの`round()`を適用する
    # （軸別スコアの計算・加重合成自体はベクトル化済みのままで、丸めのみの
    # 逐次処理はn件でも計算コストは無視できる）。
    composite = round1_array(composite)

    # compute_cost_from_axis_scoresと同じ: difficultyがNaN(None相当)ならcostは距離そのもの
    # （割増なし）。allowed=Falseのcost=Noneは出力構築時に別途上書きする。
    penalty_multiplier = np.where(np.isnan(composite), 1.0, 1.0 + penalty_strength * (composite / 100))
    cost = round1_array(distance_m * penalty_multiplier)

    # --- 出力構築（EdgeCostResult.model_construct: 値は内部計算済みでバリデーション不要） ---
    results: dict[str, EdgeCostResult] = {}
    for i, edge_id in enumerate(edge_ids):
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
