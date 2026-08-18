"""静的道路属性の派生分類（docs/static-road-attributes-plan.md P0・§2.4）。

すべて純関数・unknown安全（タグが無い/未知の値は`None`または`"unknown"`を返し、
根拠のない推測はしない）。正準定義はここ1箇所（domain/road.pyのGOOD/BAD_OSM_SURFACE_TAGSと
同じ「正準1箇所」の運用、改善計画T7原則）。

MVT生成（road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL）はbicycle_infraのみSQL側で
同じ判定基準をCASE式として実装しており、classify_bicycle_infrastructureと1:1対応させる
（test_road_graph_repository.pyの整合性テストで突き合わせる。SQL側にPythonを呼び出す手段が
無いため、判定ロジック自体はやむを得ず2箇所に存在するが、同じ入力に対し常に同じ出力になる
ことをテストで担保する）。

車ストレス（car_stress_breakdown/car_stress_level、改善計画T150で「交通ストレス」から改称）は
改善計画（交通ストレスレシピ外出し基盤）以降、SQL側では最終値を計算しない（材料タグのみ
焼き込み、最終値の計算はfrontend/src/components/Map/carStressExpression.tsとこのモジュールが
それぞれ担う）。両者の整合はcarStressExpression.test.tsが担保する。
"""

from typing import Literal

from pydantic import BaseModel

from app.domain.recipe import (
    DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    DEFAULT_ROAD_SUITABILITY_RECIPE,
    MotorVehicleDensityRecipe,
    RoadSuitabilityRecipe,
    car_closeness,
    clamp_level,
    cycleway_class,
    cycleway_values,
    parse_lanes,
    parse_maxspeed,
    tag_value_is,
    threshold_adjustment,
)

# 信号・横断歩道・一時停止・踏切のnode空間マッチ用スナップ半径（静的道路属性P1、改善計画T44）。
# openrouteservice_engine.py（明示引数）とAttributeRepository各メソッド（デフォルト引数、
# GraphService.get_stop_poi_countsはこのデフォルトを暗黙使用）の両方がこの定数をimportして
# 参照する。domain/road.py: SURFACE_MATCH_MAX_DISTANCE_Mと同じ理由で「コメントで揃える」
# 手動同期にしない（設計原則2）。
STOP_POI_MATCH_MAX_DISTANCE_M = 15.0

# 交差点（次数3以上のroad_node）の空間マッチ用半径（静的道路属性P1残り、intersectionDensity）。
# road_nodeは信号等のPOIと違い必ずEdgeの端点に位置するため、Edge単位（road_graphエンジン、
# 端点そのもの）ではSTOP_POI_MATCH_MAX_DISTANCE_M相当でも十分だが、ORSエンジンのサンプル点は
# ルートgeometry上の等間隔点でありグラフのNodeに一致するとは限らないため、路面評価
# （domain/road.py: SURFACE_MATCH_MAX_DISTANCE_M=30m）と同じ「物理的な道路網特徴への
# スナップ許容量」を採用する。
INTERSECTION_MATCH_MAX_DISTANCE_M = 30.0

# 交差点判定の次数しきい値（この数以上の異なる隣接Nodeを持つNodeを交差点とみなす）。
INTERSECTION_DEGREE_THRESHOLD = 3

# smoothness→スコア(0-100)。未設定・未知の値はNone（評価しない）。
_SMOOTHNESS_SCORES: dict[str, float] = {
    "excellent": 100.0,
    "good": 85.0,
    "intermediate": 60.0,
    "bad": 30.0,
    "very_bad": 10.0,
    "horrible": 0.0,
    "very_horrible": 0.0,
    "impassable": 0.0,
}


def smoothness_score(tags: dict[str, str]) -> float | None:
    value = tags.get("smoothness")
    if value is None:
        return None
    return _SMOOTHNESS_SCORES.get(value.strip().lower())


BicycleInfraClass = Literal[
    "separated", "lane", "shared_busway", "shared_pedestrian", "roadway", "prohibited", "unknown"
]


