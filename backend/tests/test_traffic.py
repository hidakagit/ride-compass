from app.domain.recipe import MotorVehicleDensityRecipe, RoadSuitabilityRecipe
from app.domain.traffic import (
    DEFAULT_TRAFFIC_STRESS_RECIPE,
    TrafficStressRecipe,
    classify_bicycle_infrastructure,
    classify_stop_poi,
    classify_supply_poi,
    distance_weighted_bicycle_infra_score,
    distance_weighted_intersection_density,
    distance_weighted_stop_density,
    is_dedicated_bicycle_infra,
    smoothness_score,
    traffic_stress_breakdown,
    traffic_stress_level,
)


class TestSmoothnessScore:
    def test_excellent_is_100(self):
        assert smoothness_score({"smoothness": "excellent"}) == 100.0

    def test_horrible_is_0(self):
        assert smoothness_score({"smoothness": "horrible"}) == 0.0

    def test_case_and_whitespace_insensitive(self):
        assert smoothness_score({"smoothness": " Good "}) == 85.0

    def test_missing_tag_is_none(self):
        assert smoothness_score({}) is None

    def test_unknown_value_is_none(self):
        assert smoothness_score({"smoothness": "mystery"}) is None


class TestClassifyBicycleInfrastructure:
    def test_highway_cycleway_is_separated(self):
        assert classify_bicycle_infrastructure({}, "cycleway") == "separated"

    def test_cycleway_track_is_separated(self):
        assert classify_bicycle_infrastructure({"cycleway": "track"}, "primary") == "separated"

    def test_cycleway_left_right_are_normalized(self):
        assert classify_bicycle_infrastructure({"cycleway:left": "track"}, "primary") == "separated"
        assert classify_bicycle_infrastructure({"cycleway:right": "lane"}, "primary") == "lane"

    def test_cycleway_lane_is_lane(self):
        assert classify_bicycle_infrastructure({"cycleway": "lane"}, "primary") == "lane"

    def test_shared_busway_or_shared_lane(self):
        assert classify_bicycle_infrastructure({"cycleway": "share_busway"}, "primary") == "shared_busway"
        assert classify_bicycle_infrastructure({"cycleway": "shared_lane"}, "primary") == "shared_busway"

    def test_footway_with_bicycle_designated_is_shared_pedestrian(self):
        assert classify_bicycle_infrastructure({"bicycle": "designated"}, "footway") == "shared_pedestrian"

    def test_path_with_bicycle_no_tag_is_roadway_not_shared(self):
        # bicycle=yes/designated/permissiveの明示が無ければ共用歩道扱いにしない
        assert classify_bicycle_infrastructure({}, "path") == "roadway"

    def test_bicycle_no_is_prohibited(self):
        assert classify_bicycle_infrastructure({"bicycle": "no"}, "residential") == "prohibited"

    def test_plain_highway_is_roadway(self):
        assert classify_bicycle_infrastructure({}, "residential") == "roadway"

    def test_no_highway_no_tags_is_unknown(self):
        assert classify_bicycle_infrastructure({}, None) == "unknown"

    def test_dedicated_cycleway_wins_over_bicycle_no(self):
        # 分離自転車道タグがある場合はbicycle=noより優先される（優先順位: separated>prohibited）
        assert classify_bicycle_infrastructure({"bicycle": "no"}, "cycleway") == "separated"


