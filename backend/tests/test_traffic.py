"""`domain/traffic.py`——OSMタグから派生する分類と、所要時間モデルのパラメータ。

引き当てそのものはDB側で行うため、**表が実際にどう当たるか**は
`test_tag_classification.py`（種別）と`test_resolve_direction.py`（通行方向）が
DBへ通して確かめる。ここで見るのは、表の組み立てと純関数。
"""


from app.domain.traffic import (
    MAJOR_CROSSING_MIN_RANK,
    POI_COUNT_KINDS,
    TAG_KIND_RULES,
    highway_rank,
    stop_count_material_ids,
    stop_seconds,
)
from app.domain.tuning import TUNING_VALUES, stop_seconds_parameter_id


class TestStopSeconds:
    def test_every_counted_kind_declares_its_own_value(self):
        """**0が返ったのが宣言の結果か、未知として落ちた結果かは戻り値から区別できない**。
        数える種別すべてに宣言があることを、宣言の側で確かめる（信号の無い横断歩道は
        意図的に0）。
        """
        assert POI_COUNT_KINDS, "数える種別が空なら、下のループは何も確かめていない"

        for kind in POI_COUNT_KINDS:
            assert stop_seconds_parameter_id(kind) in TUNING_VALUES, kind

    def test_an_unknown_kind_costs_nothing(self):
        """知らない種別で所要時間を膨らませない。"""
        assert stop_seconds("no_such_kind") == 0.0

    def test_the_value_comes_from_the_tuning_declaration(self):
        """ここへ数字を書き写すと、変えた値が反映されているかを誰も見なくなる。"""
        kind = next(iter(POI_COUNT_KINDS))

        assert stop_seconds(kind) == TUNING_VALUES[stop_seconds_parameter_id(kind)]


class TestStopCountMaterialIds:
    def test_there_is_one_material_for_every_counted_kind(self):
        assert len(stop_count_material_ids()) == len(POI_COUNT_KINDS)

    def test_the_id_is_built_from_the_kind(self):
        """材料idは種別から組み立てる。**その材料が実在するかはここでは見ない**——
        `traffic.py`は材料カタログを知らず、綴りの正しさはカタログ側の話。
        """
        assert set(stop_count_material_ids()) == {f"poi_{kind}_per_km" for kind in POI_COUNT_KINDS}


class TestHighwayRank:
    def test_a_bigger_road_ranks_above_a_smaller_one(self):
        assert highway_rank("trunk") > highway_rank("primary") > highway_rank("residential")

    def test_a_link_shares_the_rank_of_the_road_it_joins(self):
        """ランプは本線と同じ扱い。分けると合流待ちの判定が本線とずれる。"""
        assert highway_rank("primary_link") == highway_rank("primary")

    def test_cycleways_and_footways_rank_lowest(self):
        """階級表に無い道は0。自転車道から出るときに「上位の道と交わる」とみなさない。"""
        assert highway_rank("cycleway") == 0
        assert highway_rank("footway") == 0

    def test_a_missing_or_unknown_tag_ranks_lowest(self):
        assert highway_rank(None) == 0
        assert highway_rank("") == 0
        assert highway_rank("no_such_highway") == 0

    def test_waiting_is_required_only_above_the_quiet_streets(self):
        assert highway_rank("residential") < MAJOR_CROSSING_MIN_RANK
        assert highway_rank("service") < MAJOR_CROSSING_MIN_RANK
        assert highway_rank("tertiary") >= MAJOR_CROSSING_MIN_RANK


class TestValuesLeftOutOnPurpose:
    """表へ入れなかった値。**入れても1件も落ちない**ため、検査で固定する。"""

    @staticmethod
    def _values_for(tag_key: str) -> set[str]:
        return {value for key, value, _, _ in TAG_KIND_RULES if key == tag_key}

    def test_barriers_that_do_not_stop_a_bicycle_stay_out(self):
        """`kerb`は該当件数が多く、足すと停止密度だけが実データで跳ね上がる。"""
        barriers = self._values_for("barrier")

        for value in ("kerb", "toll_booth", "entrance", "fence", "wall", "guard_rail", "jersey_barrier"):
            assert value not in barriers, value

    def test_calming_that_does_not_slow_a_bicycle_stays_out(self):
        calming = self._values_for("traffic_calming")

        for value in ("island", "no"):
            assert value not in calming, value