def classify_bicycle_infrastructure(tags: dict[str, str], highway: str | None) -> BicycleInfraClass:
    """自転車インフラ分類（優先順位: separated＞lane＞shared_busway等＞shared_pedestrian＞
    roadway/prohibited＞unknown。計画書§2.4）。

    cycleway/cycleway:left/right/bothタグは`car_stress_level`（本モジュール）でも
    「専用自転車道の有無」の補正に使われている（trackなら-2、laneなら-1）。同じ入力を
    別目的で解釈しているため、bicycle_infra_score（本分類ベース）とcar_stress_score
    （車ストレス）は完全には独立ではなく、専用自転車道が併設された区間では両方が
    同時に「易しい」側へ動く（改善計画T62、意図的な設計でありバグではない）。
    """
    values = cycleway_values(tags)
    bicycle = (tags.get("bicycle") or "").strip().lower()

    if highway == "cycleway" or "track" in values:
        return "separated"
    if "lane" in values:
        return "lane"
    if any(v in ("share_busway", "shared_lane") for v in values):
        return "shared_busway"
    if highway in ("path", "footway") and bicycle in ("yes", "designated", "permissive"):
        return "shared_pedestrian"
    if bicycle == "no":
        return "prohibited"
    if highway is not None:
        return "roadway"
    return "unknown"


class CarStressRecipe(BaseModel):
    """`car_stress_breakdown`の判定基準のうち、車ストレス軸だけが持つ補正
    （対面通行の少車線道路への緩和）をまとめた「レシピ」。一次情報（OSMタグ）から
    二次情報（車ストレス値）を作る変換式の、この軸固有の部分（改善計画T150で
    `TrafficStressRecipe`/「交通ストレス」から改称）。

    highway別基準値・cycleway補正・制限速度補正・車線数[多い方]補正・指定路線補正は
    「車との近さ」（N2）として車ストレス・安全度が共有する（`domain/recipe.py:
    RoadSuitabilityRecipe`/`MotorVehicleDensityRecipe`/`car_closeness()`、改善計画:
    車との近さ材料の共有元化）ため、ここには含まない。

    既定値（`DEFAULT_CAR_STRESS_RECIPE`）は研究フェーズでのレシピ調整・将来の
    個人最適化に向けて外側の`RoutePreference`（軸間の重み）とは別に、この「軸の中身」
    自体をリクエスト単位で上書きできるようにするための切り出し（地図表示側は
    `frontend/src/components/Map/carStressExpression.ts`が同じレシピをMapLibre
    expressionとして再現する）。
    """

    lanes_low_threshold: int = 1
    lanes_low_adjustment: int = -1


DEFAULT_CAR_STRESS_RECIPE = CarStressRecipe()


StopPoiKind = Literal["traffic_signals", "crossing", "stop", "give_way", "level_crossing"]

_HIGHWAY_STOP_KINDS: dict[str, StopPoiKind] = {
    "traffic_signals": "traffic_signals",
    "crossing": "crossing",
    "stop": "stop",
    "give_way": "give_way",
}


def classify_stop_poi(tags: dict[str, str]) -> StopPoiKind | None:
    """信号・横断歩道・一時停止・踏切の分類（静的道路属性P1、計画書§2.2）。node取込の
    対象node判定にも使う（osm_adapter.py: osm_node_to_poi_spec、Noneを返すnodeは取込対象外）。

    railway=level_crossingとhighway=*は独立したタグのため、両方が同一nodeに付く場合は
    railway側を優先する（踏切は自転車にとって一時停止の法的義務が信号・横断歩道より
    強く、質的に異なるため）。いずれにも該当しなければNone（対象外・評価しない）。
    """
    if (tags.get("railway") or "").strip().lower() == "level_crossing":
        return "level_crossing"
    highway = (tags.get("highway") or "").strip().lower()
    return _HIGHWAY_STOP_KINDS.get(highway)


