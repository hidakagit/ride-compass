"""`domain/material_sql.py`——材料の値をDBから求める式。

どの材料がどの式を使うかは宣言（`MaterialSpec.value_sql`）が持ち、そこから下流を導く部分は
`test_material_catalog.py`が持つ。欠損率の測り方は`test_material_coverage.py`、区間の標高と
勾配は`test_elevation_values.py`。

**実在の材料id・タグ名・列名を並べない。** 式の振る舞いはidごとに違わないため、性質ごとに
架空の名前で1件通せば足りる。宣言を1件ずつ当てる形は、宣言から作った足場へ同じ宣言を
当てているだけになる（列を自分で用意して「その列が読める」ことを確かめる形）。
**宣言した列が実在するかは別の問い**で、末尾で実テーブルへ式を通して確かめる。

**判定はDB側で行うため、DBへ通して確かめる。**式はテーブルの別名を固定で参照し、FROM句は
読み出し側が組み立てる。各検査ではその別名を副問い合わせで与える。
"""

import json

import pytest
from sqlalchemy import ARRAY, Text, bindparam, text

from app.domain.material_catalog import material_value_sql
from app.domain.material_sql import (
    SURFACE_GOOD_CASE_SQL,
    cycleway_has_value_sql,
    landcover_value_sql,
    normalized_tag_sql,
    poi_density_value_sql,
    positive_integer_tag_sql,
    tag_absent_is_false_sql,
    tag_is_value_sql,
    ways_lookup_sql,
    ways_source_sql,
)

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

TAG_A = "tag_a"
KIND_A = "kind_a"
LC_A = "class_a"


def _way_alias(tags: dict[str, str], *, surface: str | None = None) -> str:
    """`w`の別名を副問い合わせで与える（`ways_source_sql`が出す列と同じ形）。"""
    literal = json.dumps(tags, ensure_ascii=False).replace("'", "''")
    surface_sql = "NULL::text" if surface is None else "'" + surface.replace("'", "''") + "'"
    return (
        "SELECT 1::bigint AS osm_way_id,"
        f" '{literal}'::jsonb AS tags,"
        f" ('{literal}'::jsonb)->>'highway' AS highway,"
        f" {surface_sql} AS surface"
    )


async def _way_value(session, expr: str, tags: dict[str, str], *, surface=None, **params):
    query = text(f"SELECT {expr} AS v FROM ({_way_alias(tags, surface=surface)}) w")
    if params:
        query = query.bindparams(**params)
    return (await session.execute(query)).scalar()


GOOD_A = "good_a"
BAD_A = "bad_a"


async def _surface_good(session, surface: str | None):
    """良し悪しの語彙は架空の2値で与える。実在の語彙が正しいかは`road.py`側の話。"""
    return await _way_value(
        session,
        SURFACE_GOOD_CASE_SQL,
        {},
        surface=surface,
        good_tags=[GOOD_A],
        bad_tags=[BAD_A],
    )


async def _edge_value(session, expr: str, *, columns: str):
    """`em`・`re`の別名を副問い合わせで与える。"""
    query = f"SELECT {expr} AS v FROM (SELECT {columns}) em, (SELECT {columns}) re"
    return (await session.execute(text(query))).scalar()


class TestReadingATag:
    @pytest.mark.parametrize("written", ["Value", " value ", "VALUE"])
    async def test_the_case_and_spacing_a_contributor_used_do_not_matter(
        self, road_graph_session, written
    ):
        """生値をそのまま比べると、大文字で書かれた道だけが不明として扱われる。"""
        value = await _way_value(road_graph_session, normalized_tag_sql(TAG_A), {TAG_A: written})

        assert value == "value"

    async def test_a_tag_nobody_wrote_reads_as_nothing(self, road_graph_session):
        assert await _way_value(road_graph_session, normalized_tag_sql(TAG_A), {}) is None