class TestTrafficStressLevel:
    def test_cycleway_base_is_1(self):
        assert traffic_stress_level("cycleway", {}) == 1

    def test_residential_base_is_2(self):
        assert traffic_stress_level("residential", {}) == 2

    def test_living_street_base_is_1(self):
        # 改善計画: 車との近さ材料の共有元化でROAD_SUITABILITY_BASE_BY_HIGHWAYへ統合した際、
        # 交通ストレス側のliving_street基準値が旧2→1へ変更された（安全度側の旧値1に合わせて
        # 統一。domain/recipe.py: ROAD_SUITABILITY_BASE_BY_HIGHWAY直上のコメント参照）。
        # この軸単位のエンドツーエンド値もピン留めする
        # （raw定数自体はTestRoadSuitabilityBaseByHighway、test_recipe.py参照）。
        assert traffic_stress_level("living_street", {}) == 1

    def test_tertiary_base_is_3(self):
        assert traffic_stress_level("tertiary", {}) == 3

    def test_secondary_base_is_3(self):
        # 改善計画T92: secondaryはprimary/trunkと分離しtertiaryと同じ3へ（実データ検証の
        # 結果、一律base=4だと指定路線の大半が最終値4/4に張り付いていたため）
        assert traffic_stress_level("secondary", {}) == 3

    def test_primary_base_is_4(self):
        assert traffic_stress_level("primary", {}) == 4

    def test_trunk_base_is_4(self):
        # primary/trunkは実データ上も最もストレスが高い区間のため4のまま維持（T92では変更なし）
        assert traffic_stress_level("trunk", {}) == 4

    def test_unknown_highway_is_none(self):
        assert traffic_stress_level("motorway", {}) is None
        assert traffic_stress_level(None, {}) is None

    def test_motor_vehicle_no_overrides_to_1_regardless_of_highway(self):
        assert traffic_stress_level("primary", {"motor_vehicle": "no"}) == 1

    def test_separated_cycleway_tag_reduces_by_2(self):
        assert traffic_stress_level("primary", {"cycleway": "track"}) == 2  # 4-2

    def test_cycleway_lane_reduces_by_1(self):
        assert traffic_stress_level("primary", {"cycleway": "lane"}) == 3  # 4-1

    def test_cycleway_shared_lane_reduces_by_1(self):
        # 改善計画T92: 自転車と共有の車道表示（シェアードレーン）もlaneと同じ-1
        assert traffic_stress_level("primary", {"cycleway": "shared_lane"}) == 3  # 4-1

    def test_cycleway_share_busway_reduces_by_1(self):
        assert traffic_stress_level("primary", {"cycleway": "share_busway"}) == 3  # 4-1

    def test_low_maxspeed_reduces_by_1(self):
        assert traffic_stress_level("primary", {"maxspeed": "30"}) == 3  # 4-1

    def test_high_maxspeed_increases_by_1(self):
        assert traffic_stress_level("tertiary", {"maxspeed": "60"}) == 4  # 3+1

    def test_many_lanes_increases_by_1(self):
        assert traffic_stress_level("tertiary", {"lanes": "4"}) == 4  # 3+1

    def test_single_lane_reduces_by_1(self):
        # 改善計画T92: 対面通行の1車線は4車線以上の+1と対称に-1
        assert traffic_stress_level("primary", {"lanes": "1"}) == 3  # 4-1

    def test_single_lane_does_not_reduce_when_separated_cycleway_present(self):
        # lanes_lowは「車道を自転車と自動車が共有している」前提の補正のため、分離自転車道
        # （cycleway=track）がある区間では該当しない（自転車はその車道の車線数と無関係な
        # 位置を走る）。track単体の-2のみが効き、lanes_lowの追加-1は乗らない。
        assert traffic_stress_level("primary", {"lanes": "1", "cycleway": "track"}) == 2  # 4-2

    def test_single_lane_still_reduces_with_non_separated_cycleway(self):
        # lane/shared（車道上のペイント区分のみ、物理分離無し）は車道共有の前提が保たれるため
        # lanes_lowは通常どおり適用される（trackだけが特別扱い）。
        assert traffic_stress_level("primary", {"lanes": "1", "cycleway": "lane"}) == 2  # 4-1-1

    def test_two_or_three_lanes_does_not_apply_adjustment(self):
        # 2〜3車線は現状どおり中立（補正なし）
        assert traffic_stress_level("primary", {"lanes": "2"}) == 4
        assert traffic_stress_level("primary", {"lanes": "3"}) == 4

    def test_result_is_clamped_to_1_5_range(self):
        # cycleway基本値1から更に-2しても1未満にはならない
        assert traffic_stress_level("cycleway", {"cycleway": "track", "maxspeed": "20"}) == 1
        # primary基本値4+maxspeed(+1)+lanes(+1)=6だが上限5でクランプ
        assert traffic_stress_level("primary", {"maxspeed": "80", "lanes": "6"}) == 5

    def test_unset_tags_do_not_apply_corrections(self):
        # 補正はタグが実際にある場合のみ適用する（unknownは補正しない）
        assert traffic_stress_level("tertiary", {}) == 3

    def test_is_designated_increases_by_1(self):
        # 外部静的データソース T51（KSJ N10/N12該当の+1補正）。
        assert traffic_stress_level("residential", {}, is_designated=True) == 3  # 2+1

    def test_is_designated_defaults_to_false(self):
        assert traffic_stress_level("residential", {}) == 2

    def test_is_designated_on_primary_reaches_5(self):
        # 改善計画（交通ストレス5段階化）以前は上限4でクランプされ、指定路線に該当する
        # primary/trunkが「素の幹線」と区別できなくなっていた（実データ実測で該当区間の
        # 39.2%を占めると確認）。4(base)+1(designated)=5はクランプ不要でそのまま5になる。
        assert traffic_stress_level("primary", {}, is_designated=True) == 5

    def test_is_designated_does_not_override_motor_vehicle_no_fixed_1(self):
        assert traffic_stress_level("primary", {"motor_vehicle": "no"}, is_designated=True) == 1


