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


class TestPoiCountKinds:
    """集計キー（`POI_COUNT_KINDS`）と、それを作るSQLのCASE式が乖離しないことを固定する。

    キーの一覧はPython側（材料の生成元）にあり、実際に値を作るのはSQLのCASE式のため、
    片方だけ変えると「材料はあるが値が入らない」「値はあるが材料が無い」という静かな
    壊れ方をする。
    """

    def test_every_imported_kind_reaches_a_count_key(self):
        """取込対象の全kindが、いずれかの集計キーへ到達する（give_wayはstopへ畳む）。"""
        from app.domain.traffic import POI_COUNT_KINDS, STOP_POI_KINDS

        assert set(STOP_POI_KINDS) - {"give_way"} <= set(POI_COUNT_KINDS)

    def test_sql_case_expression_only_produces_known_keys(self):
        """SQLのCASE式が返すリテラルが、すべてPOI_COUNT_KINDSに存在する。"""
        import re

        from app.domain.traffic import POI_COUNT_KINDS
        from app.infrastructure.road_graph_repository import _POI_COUNT_KIND_EXPR

        produced = set(re.findall(r"THEN '([a-z_]+)'", _POI_COUNT_KIND_EXPR))
        assert produced
        assert produced <= set(POI_COUNT_KINDS)

    def test_every_count_key_has_a_material(self):
        """集計キーそれぞれに対応する材料が生成されている。"""
        from app.domain.material_catalog import MATERIAL_CATALOG
        from app.domain.traffic import POI_COUNT_KINDS

        for kind in POI_COUNT_KINDS:
            assert f"poi_{kind}_per_km" in MATERIAL_CATALOG


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