class TestTagAbsentMeansNo:
    async def test_a_matching_tag_is_true(self, road_graph_session):
        expr = tag_is_value_sql(TAG_A, "x")

        assert await _way_value(road_graph_session, expr, {TAG_A: "X"}) is True

    async def test_a_different_value_is_false(self, road_graph_session):
        expr = tag_is_value_sql(TAG_A, "x")

        assert await _way_value(road_graph_session, expr, {TAG_A: "y"}) is False

    async def test_no_tag_at_all_is_false_rather_than_unknown(self, road_graph_session):
        """不明へ倒すと、そのタグを書いていない道を使う軸がすべて評価不能になる。"""
        expr = tag_is_value_sql(TAG_A, "x")

        assert await _way_value(road_graph_session, expr, {}) is False

    async def test_the_wrapper_turns_any_null_condition_into_false(self, road_graph_session):
        expr = tag_absent_is_false_sql(f"{normalized_tag_sql(TAG_A)} = 'x'")

        assert await _way_value(road_graph_session, expr, {}) is False


class TestNumericTags:
    @pytest.mark.parametrize(("written", "expected"), [("50", 50), (" 60 ", 60), ("49.9", 49)])
    async def test_a_number_a_contributor_wrote_is_read_as_an_integer(
        self, road_graph_session, written, expected
    ):
        """切り上げると、`"49.5"`が上の区分へ入る。"""
        expr = positive_integer_tag_sql(TAG_A)

        assert await _way_value(road_graph_session, expr, {TAG_A: written}) == expected

    @pytest.mark.parametrize("written", ["0", "-10", "walk", "50 mph", "", "none"])
    async def test_a_value_that_is_not_a_positive_number_has_no_value(
        self, road_graph_session, written
    ):
        """`"walk"`・`"none"`は実データに現れる。0へ倒すと制限速度0km/hの道ができ、
        速度の軸がその道を最良と判断する。
        """
        expr = positive_integer_tag_sql(TAG_A)

        assert await _way_value(road_graph_session, expr, {TAG_A: written}) is None


class TestSurfaceQuality:
    async def test_a_surface_in_the_good_list_is_good(self, road_graph_session):
        assert await _surface_good(road_graph_session, GOOD_A) is True

    async def test_a_surface_in_the_bad_list_is_bad(self, road_graph_session):
        assert await _surface_good(road_graph_session, BAD_A) is False

    async def test_a_surface_in_neither_list_stays_unknown(self, road_graph_session):
        """どちらにも属さないタグを悪い側へ倒すと、未分類の路面が一律に遅く見積もられる。"""
        assert await _surface_good(road_graph_session, "no_such_surface") is None

    async def test_no_surface_tag_stays_unknown(self, road_graph_session):
        """「タグが無い＝舗装されていない」ではない。ここだけは非該当へ畳まない。"""
        assert await _surface_good(road_graph_session, None) is None

    async def test_the_case_a_contributor_used_does_not_matter(self, road_graph_session):
        assert await _surface_good(road_graph_session, f" {GOOD_A.upper()} ") is True


class TestCyclewayTags:
    async def test_a_tag_other_than_the_base_one_counts(self, road_graph_session):
        """自転車インフラは左右・両側にも書かれる。`cycleway`本体だけを見ると、片側だけに
        車線がある道を「無し」として扱う。
        """
        expr = cycleway_has_value_sql("x")

        assert await _way_value(road_graph_session, expr, {"cycleway:left": "x"}) is True

    async def test_a_value_that_is_not_asked_for_does_not_count(self, road_graph_session):
        expr = cycleway_has_value_sql("x")

        assert await _way_value(road_graph_session, expr, {"cycleway": "y"}) is False

    async def test_several_wanted_values_are_all_accepted(self, road_graph_session):
        expr = cycleway_has_value_sql("x", "y")

        assert await _way_value(road_graph_session, expr, {"cycleway": "y"}) is True

    async def test_none_of_the_tags_is_false(self, road_graph_session):
        expr = cycleway_has_value_sql("x")

        assert await _way_value(road_graph_session, expr, {TAG_A: "x"}) is False

    async def test_the_value_is_read_past_its_case(self, road_graph_session):
        expr = cycleway_has_value_sql("x")

        assert await _way_value(road_graph_session, expr, {"cycleway": " X "}) is True


