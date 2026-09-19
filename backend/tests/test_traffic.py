from app.domain import tuning
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


class TestPoiCountKinds:
    """集計キー（`POI_COUNT_KINDS`）と、それを作るSQLのCASE式が乖離しないことを固定する。

    キーの一覧はPython側（材料の生成元）にあり、実際に値を作るのはSQLのCASE式のため、
    片方だけ変えると「材料はあるが値が入らない」「値はあるが材料が無い」という静かな
    壊れ方をする。
    """

    def test_sql_case_expression_and_key_list_match_exactly(self):
        """SQLのCASE式が返すキーと`POI_COUNT_KINDS`が完全に一致する。

        片方だけ増えると「材料はあるが値が入らない」「値はあるが材料が無い」という
        静かな壊れ方をするため、包含ではなく一致で固定する。
        """
        import re

        from app.domain.traffic import POI_COUNT_KINDS
        from app.infrastructure.road_graph_repository import _POI_COUNT_KIND_EXPR

        produced = set(re.findall(r"(?:THEN|ELSE) '([a-z_]+)'", _POI_COUNT_KIND_EXPR))
        assert produced == set(POI_COUNT_KINDS)

    def test_case_expression_has_an_else_branch_so_no_kind_is_dropped(self):
        """ELSE句があること＝取込対象のどのkindも必ずいずれかのキーへ落ちる。"""
        from app.infrastructure.road_graph_repository import _POI_COUNT_KIND_EXPR

        assert "ELSE" in _POI_COUNT_KIND_EXPR

    def test_both_ways_of_tagging_a_signal_map_to_the_same_key(self):
        """信号は`highway=traffic_signals`と`highway=crossing`＋`crossing=traffic_signals`の
        2通りで書かれる。別キーにすると1つの信号交差点が両方へ計上されて二重になるため、
        同じキーへ落ちることを固定する。"""
        from app.infrastructure.road_graph_repository import _POI_COUNT_KIND_EXPR

        lines = [line for line in _POI_COUNT_KIND_EXPR.splitlines() if "'signal'" in line]
        assert len(lines) == 2
        assert any("traffic_signals'" in line and "crossing" not in line for line in lines)
        assert any("crossing" in line and "signals%" in line for line in lines)

    def test_every_count_key_has_a_material(self):
        """集計キーそれぞれに対応する材料が生成されている。"""
        from app.domain.material_catalog import MATERIAL_CATALOG
        from app.domain.traffic import POI_COUNT_KINDS

        for kind in POI_COUNT_KINDS:
            assert f"poi_{kind}_per_km" in MATERIAL_CATALOG


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


class TestSignalMatchRadius:
    """信号判定の半径が、同じ交差点の点をまとめる距離から独立していること。

    2つは同じ値だが問うていることが違う（あちらは「同じ停止か」、こちらは「この交差点に
    信号があるか」）。まとめる距離を動かしたときに走行モデルの横断の費用まで動くと、
    直した側が正しく動くぶんだけ較正が静かに巻き戻る。
    """

    def test_signal_radius_does_not_follow_the_poi_cluster_distance(self, monkeypatch):
        from app.infrastructure import road_graph_repository

        monkeypatch.setattr(road_graph_repository, "POI_CLUSTER_EPS_M", 999.0)

        params = road_graph_repository.signal_radius_params()

        assert params["signal_radius_m"] == tuning.tuning_value("signal.match_radius_m")

    def test_signal_radius_moves_with_the_declared_calibration_value(self, monkeypatch):
        from app.infrastructure import road_graph_repository

        monkeypatch.setitem(tuning.TUNING_VALUES, "signal.match_radius_m", 123.0)

        params = road_graph_repository.signal_radius_params()

        assert params["signal_radius_m"] == 123.0
        # 粗い矩形（GiST索引用）も同じ値から導く。片方だけ古い値のままだと、索引で
        # 落としたぶんは半径の判定まで届かない。
        assert params["signal_radius_deg"] == 123.0 / 111_000.0 * 2.0