SupplyPoiKind = Literal["convenience", "vending_machine", "toilets", "drinking_water", "bicycle_parking"]

_AMENITY_SUPPLY_KINDS: dict[str, SupplyPoiKind] = {
    "vending_machine": "vending_machine",
    "toilets": "toilets",
    "drinking_water": "drinking_water",
    "bicycle_parking": "bicycle_parking",
}


def classify_supply_poi(tags: dict[str, str]) -> SupplyPoiKind | None:
    """補給・休憩ポイント（コンビニ・自販機・トイレ・給水・駐輪場）の分類（改善計画T101、
    static-road-attributes-plan.md §2.3）。classify_stop_poiと同じくnode取込の対象判定にも
    使う（osm_adapter.py: osm_node_to_poi_spec）。停止要因POIとタグ名（shop/amenity vs
    highway/railway）が独立しており衝突しないため、優先順位の考慮は不要。

    実店舗との乖離（閉店・移転にOSM側が追従できていないリスク）はタグ自体からは
    分からないため、`backend/scripts/measure_poi_freshness.py`（2026-08-18実測）で
    要素の最終編集日時を代理指標に実測した。コンビニ（shop=convenience）は直近2年以内の
    編集が関東全域で62.4%と明確に新しいが、自販機・トイレ・給水・駐輪場は5年以上未編集が
    58〜59%と高く、実店舗との乖離リスクが相対的に高い（フロント側mapLayers.ts:
    supplyPoiのpanelHintで「鮮度に注意」と明記して利用者に伝える。取込・分類自体は
    5種すべて対象とし、鮮度の扱いは表示側の注意喚起に留める）。
    """
    if (tags.get("shop") or "").strip().lower() == "convenience":
        return "convenience"
    amenity = (tags.get("amenity") or "").strip().lower()
    return _AMENITY_SUPPLY_KINDS.get(amenity)


def _density_per_km(segments: list[tuple[float, int | None]]) -> float | None:
    """(区間distance_km, 区間内のcount)のリストから「合計count÷合計distance_km」を求める
    （密度は加算的な量の比であり、区間ごとに既に正規化された値の平均ではないため、
    domain/difficulty.pyのdistance_weighted_*とは異なる集約になる）。

    countがNoneの区間は「データ未取得（例: repository未注入）」を表し、0（実測で対象無し）
    とは区別して集計から除外する。除外後に1区間も残らない、または距離の合計が0以下ならNone。
    """
    available = [(distance, count) for distance, count in segments if count is not None]
    if not available:
        return None
    distance_sum = sum(distance for distance, _ in available)
    if distance_sum <= 0:
        return None
    count_sum = sum(count for _, count in available)
    return round(count_sum / distance_sum, 2)


def distance_weighted_stop_density(segments: list[tuple[float, int | None]]) -> float | None:
    """(区間distance_km, 区間内の停止要因count)のリストから、ルート全体の停止密度
    （回/km）を求める（静的道路属性P1）。"""
    return _density_per_km(segments)


def distance_weighted_intersection_density(segments: list[tuple[float, int | None]]) -> float | None:
    """(区間distance_km, 区間内の交差点count)のリストから、ルート全体の交差点密度
    （回/km）を求める（静的道路属性P1残り、intersectionDensity）。集約方法は
    distance_weighted_stop_densityと同じ（stop_countsに無いEdge/サンプル点はNone扱いで
    「データ未取得」と「実測0件」を区別する、road_score等と同じ方針）。"""
    return _density_per_km(segments)


# 分離自転車道・自転車レーンを「専用インフラ」とみなす分類（bicycle_infra_score算出用）。
DEDICATED_BICYCLE_INFRA_CLASSES: frozenset[str] = frozenset({"separated", "lane"})


