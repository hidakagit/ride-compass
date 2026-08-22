"""Evaluation Engine（仕様書26-33章）。

Road Attribute（domain/attributes.py）とRoute PreferenceからEdge Costを算出する。
Route Engineから独立させ、Route Engine自身は「勾配がきつい」「路面が悪い」といった
評価の中身を一切知らない設計を目指す（仕様書33章）。

Score（難易度換算）は既存の`domain/difficulty.py`（Step9で導入、地図の難易度レイヤー用。
0-100、値が大きいほど走りにくい絶対基準）をそのまま再利用する。ルート単位の可視化と
Edge単位のEvaluation Engineが同じ「難易度」の意味・スケールを共有することで、新しい
正規化方式を発明せず、評価基準の食い違いも避ける。
"""

from pydantic import BaseModel

from app.domain.attributes import ElevationAttribute
from app.domain.difficulty import (
    accident_difficulty,
    car_stress_difficulty,
    composite_difficulty,
    evaluate_axis_difficulties,
    road_difficulty,
    stop_difficulty,
)
from app.domain.graph import DirectedEdge
from app.domain.night import night_difficulty
from app.domain.recipe import MotorVehicleDensityRecipe, RoadSuitabilityRecipe
from app.domain.road import classify_osm_surface
from app.domain.traffic import CarStressRecipe, car_stress_level
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

    Road Attributeとして実装済みの標高・路面・停止密度（信号・横断歩道・一時停止・踏切・
    タグなし交差点）・車ストレス・事故密度（外部静的データソース T50）・夜間
    （改善計画T139、街灯なし・トンネル）と、Dynamic Data対応（Phase 6）の風を対象とする。
    設定ファイルからの外部化はPhase 5で実施済み（route_preference.yaml、
    services/evaluation_service.py）。

    自転車インフラ（旧`infra_weight`）は改善計画T138で独立軸を廃止し車ストレス側へ
    統合済み（`car_closeness()`のcycleway補正が既に反映する情報のため独立に持たない）。
    安全度（旧`safety_weight`）は改善計画T139で軸ごと廃止し、highway等由来の部分は
    T138で車ストレスへ、街灯・トンネル由来の部分はここで`night_weight`へ置き換えた
    （事故実績は既存の`accident_weight`のまま変更なし）。`domain/safety.py`自体・
    `safety_recipe.yaml`・関連API（`SafetyRecipeOverride`等）はT148で削除済み。
    `night_weight`は既定0.0で運用する（設計プロンプトの指示どおり、街灯・トンネルを
    気にするユーザーが個別に重みを上げる想定）。
    交差点密度（旧`intersection_weight`）は改善計画T149で独立軸を廃止し停止密度側へ
    統合済み（`stop_difficulty`がタグなし交差点を低い重みで加算するため独立に持たない）。

    car_stress_weight/accident_weight/night_weightは区間難易度・探索コスト（本モデル）にのみ
    効き、scoring.yaml（total_score＝おすすめ度、候補集合内の相対評価）には含めない
    （stop_weightと同じ扱い。ユーザー承認済みのスコープ判断、静的道路属性P1参照）。
    """

    elevation_weight: float = 0.15
    road_weight: float = 0.19
    wind_weight: float = 0.26
    stop_weight: float = 0.20
    car_stress_weight: float = 0.20
    accident_weight: float = 0.08
    night_weight: float = 0.0


# RoutePreferenceのフィールド名（現行のPythonシンボル名、呼称統一はT150）→レジストリの
# axis_id（設計プロンプトが示す目標名、domain/registry_defaults.py参照）への対応表。
# 三次（compute_cost_from_axis_scores）はaxis_idキーの重み辞書のみを受け取るため、
# RoutePreferenceから変換する（改善計画T142）。
AXIS_WEIGHT_FIELD_TO_AXIS_ID: dict[str, str] = {
    "elevation_weight": "gradient",
    "wind_weight": "wind",
    "road_weight": "surface_q",
    "stop_weight": "stop_density",
    "car_stress_weight": "car_stress",
    "accident_weight": "accident",
    "night_weight": "night",
}

# domain/difficulty.py: AxisDifficultiesのフィールド名→axis_idの対応表（compute_edge_axis_scores用）。
_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID: dict[str, str] = {
    "elevation": "gradient",
    "wind": "wind",
    "road": "surface_q",
    "stop": "stop_density",
    "car_stress": "car_stress",
    "accident": "accident",
    "night": "night",
}


def preference_to_axis_weights(preference: RoutePreference) -> dict[str, float]:
    """`RoutePreference`をaxis_id（`gradient`/`wind`/`surface_q`/`stop_density`/`car_stress`/
    `accident`/`night`）をキーとする重み辞書へ変換する（改善計画T142）。"""
    dump = preference.model_dump()
    return {axis_id: dump[field] for field, axis_id in AXIS_WEIGHT_FIELD_TO_AXIS_ID.items()}


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
    # 全7軸の重み合計に対する、取得できた軸の重み合計の割合（0-1）。フロントが
    # 「◯%相当の軸のみで算出」という参考値である旨を示すために使う。
    covered_weight_fraction: float | None


def axis_inspector_breakdown(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool,
    way_counts: tuple[float, float, int, int] | None,
    accident_years_covered: int,
    preference: RoutePreference | None = None,
    car_stress_recipe: CarStressRecipe | None = None,
    road_suitability_recipe: RoadSuitabilityRecipe | None = None,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
) -> AxisInspectorResult:
    """区間インスペクタの内訳を算出する純関数。`way_counts`は
    `RoadGraphRepository.get_way_attribute_counts`の戻り値
    （length_m, accident_count, stop_count, intersection_count）で、Noneなら
    事故密度・停止密度は算出不能（available=False）として扱う。
    """
    weights = preference_to_axis_weights(preference or RoutePreference())

    level = car_stress_level(
        highway, tags, is_designated, car_stress_recipe, road_suitability_recipe, motor_vehicle_density_recipe
    )
    surface_good = classify_osm_surface(tags.get("surface"))

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

    # gradient/windは単独wayでは算出不能（ルート文脈が必要）なため、scoresへ含めない
    # （composite_difficultyの「データ無しは除外」動作をそのまま使う）。
    scores: dict[str, float | None] = {
        "car_stress": car_stress_difficulty(level),
        "surface_q": road_difficulty(surface_good),
        "stop_density": stop_difficulty(stop_per_km, intersection_per_km),
        "accident": accident_difficulty(accident_per_km_year),
        "night": night_difficulty(tags),
    }

    axes = [
        AxisInspectorAxis(axis_id=axis_id, difficulty=score, weight=weights.get(axis_id, 0.0), available=score is not None)
        for axis_id, score in scores.items()
    ]
    for axis_id in ("gradient", "wind"):
        axes.append(AxisInspectorAxis(axis_id=axis_id, difficulty=None, weight=weights.get(axis_id, 0.0), available=False))

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
    edge: DirectedEdge,
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
    if "no_bicycle" in active_filters and way_tags is not None:
        bicycle = (way_tags.get("bicycle") or "").strip().lower()
        if bicycle == "no":
            return False
    if (
        max_average_grade_percent is not None
        and elevation_attribute is not None
        and elevation_attribute.average_grade is not None
        and abs(elevation_attribute.average_grade) > max_average_grade_percent
    ):
        return False
    return True


def compute_wind_penalty(edge: DirectedEdge, wind: WeatherConditions | None) -> float | None:
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


_CAR_STRESS_LEVEL_NOT_PROVIDED = object()


def compute_edge_axis_scores(
    edge: DirectedEdge,
    elevation_attribute: ElevationAttribute | None,
    surface_type: str | None,
    wind: WeatherConditions | None = None,
    stop_count: int | None = None,
    way_tags: dict[str, str] | None = None,
    intersection_count: int | None = None,
    accident_count: int | None = None,
    accident_years_covered: int = 0,
    is_designated: bool = False,
    car_stress_recipe: CarStressRecipe | None = None,
    road_suitability_recipe: RoadSuitabilityRecipe | None = None,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
    car_stress_level_value: int | None = _CAR_STRESS_LEVEL_NOT_PROVIDED,  # type: ignore[assignment]
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
    評価しない。タグ自体が空（`{}`）でも`edge.highway`があれば車ストレスの基本値は
    評価できる（unknown安全設計のため）。
    `intersection_count`はこのEdge周辺の交差点（次数3以上のNode）の件数（静的道路属性P1残り、
    改善計画T149でstop_density軸への補助入力へ変更）。Noneはデータ無し（未評価、0件と区別する）。
    `accident_count`はこのEdge周辺の事故（accident_points）の件数（外部静的データソース
    T50）。Noneはデータ無し（未評価、0件と区別する）。`accident_years_covered`は事故データの
    収録年数（`AttributeRepository.get_accident_years_covered`）で、密度を件/(km・年)へ
    正規化するために使う。
    `is_designated`はこのEdgeがKSJ N10/N12（緊急輸送道路・重要物流道路）に該当するか
    （外部静的データソース T51）。車ストレスへの補正のみに使う。
    `car_stress_recipe`は車ストレス軸の判定レシピの上書き（省略時はdomain/traffic.py:
    DEFAULT_CAR_STRESS_RECIPE）。研究モードでのレシピ調整用（一次情報→二次情報の変換式
    自体をリクエスト単位で差し替える）。
    `road_suitability_recipe`/`motor_vehicle_density_recipe`は車ストレスが参照する
    「車との近さ」(N2)の材料の上書き（省略時はそれぞれdomain/recipe.py:
    DEFAULT_ROAD_SUITABILITY_RECIPE/DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE、改善計画:
    車との近さ材料の共有元化）。
    `car_stress_level_value`は呼び出し元が既に`car_stress_level()`を計算済みの場合、その
    結果（1-5、またはway_tags未取得ならNone）を渡すことで内部での再計算を省略できる
    （改善計画T153。省略時は`way_tags`等から本関数がその場で計算する。呼び出し元は
    `car_stress_level_value`に使ったのと同じ`car_stress_recipe`/`road_suitability_recipe`/
    `motor_vehicle_density_recipe`をこの関数へも渡すこと——異なるレシピを渡すと
    car_stress_level_valueとaxis_scores["car_stress"]が別レシピの値になり不整合になる）。
    """
    gradient_percent = elevation_attribute.average_grade if elevation_attribute else None
    is_good_surface = classify_osm_surface(surface_type)
    wind_penalty = compute_wind_penalty(edge, wind)
    stop_count_per_km = stop_count / (edge.distance_m / 1000) if stop_count is not None and edge.distance_m > 0 else None
    # 「車との近さ」(N2)はcar_stress_levelがこの1箇所でのみ参照する（T148で安全度軸を
    # 削除するまではsafety_levelとも共有する共通の土台だったため、呼び出し元で1回だけ
    # 計算して両方へ渡すdedupをしていたが、参照元が1箇所になったためcar_stress_level内部の
    # 計算へ戻した）。ただしroad_graph_engine.pyの区間表示ビルダーは、この関数とは別に
    # 表示用の生値car_stressを自分でも必要とするため、依然としてcar_stress_level()を
    # 呼び出し元・本関数の両方で計算する二重計算が残っていた（統合レビュー2026-08-19、
    # overall F-1／改善計画T153）。car_stress_level_valueが明示的に渡された場合は
    # ここでの再計算をスキップしてそれを使う。
    car_stress = (
        (
            car_stress_level(
                edge.highway,
                way_tags,
                is_designated,
                car_stress_recipe,
                road_suitability_recipe=road_suitability_recipe,
                motor_vehicle_density_recipe=motor_vehicle_density_recipe,
            )
            if way_tags is not None
            else None
        )
        if car_stress_level_value is _CAR_STRESS_LEVEL_NOT_PROVIDED
        else car_stress_level_value
    )
    intersection_count_per_km = (
        intersection_count / (edge.distance_m / 1000) if intersection_count is not None and edge.distance_m > 0 else None
    )
    accident_count_per_km_year = (
        accident_count / (edge.distance_m / 1000) / accident_years_covered
        if accident_count is not None and edge.distance_m > 0 and accident_years_covered > 0
        else None
    )
    axis_difficulties = evaluate_axis_difficulties(
        gradient_percent, wind_penalty, is_good_surface, stop_count_per_km,
        car_stress, intersection_count_per_km, accident_count_per_km_year, way_tags,
        # 重みはここでは使わない（このwrapperは軸別スコアの算出のみ担当）。
        # 全て1.0を渡してもcompositeは無視するため、compositeの計算コスト自体は避けられないが
        # 結果は使わない（下でaxis_difficulties.compositeを参照しない）。
        1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
    )
    return {
        axis_id: value
        for field, axis_id in _AXIS_DIFFICULTY_FIELD_TO_AXIS_ID.items()
        if (value := getattr(axis_difficulties, field)) is not None
    }


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
    edge: DirectedEdge,
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
    car_stress_recipe: CarStressRecipe | None = None,
    road_suitability_recipe: RoadSuitabilityRecipe | None = None,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
    penalty_strength: float = 1.0,
    max_average_grade_percent: float | None = None,
    weights: dict[str, float] | None = None,
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

    `weights`（改善計画T220、T12 Stage 2）: `preference_to_axis_weights(preference)`は
    `preference`が変わらない限り常に同じ結果を返す純関数だが、Road Graph全体
    （数万Edge）を評価する`evaluate_graph`のループから毎Edge呼ばれると、実測
    （pydanticの`model_dump`込み）で無視できないオーバーヘッドになると判明した
    （`backend/benchmarks/README.md`参照）。呼び出し元が事前計算した`weights`を渡せば
    その再計算をスキップする。省略時（既定None）は従来どおり`preference`から算出する
    （単発の呼び出し・既存テストへの影響なし）。
    """
    if not is_edge_allowed(
        edge, way_tags, elevation_attribute=elevation_attribute, max_average_grade_percent=max_average_grade_percent
    ):
        return EdgeCostResult(edge_id=edge.edge_id, cost=None, difficulty=None, allowed=False)

    axis_scores = compute_edge_axis_scores(
        edge, elevation_attribute, surface_type, wind, stop_count, way_tags,
        intersection_count, accident_count, accident_years_covered, is_designated,
        car_stress_recipe, road_suitability_recipe, motor_vehicle_density_recipe,
    )
    resolved_weights = weights if weights is not None else preference_to_axis_weights(preference)
    cost, difficulty = compute_cost_from_axis_scores(edge.distance_m, axis_scores, resolved_weights, penalty_strength)

    return EdgeCostResult(edge_id=edge.edge_id, cost=cost, difficulty=difficulty, allowed=True)