class TestTrafficStressBreakdown:
    # traffic_stress_levelはtraffic_stress_breakdown(...).levelの薄いラッパーのため、
    # 最終値の網羅的な境界値検証はTestTrafficStressLevel側に任せ、ここでは内訳フィールド
    # （改善計画T90、区間クリック時の判定根拠表示）が正しく分解されることだけを確認する。
    def test_unknown_highway_has_none_base_and_level_with_zeroed_adjustments(self):
        breakdown = traffic_stress_breakdown("motorway", {})
        assert breakdown.base is None
        assert breakdown.level is None
        assert breakdown.cycleway_adjustment == 0
        assert breakdown.maxspeed_adjustment == 0
        assert breakdown.lanes_adjustment == 0
        assert breakdown.designation_adjustment == 0
        assert breakdown.motor_vehicle_no_override is False

    def test_motor_vehicle_no_overrides_with_flag_set_and_other_adjustments_zeroed(self):
        # 補正が実際に効く条件(track+高速+多車線+指定路線)を重ねても、固定1が優先される
        breakdown = traffic_stress_breakdown(
            "primary", {"motor_vehicle": "no", "cycleway": "track", "maxspeed": "80", "lanes": "6"}, is_designated=True
        )
        assert breakdown.base == 4
        assert breakdown.motor_vehicle_no_override is True
        assert breakdown.level == 1
        assert breakdown.cycleway_adjustment == 0
        assert breakdown.maxspeed_adjustment == 0
        assert breakdown.lanes_adjustment == 0
        assert breakdown.designation_adjustment == 0

    def test_all_adjustments_reported_individually(self):
        breakdown = traffic_stress_breakdown(
            "tertiary", {"cycleway": "lane", "maxspeed": "60", "lanes": "4"}, is_designated=True
        )
        assert breakdown.base == 3
        assert breakdown.cycleway_adjustment == -1
        assert breakdown.maxspeed_adjustment == 1
        assert breakdown.lanes_adjustment == 1
        assert breakdown.designation_adjustment == 1
        assert breakdown.motor_vehicle_no_override is False
        # 3 - 1 + 1 + 1 + 1 = 5、上限5ちょうどでクランプ不要
        assert breakdown.level == 5

    def test_lanes_low_suppressed_by_separated_cycleway_reported_in_breakdown(self):
        breakdown = traffic_stress_breakdown("primary", {"lanes": "1", "cycleway": "track"})
        assert breakdown.cycleway_adjustment == -2
        assert breakdown.lanes_adjustment == 0
        assert breakdown.level == 2

    def test_level_matches_traffic_stress_level_for_same_inputs(self):
        # 薄いラッパー(traffic_stress_level)と実装(traffic_stress_breakdown)が食い違わないこと
        highway, tags, is_designated = "residential", {"cycleway": "track", "maxspeed": "30"}, True
        assert traffic_stress_breakdown(highway, tags, is_designated).level == traffic_stress_level(
            highway, tags, is_designated
        )