class TestStopDensity:
    @staticmethod
    def _columns(count: str, distance: str) -> str:
        return f"{count} AS poi_{KIND_A}, {distance} AS distance_m"

    async def test_the_count_is_divided_by_the_distance_in_kilometres(self, road_graph_session):
        value = await _edge_value(
            road_graph_session,
            poi_density_value_sql(KIND_A),
            columns=self._columns("4::integer", "500.0"),
        )

        assert value == pytest.approx(8.0)

    async def test_a_count_of_zero_is_a_density_of_zero(self, road_graph_session):
        """未計算と取り違えると、数え終わった区間が評価対象から外れる。"""
        value = await _edge_value(
            road_graph_session,
            poi_density_value_sql(KIND_A),
            columns=self._columns("0::integer", "500.0"),
        )

        assert value == 0.0

    async def test_a_count_that_has_not_been_computed_has_no_density(self, road_graph_session):
        """0として配ると、まだ数えていない区間が「停止要因なし」の最良として塗られる。"""
        value = await _edge_value(
            road_graph_session,
            poi_density_value_sql(KIND_A),
            columns=self._columns("NULL::integer", "500.0"),
        )

        assert value is None

    async def test_a_segment_with_no_length_has_no_density(self, road_graph_session):
        """0で割ると区間ごと例外になる。"""
        value = await _edge_value(
            road_graph_session,
            poi_density_value_sql(KIND_A),
            columns=self._columns("4::integer", "0.0"),
        )

        assert value is None


class TestLandcover:
    async def test_the_share_is_read_from_the_segment_column(self, road_graph_session):
        """道1本の値へ落とさない——区間の値は全区間ぶん計算されており、落とす先は
        「同じ道の平均」でしかない。
        """
        value = await _edge_value(
            road_graph_session, landcover_value_sql(LC_A), columns=f"12.5 AS lc_{LC_A}"
        )

        assert value == pytest.approx(12.5)


class TestAgainstTheRealTables:
    """上の各検査は別名を副問い合わせで与えるため、**綴りの合わない列を見つけられない**。
    宣言されている式を実テーブルへ通して、その1点だけを確かめる。行は0件でよい——
    列の参照はPostgreSQLが構文解析の時点で検証する。
    """

    async def test_every_declared_expression_resolves_against_the_schema(self, road_graph_session):
        """式が参照する列が実在しないと、その材料を含む読み出しが区間ぶん丸ごと落ちる。
        材料idも期待値も名指ししない——値の正しさは上の各検査が持つ。
        """
        expressions = material_value_sql()
        assert expressions, "宣言された式が1つも無ければ、このクエリは何も確かめていない"

        query = text(
            "SELECT " + ", ".join(f"({expr})" for expr in sorted(expressions.values()))
            + f" FROM {ways_source_sql()} w, road_edges re, edge_materials em"
        ).bindparams(
            bindparam("good_tags", value=[GOOD_A], type_=ARRAY(Text())),
            bindparam("bad_tags", value=[BAD_A], type_=ARRAY(Text())),
            bindparam("accident_years", value=1),
        )

        assert (await road_graph_session.execute(query)).all() == []

    async def test_the_single_way_lookup_resolves_too(self, road_graph_session):
        """区間ごとに1本だけ引く経路。別名の中身が違うと、こちらだけが落ちる。"""
        query = f"SELECT count(*) FROM {ways_lookup_sql('42')} w"

        assert (await road_graph_session.execute(text(query))).scalar() == 0

    async def test_the_sampling_clause_is_accepted(self, road_graph_session):
        """抽選を外へ付ける形にすると、欠損率を測るバッチが構文エラーで止まる。"""
        query = f"SELECT count(*) FROM {ways_source_sql('TABLESAMPLE SYSTEM (100)')} w"

        assert (await road_graph_session.execute(text(query))).scalar() is not None
