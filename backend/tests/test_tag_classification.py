"""`domain/traffic.py: tag_kind_sql`——OSMの点のタグから、停止要因・補給休憩の種別を決める。

規則表（`TAG_KIND_RULES`）は書き写さず、**引き当ての順序・意図的に外した値・自販機の式**を見る。
集計キーへの畳み込みは`batch/derive_counts.py`、停止密度の材料は`test_material_values.py`が持つ。

結果は`node_materials`（`batch/derive_node_materials.py`）に入る。判定はDB側で行うため、
DBへ通して確かめる。タグの値はDBへ入った生の文字列で、表記は投稿者任せ。
"""

import json

import pytest
from sqlalchemy import text

from app.domain.traffic import tag_kind_sql

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


def _source(tag_sets: list[dict[str, str]]) -> str:
    rows = ", ".join(
        f"({i}, '{json.dumps(tags, ensure_ascii=False)}'::jsonb)" for i, tags in enumerate(tag_sets)
    )
    return f"SELECT * FROM (VALUES {rows}) AS t(id, tags)"


async def _kinds(session, *tag_sets: dict[str, str]) -> dict[int, str]:
    """当たった行だけの {行番号: kind}。返らなかった行は入らない。"""
    result = await session.execute(text(tag_kind_sql(_source(list(tag_sets)))))
    return {row.id: row.kind for row in result.all()}


async def _kind(session, tags: dict[str, str]) -> str | None:
    return (await _kinds(session, tags)).get(0)


class TestWhatComesBack:
    async def test_a_point_matching_nothing_is_not_returned(self, road_graph_session):
        """すべての点へ種別を付けると、街の全POIが停止要因か補給POIとして数えられる。"""
        assert await _kinds(road_graph_session, {"amenity": "bench"}, {}) == {}

    async def test_only_the_matching_rows_come_back(self, road_graph_session):
        kinds = await _kinds(
            road_graph_session, {"amenity": "bench"}, {"highway": "traffic_signals"}
        )

        assert kinds == {1: "traffic_signals"}

    async def test_a_point_gets_exactly_one_kind(self, road_graph_session):
        """1つの点が2度数えられると、停止密度がその分だけ増える。"""
        result = await road_graph_session.execute(
            text(tag_kind_sql(_source([{"railway": "crossing", "highway": "crossing"}])))
        )

        assert len(result.all()) == 1


class TestWhichRuleWins:
    async def test_a_railway_crossing_is_not_counted_as_a_plain_crossing(self, road_graph_session):
        """歩道・自転車道が線路を渡る点は`railway=crossing`と`highway=crossing`の両方で
        書かれる。`highway`側が勝つと、線路を渡る点が信号なし横断歩道（ほぼ停止しない）へ
        落ちて、踏切の待ちが所要時間から消える。
        """
        tags = {"railway": "crossing", "highway": "crossing"}

        assert await _kind(road_graph_session, tags) == "railway_crossing"

    async def test_a_stop_factor_beats_a_supply_point_on_the_same_node(self, road_graph_session):
        """止まる理由と買える場所が同じ点に書かれていたら、止まる側で数える。補給が勝つと、
        その信号が停止密度から消える（逆は補給の候補が1つ減るだけ）。
        """
        tags = {"highway": "traffic_signals", "shop": "convenience"}

        assert await _kind(road_graph_session, tags) == "traffic_signals"

    async def test_the_value_is_read_past_its_spacing_and_case(self, road_graph_session):
        assert await _kind(road_graph_session, {"highway": " Traffic_Signals "}) == "traffic_signals"


class TestLevelCrossings:
    async def test_a_road_crossing_the_tracks_is_a_level_crossing(self, road_graph_session):
        assert await _kind(road_graph_session, {"railway": "level_crossing"}) == "level_crossing"

    async def test_a_tramway_crossing_is_the_same_kind_of_stop(self, road_graph_session):
        """外すと、併用軌道のある街の停止が数えられない。"""
        assert await _kind(road_graph_session, {"railway": "tram_level_crossing"}) == "level_crossing"


class TestBarriersAndCalming:
    async def test_a_gate_is_a_stop(self, road_graph_session):
        assert await _kind(road_graph_session, {"barrier": "gate"}) == "barrier"

    async def test_a_kerb_is_not_a_stop(self, road_graph_session):
        """拾うと、歩道の縁石の数が停止密度になる。"""
        assert await _kind(road_graph_session, {"barrier": "kerb"}) is None

    async def test_a_structure_alongside_the_road_is_not_a_stop(self, road_graph_session):
        """柵・ガードレールは道に沿う構造物で、**渡る点ではない**。"""
        assert await _kind(road_graph_session, {"barrier": "fence"}) is None

    async def test_a_hump_is_a_slowdown_of_its_own_kind(self, road_graph_session):
        assert await _kind(road_graph_session, {"traffic_calming": "hump"}) == "traffic_calming"

    async def test_a_central_island_does_not_slow_anyone(self, road_graph_session):
        assert await _kind(road_graph_session, {"traffic_calming": "island"}) is None


class TestSupplyPoints:
    async def test_a_convenience_store_is_a_supply_point(self, road_graph_session):
        assert await _kind(road_graph_session, {"shop": "convenience"}) == "convenience"

    async def test_a_toilet_is_a_rest_point(self, road_graph_session):
        assert await _kind(road_graph_session, {"amenity": "toilets"}) == "toilets"

    async def test_a_shop_with_a_similar_range_is_still_not_one(self, road_graph_session):
        """補給に数えるのは`shop=convenience`だけ。品揃えの近い`supermarket`まで広げると、
        営業時間の限られた店が「いつでも寄れる」前提の補給地点として案内される。
        """
        assert await _kind(road_graph_session, {"shop": "supermarket"}) is None


class TestVendingMachines:
    async def test_a_machine_selling_drinks_is_a_supply_point(self, road_graph_session):
        tags = {"amenity": "vending_machine", "vending": "drinks"}

        assert await _kind(road_graph_session, tags) == "vending_drinks"

    async def test_one_edible_value_among_several_is_enough(self, road_graph_session):
        tags = {"amenity": "vending_machine", "vending": "cigarettes;drinks"}

        assert await _kind(road_graph_session, tags) == "vending_drinks"

    async def test_a_machine_with_nothing_written_is_unknown_not_dropped(self, road_graph_session):
        """`vending`が無い自販機は日本のOSMで多数を占める。落とすと補給地点の候補が
        大きく減るため、「中身が分からない機械」として別kindで残す。
        """
        assert await _kind(road_graph_session, {"amenity": "vending_machine"}) == "vending_unknown"

    async def test_a_value_that_is_only_separators_is_also_unknown(self, road_graph_session):
        tags = {"amenity": "vending_machine", "vending": ";;"}

        assert await _kind(road_graph_session, tags) == "vending_unknown"

    async def test_a_machine_selling_nothing_edible_is_dropped(self, road_graph_session):
        """中身が分かっていて飲食物でないなら、補給の候補にしてはいけない——「分からない」
        側へ倒すと、たばこ・切符の機械が補給地点として案内される。
        """
        tags = {"amenity": "vending_machine", "vending": "cigarettes"}

        assert await _kind(road_graph_session, tags) is None

    async def test_the_values_are_read_past_their_spacing_and_case(self, road_graph_session):
        tags = {"amenity": "vending_machine", "vending": " Drinks ; "}

        assert await _kind(road_graph_session, tags) == "vending_drinks"