def is_dedicated_bicycle_infra(bicycle_infra: BicycleInfraClass | None) -> bool | None:
    """自転車インフラ分類が「専用インフラ（分離・レーン）」かどうかを3値で返す
    （不明はNone。road.py: classify_osm_surfaceの3値判定と同じ考え方）。

    `classify_bicycle_infrastructure`は判定不能（highway等の入力が無い）な場合Noneではなく
    文字列`"unknown"`を返す仕様のため、ここでも明示的にNone扱いする。これを怠ると、
    ORSエンジンでway_tagsの空間マッチに失敗した区間（データ欠損）が「専用インフラではないと
    確認された区間」としてdistance_weighted_bicycle_infra_scoreの分母に混入してしまう。
    """
    if bicycle_infra is None or bicycle_infra == "unknown":
        return None
    return bicycle_infra in DEDICATED_BICYCLE_INFRA_CLASSES


def distance_weighted_bicycle_infra_score(pairs: list[tuple[float, bool | None]]) -> float | None:
    """(区間の距離, 専用の自転車インフラか)のペア列から、距離加重の専用インフラ率(%)を
    算出する（domain/road.py: distance_weighted_road_scoreと同じ集約方法。不明区間は
    分母から除外し、判定できる区間が1つも無ければNone）。"""
    known = sum(distance for distance, is_dedicated in pairs if is_dedicated is not None)
    if known <= 0:
        return None
    dedicated = sum(distance for distance, is_dedicated in pairs if is_dedicated)
    return round(dedicated / known * 100, 1)


class CarStressBreakdown(BaseModel):
    """`car_stress_level`の判定内訳（改善計画T90、T150で「交通ストレス」から改称）。
    地図上の道路クリック時に「なぜこの値になったか」を説明する表示専用データで、
    `level`は`car_stress_level`と同じ最終値。highwayが判定基準
    （`domain/recipe.py: ROAD_SUITABILITY_BASE_BY_HIGHWAY`）に登録されていない場合は
    `base`/`level`ともNoneで、他の補正フィールドは0/False。
    """

    base: int | None
    cycleway_adjustment: int
    maxspeed_adjustment: int
    lanes_adjustment: int
    designation_adjustment: int
    motor_vehicle_no_override: bool
    level: int | None


