from app.domain.traffic import classify_stop_poi, classify_supply_poi


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

    def test_barrier_values_are_classified(self):
        # T654で追加したkind。分類器側にテストが無いと、_BARRIER_STOP_VALUESを増減しても
        # 取込プロファイル側さえ変えなければどのテストも赤くならない。
        for value in ["cycle_barrier", "bollard", "gate", "lift_gate", "stile", "block", "chain"]:
            assert classify_stop_poi({"barrier": value}) == "barrier", value

    def test_traffic_calming_values_are_classified(self):
        for value in ["hump", "bump", "table", "cushion", "chicane", "rumble_strip"]:
            assert classify_stop_poi({"traffic_calming": value}) == "traffic_calming", value

    def test_barrier_values_deliberately_left_out_are_not_stop_factors(self):
        """`_BARRIER_STOP_VALUES`から**意図的に外した**値（traffic.pyのコメント参照）。

        ここを固定しないと、`kerb`のような「該当件数が多いが停止要因として識別力が無い」値を
        足しても分類器のテストは1件も落ちず、停止密度だけが実データで跳ね上がる。
        """
        for value in ["kerb", "toll_booth", "entrance", "fence", "wall", "guard_rail", "jersey_barrier"]:
            assert classify_stop_poi({"barrier": value}) is None, value

    def test_traffic_calming_values_deliberately_left_out(self):
        # island（中央島）・noは進行を妨げない。
        for value in ["island", "no"]:
            assert classify_stop_poi({"traffic_calming": value}) is None, value

    def test_railway_takes_priority_over_barrier(self):
        # 踏切に車止めが併設されている点。止まる理由としては踏切の方が強い。
        assert classify_stop_poi({"railway": "level_crossing", "barrier": "gate"}) == "level_crossing"

    def test_stop_poi_kinds_matches_literal_values(self):
        """STOP_POI_KINDS（SQL側kindフィルタの正準集合、改善計画T145b実装中に発見した
        補給POI誤算入バグの修正）がStopPoiKindのLiteral値と乖離しないことを確認する。"""
        from typing import get_args

        from app.domain.traffic import STOP_POI_KINDS, StopPoiKind

        assert STOP_POI_KINDS == frozenset(get_args(StopPoiKind))


class TestClassifySupplyPoi:
    def test_convenience_store(self):
        assert classify_supply_poi({"shop": "convenience"}) == "convenience"

    def test_vending_machine_selling_drinks(self):
        assert classify_supply_poi({"amenity": "vending_machine", "vending": "drinks"}) == "vending_drinks"

    def test_vending_machine_selling_drinks_among_others(self):
        """複数の値は`;`で連結される。1つでも飲食物があれば飲料自販機として扱う。"""
        assert (
            classify_supply_poi({"amenity": "vending_machine", "vending": "cigarettes;drinks"})
            == "vending_drinks"
        )

    def test_vending_machine_without_vending_tag_is_unknown(self):
        """タグが無いものを「買えない」側へ寄せない（日本では飲料でも付けない慣習がある）。"""
        assert classify_supply_poi({"amenity": "vending_machine"}) == "vending_unknown"
        assert classify_supply_poi({"amenity": "vending_machine", "vending": " "}) == "vending_unknown"

    def test_vending_machine_selling_nothing_edible_is_not_a_supply_poi(self):
        """たばこ・切符・パーキング券の機械は取り込まない（当てにされると買えない）。"""
        for value in ("cigarettes", "parking_tickets", "public_transport_tickets", "condoms"):
            assert classify_supply_poi({"amenity": "vending_machine", "vending": value}) is None

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

