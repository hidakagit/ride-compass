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

    def test_stop_poi_kinds_matches_literal_values(self):
        """STOP_POI_KINDS（SQL側kindフィルタの正準集合、改善計画T145b実装中に発見した
        補給POI誤算入バグの修正）がStopPoiKindのLiteral値と乖離しないことを確認する。"""
        from typing import get_args

        from app.domain.traffic import STOP_POI_KINDS, StopPoiKind

        assert STOP_POI_KINDS == frozenset(get_args(StopPoiKind))


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