def car_stress_breakdown(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool = False,
    recipe: CarStressRecipe | None = None,
    road_suitability_recipe: RoadSuitabilityRecipe | None = None,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
    *,
    car_closeness_result: tuple[int | None, int, int, int, int] | None = None,
) -> CarStressBreakdown:
    """車ストレス（旧「交通ストレス」、LTS: Level of Traffic Stress風の1-5段階。
    「交通量」ではなく「推定される車との近接ストレス」、計画書§2.4）を、各補正の
    適用有無・量が分かる内訳付きで返す。基本値はhighwayのみで決まり、未知のhighwayは
    None（評価しない）。補正はタグが実際にある場合のみ適用する（unknownは補正しない）。

    `recipe`省略時は`DEFAULT_CAR_STRESS_RECIPE`を使う。`road_suitability_recipe`/
    `motor_vehicle_density_recipe`は省略時それぞれ`DEFAULT_ROAD_SUITABILITY_RECIPE`/
    `DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE`（改善計画: 車との近さ材料の共有元化。
    この2つは安全度側と共有する「車との近さ」(N2)の材料で、`recipe`
    [`CarStressRecipe`]はこの軸固有の少車線道路補正のみを持つ）。

    `car_closeness_result`は`car_closeness()`の呼び出し結果を呼び出し側で事前計算済みの
    場合に渡す（`domain/evaluation.py: compute_edge_cost`参照）。同じ材料タグ・同じ
    レシピに対してcar_closeness()は`car_stress_breakdown`/`safety_breakdown`の両方から
    毎回独立に呼ばれ、ルート生成の全Edgeに対して計算結果が完全に重複していたため
    （1Edgeにつき2回計算していた無駄を解消）、省略時のみ内部で`car_closeness()`を呼ぶ。

    cycleway系タグによる補正は`classify_bicycle_infrastructure`と同じ入力を別目的で
    解釈しているため、両者は完全には独立ではない（同関数のdocstring参照、改善計画T62）。

    `is_designated`はKSJ N10（緊急輸送道路）・N12（重要物流道路）への該当（外部静的
    データソース T51、`domain/designation.py: CAR_STRESS_DESIGNATION_KINDS`）。
    大型車交通の代理指標として+1する（既存クランプ内、motor_vehicle=noの固定1より後段）。
    road_graph_repository.pyのMVT生成CASE式と1:1対応させる（test_road_graph_repository.pyの
    整合性テストで担保。判定ロジックの実装自体はここ1箇所にまとめ、`car_stress_level`は
    `level`だけを取り出す薄いラッパーにすることで二重実装を避ける）。

    採用している入力は一貫して「この区間で自動車とどれだけ近く・速く・多く接するか」という
    同一の構造を推定する手がかりに限定している（道路種別・車線数・制限速度・自転車インフラの
    有無・指定路線該当）。信号・一時停止等の停止密度や交差点密度は、質的に別種の負担
    （立ち止まる頻度・判断ポイントの多さ）であり、この構造の手がかりではないため、意図的に
    ここへは合成せず別軸（`distance_weighted_stop_density`・`distance_weighted_intersection_density`、
    それぞれ独立した重みでユーザーが調整できる）のまま残している（改善計画T92で明文化）。
    """
    recipe = recipe or DEFAULT_CAR_STRESS_RECIPE
    road_suitability_recipe = road_suitability_recipe or DEFAULT_ROAD_SUITABILITY_RECIPE
    motor_vehicle_density_recipe = motor_vehicle_density_recipe or DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE

    # 改善計画: 車との近さ材料の共有元化。「道路適正＋自動車密度」（N2、安全度側
    # domain/safety.py: safety_breakdownと共有）はdomain/recipe.py: car_closeness()へ
    # 切り出し済み。呼び出し側（compute_edge_cost）が既に計算済みならそれを使い、
    # 同一Edgeに対する二重計算を避ける。
    base, cycleway_adj, maxspeed_adj, lanes_high_adj, designation_adj = car_closeness_result or car_closeness(
        highway, tags, is_designated, road_suitability_recipe, motor_vehicle_density_recipe
    )
    if base is None:
        return CarStressBreakdown(
            base=None,
            cycleway_adjustment=0,
            maxspeed_adjustment=0,
            lanes_adjustment=0,
            designation_adjustment=0,
            motor_vehicle_no_override=False,
            level=None,
        )

    # motor_vehicle=no（自転車可）は他の補正に関わらず1に固定（計画書§2.4）。
    if tag_value_is(tags, "motor_vehicle", "no"):
        return CarStressBreakdown(
            base=base,
            cycleway_adjustment=0,
            maxspeed_adjustment=0,
            lanes_adjustment=0,
            designation_adjustment=0,
            motor_vehicle_no_override=True,
            level=1,
        )

    # 改善計画T92: 対面通行の1車線（センターラインなし等）は車の追い越し・すれ違いの
    # 圧迫感が少なく、4車線以上の+1（lanes_high_adj、car_closeness()由来）と対称に
    # 既定-1する（lanes_low、車ストレス軸のみが持つ補正。安全度は不採用）。
    #
    # lanes_lowは「車道を自転車と自動車が共有している」ことを前提にした補正のため、
    # 分離自転車道（cycleway_class=="track"）がある区間では該当しない（自転車は
    # その車道の車線数と無関係な位置を走る）。分離区間ではlow方向を無効化する
    # （high方向＝多車線・自動車の量は分離の有無に関わらず意味を持つため据え置き）。
    # 実データ確認（dev DB, 2026-08-19）ではlanes<=1かつcycleway_class=="track"の
    # 該当がほぼ皆無（対象highway中1件、最終levelへの影響も無し）で実害は無いに等しいが、
    # 「専用道があるのにすれ違い圧迫の緩和を追加で与える」という論理的な不整合を解消する。
    #
    # lanes_high（自動車密度レシピ由来）とlanes_low（このレシピ由来）は別レシピの値のため、
    # 1回のthreshold_adjustment呼び出しでは表現できない（low<highの前提が別レシピを
    # またぐと保証できない）。それぞれ独立に計算して加算する（値が同時に両方非ゼロになる
    # ことは無い: lanes<=1とlanes>=4は排他的）。
    lanes_low_threshold = None if cycleway_class(tags) == "track" else recipe.lanes_low_threshold
    lanes_low_adj = threshold_adjustment(parse_lanes(tags), lanes_low_threshold, recipe.lanes_low_adjustment, None, 0)
    lanes_adj = lanes_high_adj + lanes_low_adj

    # 改善計画（車ストレス5段階化）: 実データ実測（dev DB、39,857way・5,737.6km）で、
    # クランプ前の生値がraw>=5に8.3%（way数）/9.3%（距離）集中しており、primary/trunk/
    # 指定路線（N10/N12）で従来level4に丸め込まれ区別できなくなっていたことを確認した。
    # 上限を4→5へ拡張し、この区間を独立したlevel5として可視化する（下限1は変更なし。
    # level2（62%/56%）はタグ欠損由来の一極集中で、追加のタグ収集無しに細分化する材料が
    # 無いため据え置き）。
    level = clamp_level(base + cycleway_adj + maxspeed_adj + lanes_adj + designation_adj, 1, 5)

    return CarStressBreakdown(
        base=base,
        cycleway_adjustment=cycleway_adj,
        maxspeed_adjustment=maxspeed_adj,
        lanes_adjustment=lanes_adj,
        designation_adjustment=designation_adj,
        motor_vehicle_no_override=False,
        level=level,
    )