class TestTrafficStressRecipeOverride:
    """改善計画（交通ストレスレシピ外出し基盤・車との近さ材料の共有元化）: recipe引数
    （交通ストレス軸固有の少車線補正）・road_suitability_recipe引数（highway別基準値・
    cycleway補正）・motor_vehicle_density_recipe引数（制限速度・車線数[多い方]・指定路線
    補正）でそれぞれ上書きできることを確認する。省略時（既定レシピ）の挙動は
    TestTrafficStressLevel/TestTrafficStressBreakdownで既に網羅済みのため、ここでは
    「上書きが実際に効くこと」「他の呼び出し・既定レシピ自体に副作用が漏れないこと」
    に絞る。
    """

    def test_lanes_low_adjustment_override(self):
        recipe = TrafficStressRecipe(lanes_low_adjustment=-3)
        assert traffic_stress_level("primary", {"lanes": "1"}, recipe=recipe) == 1  # 4-3

    def test_base_by_highway_override_changes_base(self):
        road_suitability_recipe = RoadSuitabilityRecipe(base_by_highway={"secondary": 2})
        assert traffic_stress_level("secondary", {}, road_suitability_recipe=road_suitability_recipe) == 2
        # 既定レシピでは3のまま(上書きがDEFAULT_ROAD_SUITABILITY_RECIPEを書き換えていないこと)
        assert traffic_stress_level("secondary", {}) == 3

    def test_cycleway_adjustment_override(self):
        road_suitability_recipe = RoadSuitabilityRecipe(cycleway_lane_adjustment=-3)
        assert (
            traffic_stress_level("primary", {"cycleway": "lane"}, road_suitability_recipe=road_suitability_recipe)
            == 1
        )  # 4-3

    def test_maxspeed_threshold_override(self):
        motor_vehicle_density_recipe = MotorVehicleDensityRecipe(maxspeed_high_threshold=40)
        assert (
            traffic_stress_level(
                "tertiary", {"maxspeed": "40"}, motor_vehicle_density_recipe=motor_vehicle_density_recipe
            )
            == 4
        )  # 3+1
        # 既定レシピ(閾値60)では40は補正なし
        assert traffic_stress_level("tertiary", {"maxspeed": "40"}) == 3

    def test_designation_adjustment_override(self):
        motor_vehicle_density_recipe = MotorVehicleDensityRecipe(designation_adjustment=2)
        assert (
            traffic_stress_level(
                "residential", {}, is_designated=True, motor_vehicle_density_recipe=motor_vehicle_density_recipe
            )
            == 4
        )  # 2+2

    def test_motor_vehicle_no_override_ignores_recipe(self):
        # motor_vehicle=noは常に1固定で、レシピの補正量に関わらず変わらない
        road_suitability_recipe = RoadSuitabilityRecipe(cycleway_lane_adjustment=-3)
        motor_vehicle_density_recipe = MotorVehicleDensityRecipe(designation_adjustment=3)
        assert (
            traffic_stress_level(
                "primary",
                {"motor_vehicle": "no"},
                is_designated=True,
                road_suitability_recipe=road_suitability_recipe,
                motor_vehicle_density_recipe=motor_vehicle_density_recipe,
            )
            == 1
        )

    def test_default_recipe_matches_default_traffic_stress_recipe_constant(self):
        assert TrafficStressRecipe() == DEFAULT_TRAFFIC_STRESS_RECIPE


class TestClassifyStopPoi:
    def test_traffic_signals(self):
        assert classify_stop_poi({"highway": "traffic_signals"}) == "traffic_signals"

    def test_crossing(self):
        assert classify_stop_poi({"highway": "crossing"}) == "crossing"

    def test_stop(self):
        assert classify_stop_poi({"highway": "stop"}) == "stop"

    def test_give_way(self):
        assert classify_stop_poi({"highway": "give_way"}) == "give_way"

    def test_level_crossing(self):
        assert classify_stop_poi({"railway": "level_crossing"}) == "level_crossing"

    def test_level_crossing_takes_priority_over_highway(self):
        # 踏切と横断歩道タグが同一nodeに同居する場合、踏切側を優先する（一時停止義務が強いため）
        assert classify_stop_poi({"highway": "crossing", "railway": "level_crossing"}) == "level_crossing"

    def test_case_and_whitespace_insensitive(self):
        assert classify_stop_poi({"highway": " Traffic_Signals "}) == "traffic_signals"

    def test_missing_tags_is_none(self):
        assert classify_stop_poi({}) is None

    def test_unrelated_highway_value_is_none(self):
        assert classify_stop_poi({"highway": "residential"}) is None


class TestClassifySupplyPoi:
    def test_convenience_store(self):
        assert classify_supply_poi({"shop": "convenience"}) == "convenience"

    def test_vending_machine(self):
        assert classify_supply_poi({"amenity": "vending_machine"}) == "vending_machine"

    def test_toilets(self):
        assert classify_supply_poi({"amenity": "toilets"}) == "toilets"

    def test_drinking_water(self):
        assert classify_supply_poi({"amenity": "drinking_water"}) == "drinking_water"

    def test_bicycle_parking(self):
        assert classify_supply_poi({"amenity": "bicycle_parking"}) == "bicycle_parking"

    def test_case_and_whitespace_insensitive(self):
        assert classify_supply_poi({"shop": " Convenience "}) == "convenience"

    def test_missing_tags_is_none(self):
        assert classify_supply_poi({}) is None

    def test_unrelated_shop_value_is_none(self):
        assert classify_supply_poi({"shop": "supermarket"}) is None

    def test_unrelated_amenity_value_is_none(self):
        assert classify_supply_poi({"amenity": "restaurant"}) is None

    def test_does_not_match_stop_poi_tags(self):
        assert classify_supply_poi({"highway": "traffic_signals"}) is None


