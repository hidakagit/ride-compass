"""`domain/traffic.py`——OSMタグから派生する分類と、所要時間モデルのパラメータ。

引き当てそのものはDB側で行うため、**表が実際にどう当たるか**は
`test_tag_classification.py`（種別）と`test_resolve_direction.py`（通行方向）が
DBへ通して確かめる。ここで見るのは、表の組み立てと純関数。
"""


from app.domain.traffic import (
    DIRECTION_RULES,
    MAJOR_CROSSING_MIN_RANK,
    POI_COUNT_KINDS,
    TAG_KIND_RULES,
    highway_rank,
    stop_count_material_ids,
    stop_seconds,
)
from app.domain.tuning import TUNING_VALUES, stop_seconds_parameter_id


class TestStopSeconds:
    """停止要因1回あたりの時間損失。所要時間へそのまま足す量。"""

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
        """秒数は走ってみて決める値で、管理画面から変えられる。ここへ数字を書き写すと
        変えた値が反映されているかを誰も見なくなる。
        """
        kind = next(iter(POI_COUNT_KINDS))

        assert stop_seconds(kind) == TUNING_VALUES[stop_seconds_parameter_id(kind)]


class TestStopCountMaterialIds:
    """停止の待ちを所要時間へ足すのに要る材料id。"""

    def test_there_is_one_material_for_every_counted_kind(self):
        """軸が分解した材料だけを経路へ運ぶ既定に任せると、停止の軸を非公開にした瞬間に
        所要時間から停止の待ちが静かに消える。この一覧は軸の構成と無関係に要る。
        """
        assert len(stop_count_material_ids()) == len(POI_COUNT_KINDS)

    def test_the_id_is_built_from_the_kind(self):
        """材料idは種別から組み立てる。**その材料が実在するかはここでは見ない**——
        `traffic.py`は材料カタログを知らず、綴りの正しさはカタログ側の話。
        """
        assert set(stop_count_material_ids()) == {f"poi_{kind}_per_km" for kind in POI_COUNT_KINDS}


class TestHighwayRank:
    """交差点で「自分が走ってきた道より上位の道と交わるか」を判定するための階級順。
    値そのものに意味は無く、比較結果だけが使われる。"""

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
        """生活道路・サービス道路を横切るのに待ちは要らない。階級の大小だけで判定すると、
        自転車道（0）からサービス道路（1）へ出るだけで「待つ交差点」が成立する。
        """
        assert highway_rank("residential") < MAJOR_CROSSING_MIN_RANK
        assert highway_rank("service") < MAJOR_CROSSING_MIN_RANK
        assert highway_rank("tertiary") >= MAJOR_CROSSING_MIN_RANK


class TestValuesLeftOutOnPurpose:
    """表へ入れなかった値。**入れても1件も落ちない**ため、検査で固定する。"""

    @staticmethod
    def _values_for(tag_key: str) -> set[str]:
        return {value for key, value, _, _ in TAG_KIND_RULES if key == tag_key}

    def test_barriers_that_do_not_stop_a_bicycle_stay_out(self):
        """`kerb`は該当件数が多いが段差の過半がlowered/flushで停止要因として識別力が無く、
        足すと停止密度だけが実データで跳ね上がる。`toll_booth`は自動車専用道路上、
        `entrance`は塀の開口部（通れる）、`fence`/`wall`/`guard_rail`/`jersey_barrier`は
        道に沿う構造物で渡る点ではない。
        """
        barriers = self._values_for("barrier")

        for value in ("kerb", "toll_booth", "entrance", "fence", "wall", "guard_rail", "jersey_barrier"):
            assert value not in barriers, value

    def test_calming_that_does_not_slow_a_bicycle_stays_out(self):
        """`island`（中央島）・`no`は進行を妨げない。"""
        calming = self._values_for("traffic_calming")

        for value in ("island", "no"):
            assert value not in calming, value


class TestRuleTables:
    """引き当ての表そのもの。当たり方はDBへ通すテストが見る。"""

    def test_stop_factors_are_looked_up_before_supply(self):
        """1つのノードが停止要因と補給の両方のタグを持つことがある（コンビニ前の横断歩道
        等）。停止要因を先に当てないと、そのノードが停止として数えられない。
        """
        stop_kinds = {"traffic_signals", "crossing", "stop", "give_way", "level_crossing",
                      "railway_crossing", "barrier", "traffic_calming"}
        stop_priorities = [p for _, _, kind, p in TAG_KIND_RULES if kind in stop_kinds]
        supply_priorities = [p for _, _, kind, p in TAG_KIND_RULES if kind not in stop_kinds]

        assert stop_priorities and supply_priorities
        assert max(stop_priorities) < min(supply_priorities)

    def test_the_bicycle_exception_is_looked_up_before_the_general_oneway(self):
        """`oneway:bicycle`は「自転車に限り一方通行規制の対象外」を表す例外タグ。
        `oneway`を先に当てると、その例外が効かない。
        """
        bicycle = [p for key, _, _, p in DIRECTION_RULES if key == "oneway:bicycle"]
        general = [p for key, _, _, p in DIRECTION_RULES if key == "oneway"]

        assert bicycle and general
        assert max(bicycle) < min(general)

    def test_an_implicit_roundabout_is_looked_up_last(self):
        """環状交差点は`oneway`が書かれていなくても一方通行だが、明示された`oneway`が
        あればそちらが優先する。
        """
        junction = [p for key, _, _, p in DIRECTION_RULES if key == "junction"]
        general = [p for key, _, _, p in DIRECTION_RULES if key == "oneway"]

        assert junction and general
        assert min(junction) > max(general)
