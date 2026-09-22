"""`domain/attributes.py: elevation_values_sql`——区間の頂点列から標高と勾配を出す。

頂点列を作る側は`test_derive_topology.py`、出た値をEdgeへ配る側は
`test_graph_material_cache.py`、勾配を材料として読む側は`test_material_values.py`が持つ。

**判定はDB側で行うため、DBへ通して確かめる。**距離は`ST_Distance`のgeography計算に
依存するので、期待値は緯度1ステップの実距離をDBに聞いてから組む——自前の距離式を持つと、
SQLが使う距離とテストが使う距離が別物になる。
"""

import pytest
from sqlalchemy import text

from app.domain.attributes import MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT, elevation_values_sql

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

LON = 139.7
LAT = 35.0
STEP_DEG = 0.001

_STEP_M: list[float] = [0.0]


def _source(segments: dict[int, tuple[list[float | None], bool]], *, spread: bool = True) -> str:
    """{区間番号: (ordの順に並べた標高, 構造物か)} を頂点列の関係へ。

    頂点は緯度方向へ`STEP_DEG`ずつ等間隔に置く。`spread=False`は全頂点を同じ座標へ置く。
    """
    rows = []
    for segment_index, (elevations, on_structure) in segments.items():
        for ord_, elev in enumerate(elevations):
            elev_sql = "NULL::double precision" if elev is None else str(float(elev))
            lat = LAT + ord_ * STEP_DEG if spread else LAT
            rows.append(
                f"(1::bigint, {segment_index}, {ord_}, {LON}, {lat},"
                f" {elev_sql}, {str(on_structure).lower()})"
            )
    return (
        f"SELECT * FROM (VALUES {', '.join(rows)})"
        " AS v(osm_way_id, segment_index, ord, lon, lat, elev, on_structure)"
    )


async def _values(session, segments, *, spread: bool = True) -> dict[int, dict]:
    result = await session.execute(text(elevation_values_sql(_source(segments, spread=spread))))
    return {
        row.segment_index: {
            key: None if value is None else float(value)
            for key, value in row._mapping.items()
            if key not in ("osm_way_id", "segment_index")
        }
        for row in result.all()
    }


async def _one(session, elevations, *, on_structure: bool = False, spread: bool = True) -> dict:
    return (await _values(session, {0: (elevations, on_structure)}, spread=spread))[0]


async def _step_m(session) -> float:
    """頂点1ステップの実距離（m）。SQLと同じ`ST_Distance`に聞いて使い回す。"""
    if not _STEP_M[0]:
        query = (
            "SELECT ST_Distance("
            f"ST_MakePoint({LON}, {LAT})::geography,"
            f"ST_MakePoint({LON}, {LAT + STEP_DEG})::geography)"
        )
        _STEP_M[0] = float((await session.execute(text(query))).scalar())
    return _STEP_M[0]


class TestWhichSegmentsGetValues:
    async def test_a_segment_with_two_known_points_gets_values(self, road_graph_session):
        assert set(await _values(road_graph_session, {0: ([0.0, 10.0], False)})) == {0}

    async def test_a_segment_with_one_known_point_is_not_returned(self, road_graph_session):
        """0を埋めて返すと、標高が無い区間が「平坦」として最易の色で塗られる。"""
        assert await _values(road_graph_session, {0: ([5.0, None], False)}) == {}

    async def test_a_segment_with_no_elevation_at_all_is_not_returned(self, road_graph_session):
        assert await _values(road_graph_session, {0: ([None, None, None], False)}) == {}

    async def test_the_segments_that_can_be_valued_come_back_on_their_own(self, road_graph_session):
        """1区間の欠損で、同じ呼び出しの他の区間まで落とさない。"""
        segments = {0: ([0.0, 10.0], False), 1: ([None, 3.0], False), 2: ([2.0, 4.0], False)}

        assert set(await _values(road_graph_session, segments)) == {0, 2}


class TestGainAndLoss:
    async def test_a_climb_goes_to_gain_and_a_descent_to_loss(self, road_graph_session):
        values = await _one(road_graph_session, [0.0, 10.0, 4.0])

        assert values["elevation_gain_m"] == 10.0
        assert values["elevation_loss_m"] == 6.0

    async def test_the_ends_are_the_first_and_last_known_elevations(self, road_graph_session):
        values = await _one(road_graph_session, [3.0, 99.0, 8.0])

        assert values["start_elevation_m"] == 3.0
        assert values["end_elevation_m"] == 8.0

    async def test_a_missing_point_at_the_edge_does_not_become_the_end(self, road_graph_session):
        """欠損を端として扱うと、区間の高低差が丸ごと失われる。"""
        values = await _one(road_graph_session, [None, 10.0, 14.0, None])

        assert values["start_elevation_m"] == 10.0
        assert values["end_elevation_m"] == 14.0

    async def test_a_descent_has_a_negative_average_grade(self, road_graph_session):
        """符号を落として絶対値にすると、下り基調の区間が登りとして重み付けされる。"""
        assert (await _one(road_graph_session, [10.0, 0.0]))["average_grade"] < 0

    async def test_the_steepest_climb_and_descent_are_kept_separately(self, road_graph_session):
        values = await _one(road_graph_session, [0.0, 10.0, 9.0])

        assert values["max_grade"] > 0 > values["min_grade"]
        assert values["max_grade"] > abs(values["min_grade"])

    async def test_the_average_grade_is_the_rise_over_the_whole_length(self, road_graph_session):
        step = await _step_m(road_graph_session)
        values = await _one(road_graph_session, [0.0, 20.0, 10.0])

        assert values["average_grade"] == pytest.approx(10.0 / (step * 2) * 100, abs=0.01)

    async def test_the_elevations_and_the_grades_are_rounded_differently(self, road_graph_session):
        """勾配を標高と同じ桁で丸めると、緩い登りが0になって平坦と区別できない。"""
        values = await _one(road_graph_session, [0.06, 10.04])

        assert values["start_elevation_m"] == 0.1
        assert values["end_elevation_m"] == 10.0
        assert values["average_grade"] == round(values["average_grade"], 2)


