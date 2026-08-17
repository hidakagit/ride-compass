from app.domain.safety import (
    DEFAULT_SAFETY_RECIPE,
    SafetyRecipe,
    safety_breakdown,
    safety_level,
)


class TestSafetyLevel:
    def test_cycleway_base_is_1(self):
        assert safety_level("cycleway", {}) == 1

    def test_residential_base_is_2(self):
        assert safety_level("residential", {}) == 2

    def test_tertiary_base_is_3(self):
        # 改善計画T121: 事故密度実測（residential/unclassifiedより明確に高くsecondaryに
        # 近いlanes/maxspeed分布）を根拠に2から引き上げ。
        assert safety_level("tertiary", {}) == 3

    def test_secondary_base_is_3(self):
        assert safety_level("secondary", {}) == 3

    def test_primary_base_is_4(self):
        assert safety_level("primary", {}) == 4

    def test_trunk_base_is_4(self):
        assert safety_level("trunk", {}) == 4

    def test_unknown_highway_is_none(self):
        assert safety_level("motorway", {}) is None
        assert safety_level(None, {}) is None

    def test_motor_vehicle_no_overrides_to_1_regardless_of_highway(self):
        assert safety_level("primary", {"motor_vehicle": "no"}) == 1

    def test_separated_cycleway_tag_reduces_by_2(self):
        assert safety_level("primary", {"cycleway": "track"}) == 2  # 4-2

    def test_cycleway_lane_reduces_by_1(self):
        assert safety_level("primary", {"cycleway": "lane"}) == 3  # 4-1

    def test_cycleway_shared_lane_reduces_by_1(self):
        assert safety_level("primary", {"cycleway": "shared_lane"}) == 3  # 4-1

    def test_low_maxspeed_reduces_by_1(self):
        assert safety_level("primary", {"maxspeed": "30"}) == 3  # 4-1

    def test_high_maxspeed_increases_by_1(self):
        assert safety_level("tertiary", {"maxspeed": "60"}) == 4  # 3+1

    def test_many_lanes_increases_by_1(self):
        assert safety_level("tertiary", {"lanes": "4"}) == 4  # 3+1

    def test_invalid_zero_lanes_and_maxspeed_are_ignored(self):
        # SQL側(_ROAD_SURFACE_TILE_MVT_SQL)・parse_lanes/parse_maxspeedと同じく
        # 0以下は無効値としてキー自体を無視する(補正が誤発火しない)。
        assert safety_level("primary", {"lanes": "0"}) == 4
        assert safety_level("primary", {"maxspeed": "0"}) == 4

    def test_shoulder_reduces_by_1(self):
        assert safety_level("secondary", {"shoulder": "yes"}) == 2  # 3-1

    def test_lit_reduces_by_1(self):
        assert safety_level("secondary", {"lit": "yes"}) == 2  # 3-1

    def test_tunnel_increases_by_1(self):
        assert safety_level("secondary", {"tunnel": "yes"}) == 4  # 3+1

    def test_shoulder_lit_tunnel_combine(self):
        assert safety_level("secondary", {"shoulder": "yes", "lit": "yes", "tunnel": "yes"}) == 2  # 3-1-1+1

    def test_result_is_clamped_to_1_4_range(self):
        # cycleway基本値1から更に-2しても1未満にはならない
        assert safety_level("cycleway", {"cycleway": "track", "maxspeed": "20"}) == 1
        # primary基本値4に複数の増加要因が重なっても4を超えない
        assert safety_level("primary", {"maxspeed": "80", "lanes": "6", "tunnel": "yes"}) == 4

    def test_unset_tags_do_not_apply_corrections(self):
        assert safety_level("tertiary", {}) == 3

    def test_is_designated_increases_by_1(self):
        assert safety_level("residential", {}, is_designated=True) == 3  # 2+1

    def test_is_designated_defaults_to_false(self):
        assert safety_level("residential", {}) == 2

    def test_is_designated_clamped_to_4(self):
        assert safety_level("primary", {}, is_designated=True) == 4

    def test_is_designated_does_not_override_motor_vehicle_no_fixed_1(self):
        assert safety_level("primary", {"motor_vehicle": "no"}, is_designated=True) == 1