class TestDistanceWeightedStopDensity:
    def test_sums_counts_over_total_distance(self):
        # 2区間: 1kmに2回、3kmに2回 -> 合計4回/合計4km = 1.0回/km
        assert distance_weighted_stop_density([(1.0, 2), (3.0, 2)]) == 1.0

    def test_is_total_ratio_not_average_of_rates(self):
        # 単純平均(2.0回/kmと0回/kmの平均=1.0)ではなく、合計count/合計distanceになる
        # 0.1kmに2回(20回/km相当)＋9.9kmに0回 -> 2/10.0 = 0.2回/km
        assert distance_weighted_stop_density([(0.1, 2), (9.9, 0)]) == 0.2

    def test_zero_total_distance_returns_none(self):
        assert distance_weighted_stop_density([(0.0, 3)]) is None

    def test_empty_returns_none(self):
        assert distance_weighted_stop_density([]) is None

    def test_no_stops_is_zero(self):
        assert distance_weighted_stop_density([(5.0, 0)]) == 0.0

    def test_none_counts_are_excluded_not_treated_as_zero(self):
        # データ未取得(None)の区間は実測0とは区別し、集計から除外する（残り区間で再正規化）
        assert distance_weighted_stop_density([(1.0, 2), (9.0, None)]) == 2.0

    def test_all_none_counts_return_none(self):
        assert distance_weighted_stop_density([(1.0, None), (2.0, None)]) is None


class TestDistanceWeightedIntersectionDensity:
    # distance_weighted_stop_densityと同じ集約ロジック（_density_per_km共有）のため
    # 基本ケースのみ確認する。詳細な境界値は上のTestDistanceWeightedStopDensity参照。
    def test_sums_counts_over_total_distance(self):
        assert distance_weighted_intersection_density([(1.0, 1), (3.0, 1)]) == 0.5

    def test_none_counts_are_excluded_not_treated_as_zero(self):
        assert distance_weighted_intersection_density([(1.0, 2), (9.0, None)]) == 2.0

    def test_empty_returns_none(self):
        assert distance_weighted_intersection_density([]) is None


class TestIsDedicatedBicycleInfra:
    def test_separated_is_dedicated(self):
        assert is_dedicated_bicycle_infra("separated") is True

    def test_lane_is_dedicated(self):
        assert is_dedicated_bicycle_infra("lane") is True

    def test_roadway_is_not_dedicated(self):
        assert is_dedicated_bicycle_infra("roadway") is False

    def test_shared_pedestrian_is_not_dedicated(self):
        assert is_dedicated_bicycle_infra("shared_pedestrian") is False

    def test_none_passthrough(self):
        assert is_dedicated_bicycle_infra(None) is None

    def test_unknown_is_treated_as_none_not_false(self):
        # classify_bicycle_infrastructureは判定不能(highway等が無い)場合Noneではなく
        # "unknown"を返す。ここでFalse扱いすると「データ欠損」が
        # distance_weighted_bicycle_infra_scoreの分母に「非専用インフラ確定」として
        # 混入してしまう(ORSエンジンでway_tagsの空間マッチに失敗した区間で発生しうる)。
        assert is_dedicated_bicycle_infra("unknown") is None


class TestDistanceWeightedBicycleInfraScore:
    def test_distance_weighted_percent_of_dedicated_infra(self):
        # 3kmが専用インフラ・1kmが非専用 -> 75%
        assert distance_weighted_bicycle_infra_score([(3.0, True), (1.0, False)]) == 75.0

    def test_all_dedicated_is_100_percent(self):
        assert distance_weighted_bicycle_infra_score([(5.0, True)]) == 100.0

    def test_unknown_segments_excluded_from_denominator(self):
        # Noneの区間(5km)は分母から除外し、残り2区間だけで計算する -> 1km/(1km+1km) = 50%
        assert distance_weighted_bicycle_infra_score([(1.0, True), (1.0, False), (5.0, None)]) == 50.0

    def test_all_unknown_returns_none(self):
        assert distance_weighted_bicycle_infra_score([(1.0, None), (2.0, None)]) is None

    def test_zero_known_distance_returns_none(self):
        assert distance_weighted_bicycle_infra_score([]) is None