def car_stress_tile_ingredients(
    highway: str | None, tags: dict[str, str], is_designated: bool = False
) -> dict[str, object]:
    """車ストレスの材料タグを、road-surface-tilesのMVTが実際に焼き込むプロパティと
    同じ形（キー名・値の有無）で返す。`export_openapi.py`が書き出す相互検証フィクスチャ
    （car-stress-test-cases.json、フロントのcarStressExpression.test.tsが読む）専用。
    `_ROAD_SURFACE_TILE_MVT_SQL`同様、値がNoneの項目はキーごと省略する
    （ST_AsMVTがNULLプロパティを省略する挙動に合わせ、`["has", ...]`判定を正しく再現するため）。
    designationは実際は`emergency_transport`/`critical_logistics`/`both`の3値を取るが、
    車ストレスへの補正は「該当するか否か」しか見ないため、ここでは代表して
    `emergency_transport`のみを使う。
    """
    ingredients: dict[str, object] = {}
    if highway is not None:
        ingredients["highway"] = highway
    cycleway = cycleway_class(tags)
    if cycleway is not None:
        ingredients["cycleway_class"] = cycleway
    maxspeed = parse_maxspeed(tags)
    if maxspeed is not None:
        ingredients["maxspeed_kmh"] = maxspeed
    lanes = parse_lanes(tags)
    if lanes is not None:
        ingredients["lanes_count"] = lanes
    if tag_value_is(tags, "motor_vehicle", "no"):
        ingredients["motor_vehicle_no"] = True
    if is_designated:
        ingredients["designation"] = "emergency_transport"
    return ingredients


def car_stress_level(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool = False,
    recipe: CarStressRecipe | None = None,
    road_suitability_recipe: RoadSuitabilityRecipe | None = None,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
    *,
    car_closeness_result: tuple[int | None, int, int, int, int] | None = None,
) -> int | None:
    """車ストレス（1-5段階）の最終値のみを返す薄いラッパー。判定ロジックの実装・
    docstringは`car_stress_breakdown`参照。"""
    return car_stress_breakdown(
        highway,
        tags,
        is_designated,
        recipe,
        road_suitability_recipe,
        motor_vehicle_density_recipe,
        car_closeness_result=car_closeness_result,
    ).level