class TestPointsWithoutElevation:
    async def test_a_pair_that_spans_a_gap_does_not_feed_the_gain(self, road_graph_session):
        """欠損を挟んだ2点を隣接扱いすると、欠損区間の起伏が均された値として積まれる。"""
        values = await _one(road_graph_session, [0.0, None, 30.0])

        assert values["elevation_gain_m"] == 0.0
        assert values["max_grade"] is None
        assert values["min_grade"] is None

    async def test_the_length_still_spans_the_gap(self, road_graph_session):
        """欠損ペアを長さからも外すと、区間が短くなったぶん平均勾配が過大になる。"""
        step = await _step_m(road_graph_session)
        values = await _one(road_graph_session, [0.0, None, 30.0])

        assert values["average_grade"] == pytest.approx(30.0 / (step * 2) * 100, abs=0.01)


class TestBridgesAndTunnels:
    async def test_a_road_on_the_ground_does_climb_its_middle(self, road_graph_session):
        """同じ点列を構造物でない道として渡すと中間の起伏を積む。下の2件はこの対比。"""
        values = await _one(road_graph_session, [50.0, 10.0, 50.0])

        assert values["elevation_gain_m"] == 40.0
        assert values["elevation_loss_m"] == 40.0

    async def test_the_terrain_under_a_bridge_is_not_climbed(self, road_graph_session):
        """谷を渡る平らな橋。中間点を使うと、谷底の起伏がそのまま獲得標高へ積まれる。"""
        values = await _one(road_graph_session, [50.0, 10.0, 5.0, 10.0, 50.0], on_structure=True)

        assert values["elevation_gain_m"] == 0.0
        assert values["elevation_loss_m"] == 0.0
        assert values["start_elevation_m"] == 50.0
        assert values["end_elevation_m"] == 50.0

    async def test_a_bridge_that_actually_climbs_keeps_that_climb(self, road_graph_session):
        values = await _one(road_graph_session, [0.0, 99.0, 12.0], on_structure=True)

        assert values["elevation_gain_m"] == 12.0
        assert values["elevation_loss_m"] == 0.0

    async def test_a_bridge_has_no_grade_of_its_own_beyond_the_average(self, road_graph_session):
        """区間内の起伏を知っているふりをすると、橋が最急勾配の上位を占める。"""
        values = await _one(road_graph_session, [0.0, 99.0, 12.0], on_structure=True)

        assert values["max_grade"] == values["average_grade"]
        assert values["min_grade"] == values["average_grade"]


class TestImplausibleGrades:
    @staticmethod
    def _rise_for(step: float, percent: float) -> float:
        return step * percent / 100

    async def test_a_grade_no_public_road_has_is_treated_as_missing(self, road_graph_session):
        """誤った値で経路から黙って外すより、値を持たせない方が安全側——0次ハードフィルタは
        値の無い区間を除外しない。
        """
        step = await _step_m(road_graph_session)
        over = self._rise_for(step, MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT + 5.0)

        assert (await _one(road_graph_session, [0.0, over]))["average_grade"] is None

    async def test_a_steep_but_plausible_grade_is_kept(self, road_graph_session):
        step = await _step_m(road_graph_session)
        under = self._rise_for(step, MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT - 5.0)

        assert (await _one(road_graph_session, [0.0, under]))["average_grade"] is not None

    async def test_only_the_average_grade_is_dropped(self, road_graph_session):
        """区間ごと落とすと、表示に使う標高そのものまで失われる。"""
        step = await _step_m(road_graph_session)
        over = self._rise_for(step, MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT + 5.0)

        values = await _one(road_graph_session, [0.0, over])

        assert values["end_elevation_m"] == round(over, 1)
        assert values["elevation_gain_m"] == round(over, 1)

    async def test_a_segment_with_no_length_has_no_average_grade(self, road_graph_session):
        """全頂点が同じ座標。距離0で割ると区間ごと例外になる。"""
        values = await _one(road_graph_session, [0.0, 5.0], spread=False)

        assert values["average_grade"] is None
        assert values["max_grade"] is None
        assert values["elevation_gain_m"] == 5.0
