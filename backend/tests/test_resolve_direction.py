"""`domain/traffic.py: direction_sql`——OSMタグから通行方向をDB側で決める。

規則表（`DIRECTION_RULES`）そのものは書き写さず、**引き当ての順序と、どこへ落ちるか**を見る。
道の分類そのものは`test_traffic.py`が持つ。

結果は`way_materials.direction`（`batch/derive_way_materials.py`）に入り、探索が逆向きの枝を
作ってよいかを決める。**判定はDB側で行うため、DBへ通して確かめる**——表だけを見て通る形に
すると、優先順位と値の正規化が実際にどう効くかを押さえられない。

タグの値はDBへ入った生の文字列で、表記は投稿者任せ（前後の空白・大文字）。
"""

import json

import pytest
from sqlalchemy import text

from app.domain.traffic import direction_sql

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


async def _directions(session, *tag_sets: dict[str, str]) -> list[str]:
    result = await session.execute(text(direction_sql(_source(list(tag_sets)))))
    return [row.direction for row in sorted(result.all(), key=lambda row: row.id)]


class TestWhatComesBack:
    async def test_every_row_comes_back_even_when_no_rule_matches(self, road_graph_session):
        """道は必ずどちらかに通れる。当たらない行を落とすと、その道がグラフから消える。"""
        assert await _directions(road_graph_session, {}, {"highway": "residential"}) == [
            "both",
            "both",
        ]

    async def test_a_time_dependent_value_is_treated_as_both(self, road_graph_session):
        """`oneway=alternating`（交互通行）のように時間帯で向きが変わるものは、時刻を持たない
        この列では表せない。通れる側へ倒す。
        """
        assert await _directions(road_graph_session, {"oneway": "alternating"}) == ["both"]


class TestTheOnewayTag:
    async def test_an_affirmative_oneway_means_forward_only(self, road_graph_session):
        assert await _directions(road_graph_session, {"oneway": "yes"}) == ["forward"]

    async def test_a_reversed_oneway_means_backward_only(self, road_graph_session):
        """`-1`はwayの描かれた向きと逆、という意味。両方向へ倒すと逆走する経路が出る。"""
        assert await _directions(road_graph_session, {"oneway": "-1"}) == ["backward"]

    async def test_the_value_is_read_past_its_spacing_and_case(self, road_graph_session):
        """生値をそのまま比べると、`"Yes"`と書かれた道だけが静かに両方向として扱われる。"""
        assert await _directions(road_graph_session, {"oneway": "  YES "}) == ["forward"]


class TestWhichRuleWins:
    async def test_the_bicycle_exception_overrides_the_general_oneway(self, road_graph_session):
        """`oneway:bicycle`は「自転車に限り一方通行規制の対象外」（逆走可の一方通行路）。
        `oneway`に負けると、通れる道を避けて遠回りする。
        """
        tags = {"oneway": "yes", "oneway:bicycle": "no"}

        assert await _directions(road_graph_session, tags) == ["both"]

    async def test_an_uninterpretable_exception_falls_back_to_the_general_tag(self, road_graph_session):
        """例外タグが**付いていること**ではなく、その値が解釈できたことで効く。付いていれば
        無条件に例外扱いにすると、意味不明な値1つで一方通行が消える。
        """
        tags = {"oneway": "yes", "oneway:bicycle": "alternating"}

        assert await _directions(road_graph_session, tags) == ["forward"]

    async def test_a_roundabout_is_one_way_without_saying_so(self, road_graph_session):
        """環状交差点は構造として一方向にしか通れず、OSMは個々のwayへ`oneway`を付けない慣行が
        ある。両方向として扱うと、環を逆走する経路を出しうる。
        """
        assert await _directions(road_graph_session, {"junction": "roundabout"}) == ["forward"]

    async def test_an_explicit_oneway_beats_the_implied_one(self, road_graph_session):
        """OSM側が向きを書いているなら、構造からの推定より優先する。"""
        tags = {"junction": "roundabout", "oneway": "no"}

        assert await _directions(road_graph_session, tags) == ["both"]

    async def test_a_junction_that_implies_nothing_stays_bidirectional(self, road_graph_session):
        """`junction=yes`は「交差点である」だけで、一方向を含意しない。"""
        assert await _directions(road_graph_session, {"junction": "yes"}) == ["both"]