class TestSafetyBreakdown:
    # safety_levelはsafety_breakdown(...).levelの薄いラッパーのため、最終値の網羅的な
    # 境界値検証はTestSafetyLevel側に任せ、ここでは内訳フィールド（区間クリック時の
    # 判定根拠表示）が正しく分解されることだけを確認する。
    def test_unknown_highway_has_none_base_and_level_with_zeroed_adjustments(self):
        breakdown = safety_breakdown("motorway", {})
        assert breakdown.base is None
        assert breakdown.level is None
        assert breakdown.cycleway_adjustment == 0
        assert breakdown.maxspeed_adjustment == 0
        assert breakdown.lanes_adjustment == 0
        assert breakdown.shoulder_adjustment == 0
        assert breakdown.lit_adjustment == 0
        assert breakdown.tunnel_adjustment == 0
        assert breakdown.designation_adjustment == 0
        assert breakdown.motor_vehicle_no_override is False

    def test_motor_vehicle_no_overrides_with_flag_set_and_other_adjustments_zeroed(self):
        breakdown = safety_breakdown(
            "primary",
            {"motor_vehicle": "no", "cycleway": "track", "maxspeed": "80", "lanes": "6", "tunnel": "yes"},
            is_designated=True,
        )
        assert breakdown.base == 4
        assert breakdown.motor_vehicle_no_override is True
        assert breakdown.level == 1
        assert breakdown.cycleway_adjustment == 0
        assert breakdown.maxspeed_adjustment == 0
        assert breakdown.lanes_adjustment == 0
        assert breakdown.shoulder_adjustment == 0
        assert breakdown.lit_adjustment == 0
        assert breakdown.tunnel_adjustment == 0
        assert breakdown.designation_adjustment == 0

    def test_all_adjustments_reported_individually(self):
        breakdown = safety_breakdown(
            "tertiary",
            {"cycleway": "lane", "maxspeed": "60", "lanes": "4", "shoulder": "yes", "lit": "yes", "tunnel": "yes"},
            is_designated=True,
        )
        assert breakdown.base == 3
        assert breakdown.cycleway_adjustment == -1
        assert breakdown.maxspeed_adjustment == 1
        assert breakdown.lanes_adjustment == 1
        assert breakdown.shoulder_adjustment == -1
        assert breakdown.lit_adjustment == -1
        assert breakdown.tunnel_adjustment == 1
        assert breakdown.designation_adjustment == 1
        assert breakdown.motor_vehicle_no_override is False
        # 3 - 1 + 1 + 1 - 1 - 1 + 1 + 1 = 4
        assert breakdown.level == 4

    def test_level_matches_safety_level_for_same_inputs(self):
        highway, tags, is_designated = "residential", {"cycleway": "track", "maxspeed": "30", "lit": "yes"}, True
        assert safety_breakdown(highway, tags, is_designated).level == safety_level(highway, tags, is_designated)


class TestSafetyRecipeOverride:
    """改善計画（安全度レシピ）: recipe引数でbase_by_highway・各補正の閾値・補正量を
    上書きできることを確認する。recipe省略時（既定レシピ）の挙動はTestSafetyLevel/
    TestSafetyBreakdownで既に網羅済みのため、ここでは「上書きが実際に効くこと」
    「他の呼び出し・既定レシピ自体に副作用が漏れないこと」に絞る
    （TestTrafficStressRecipeOverrideと同じ観点）。
    """

    def test_base_by_highway_override_changes_base(self):
        recipe = SafetyRecipe(base_by_highway={"secondary": 2})
        assert safety_level("secondary", {}, recipe=recipe) == 2
        # 既定レシピでは3のまま(上書きがDEFAULT_SAFETY_RECIPEを書き換えていないこと)
        assert safety_level("secondary", {}) == 3

    def test_cycleway_adjustment_override(self):
        recipe = SafetyRecipe(cycleway_lane_adjustment=-3)
        assert safety_level("primary", {"cycleway": "lane"}, recipe=recipe) == 1  # 4-3

    def test_maxspeed_threshold_override(self):
        recipe = SafetyRecipe(maxspeed_high_threshold=40)
        assert safety_level("tertiary", {"maxspeed": "40"}, recipe=recipe) == 4  # 3+1
        # 既定レシピ(閾値60)では40は補正なし
        assert safety_level("tertiary", {"maxspeed": "40"}) == 3

    def test_shoulder_adjustment_override(self):
        recipe = SafetyRecipe(shoulder_adjustment=-2)
        assert safety_level("secondary", {"shoulder": "yes"}, recipe=recipe) == 1  # 3-2

    def test_lit_adjustment_override(self):
        recipe = SafetyRecipe(lit_adjustment=-2)
        assert safety_level("secondary", {"lit": "yes"}, recipe=recipe) == 1  # 3-2

    def test_tunnel_adjustment_override(self):
        recipe = SafetyRecipe(tunnel_adjustment=2)
        assert safety_level("tertiary", {"tunnel": "yes"}, recipe=recipe) == 4  # 3+2=5, clamped to 4

    def test_designation_adjustment_override(self):
        recipe = SafetyRecipe(designation_adjustment=2)
        assert safety_level("residential", {}, is_designated=True, recipe=recipe) == 4  # 2+2

    def test_motor_vehicle_no_override_ignores_recipe(self):
        # motor_vehicle=noは常に1固定で、レシピの補正量に関わらず変わらない
        recipe = SafetyRecipe(cycleway_lane_adjustment=-3, designation_adjustment=3)
        assert safety_level("primary", {"motor_vehicle": "no"}, is_designated=True, recipe=recipe) == 1

    def test_default_recipe_matches_default_safety_recipe_constant(self):
        assert SafetyRecipe() == DEFAULT_SAFETY_RECIPE
