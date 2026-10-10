"""`domain/route.py`——区間（交差点の間）を`SEGMENT_BIN_DISTANCE_KM`ごとのビンへ束ねる`aggregate_segments_into_bins`と、
区間の値を候補全体へ畳む`merge_*`と、Edge単位の軸の生値を候補全体へ畳む`route_axis_raw_values`。

入口は`aggregate_segments_into_bins`・`merge_axis_difficulties`・`merge_axis_contributions`・`merge_difficulty`・
`merge_overall_difficulty`・`merge_material_values`・`merge_material_category_shares`・`route_axis_raw_values`。
応答の型（`RouteCandidate`等）の検証はPydanticが持つ。

密度の軸（区間が`DensityScoreInput`を持つ軸）は、本番の停止密度の軸と同じ、0から始まり上限で頭打ちになる直線で
確かめる——頭打ちの手前だけを通る値では、点数の平均と回数の平均の点数が同じになり、畳み方の違いが出ない。

ここで見ないもの:
- 区間の値をコスト配列から読んで区間を組み立てること → `test_route_generation_behavior.py`
- どの軸が密度の軸か → `test_evaluation.py`
- 候補全体へ畳んだ値を候補へ載せること → `test_route_generator.py`
"""

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain import route
from app.domain.axis_definitions import BreakpointLinearShape, MaterialTerm
from app.domain.route import DensityScoreInput, RouteSegmentDetail

WIDTH = route.SEGMENT_BIN_DISTANCE_KM
#: 本番の停止密度の軸の折れ線（1kmあたりの回数 → 点数。9.58回/kmで100点、その先は100点）。
STOP_SHAPE = BreakpointLinearShape(
    terms=[MaterialTerm(material="signals_per_km")], breakpoints=[(0.0, 0.0), (9.58, 100.0)],
)


def _segments(distances: list[float], **fields_per_segment) -> list[RouteSegmentDetail]:
    """東へ一直線に連なる区間。`fields_per_segment`は名前 → 区間ごとの値の並び。"""
    segments = []
    cumulative = 0.0
    for i, distance in enumerate(distances):
        segments.append(RouteSegmentDetail(
            start_latitude=35.0, start_longitude=139.0 + i * 0.01,
            end_latitude=35.0, end_longitude=139.0 + (i + 1) * 0.01,
            cumulative_distance_km=cumulative, distance_km=distance,
            **{name: values[i] for name, values in fields_per_segment.items()},
        ))
        cumulative += distance
    return segments


def test_no_segments_make_no_bins():
    assert route.aggregate_segments_into_bins([]) == []


def _signal_segments(distances: list[float], signals: list[float], share: float | None = None) -> list[RouteSegmentDetail]:
    """信号の数で決まる停止密度の軸（`stops`）と、どの区間も20点の軸（`other`）を持つ区間。`share`は停止密度の軸の
    重みの割合（`other`が残り）で、Noneなら合成に入らない。区間の値はエンジンと同じく区間の点数・寄与度・合成から作る。"""
    segments = []
    for distance, count in zip(distances, signals, strict=True):
        density = count / distance
        score = STOP_SHAPE.score_at(density)
        fields = {"axis_difficulties": {"stops": score, "other": 20.0}}
        if share is not None:
            fields |= {
                "axis_contributions": {"stops": score * share, "other": 20.0 * (1 - share)},
                "difficulty": score * share + 20.0 * (1 - share),
            }
        segments.append((distance, fields, DensityScoreInput(
            value=density, distance_km=distance, weight_share=share, shape=STOP_SHAPE)))
    built = _segments(
        [round(distance, route.DISTANCE_KM_DECIMALS) for distance, _, _ in segments],
        **{name: [fields.get(name) for _, fields, _ in segments] for name in segments[0][1]},
    )
    return [segment.with_density_inputs({"stops": density}) for segment, (_, _, density) in zip(built, segments)]


def test_a_bin_scores_a_density_axis_from_the_mean_count_and_rebuilds_its_contribution_and_difficulty():
    """62.5mの区間で信号1つと0が交互に並ぶ500m（8回/km）。区間の点数は100点と0点で平均は50点だが、ビンは8回/kmの点数
    （8 × 100/9.58 = 83.5点）。寄与度はその点数×重みの割合、合成の難しさは寄与度の和のまま。"""
    bins = route.aggregate_segments_into_bins(_signal_segments([0.0625] * 8, [1, 0] * 4, share=0.6))

    merged = bins[0]
    assert merged.axis_difficulties == {"stops": 83.5, "other": 20.0}
    assert merged.axis_contributions == {"stops": 50.1, "other": 8.0}
    assert merged.difficulty == pytest.approx(58.1)


def test_a_short_segment_rounded_to_zero_length_still_counts_its_signals():
    """応答の区間の距離は10m単位に丸めるので、信号の脇の4mの区間は長さ0で来る。回数は丸めない距離で平均する
    （500mで信号1つ＝2回/kmの点数 2 × 100/9.58 = 20.9点。丸めた距離で平均すると0点）。"""
    bins = route.aggregate_segments_into_bins(_signal_segments([0.004, 0.496], [1, 0]))

    assert bins[0].axis_difficulties["stops"] == 20.9


def test_a_route_scores_a_density_axis_from_the_mean_count_over_its_bins():
    """候補はビンからもう一度畳む。信号の集まった500m（16回/km、頭打ちの100点）と信号の無い500m（0点）の候補は、点数の
    平均（50点）ではなく8回/kmの点数（83.5点）。"""
    bins = route.aggregate_segments_into_bins(_signal_segments([0.0625] * 16, [1] * 8 + [0] * 8, share=0.6))

    assert route.merge_axis_difficulties(bins)["stops"] == 83.5
    assert route.merge_axis_contributions(bins)["stops"] == pytest.approx(50.1)
    overall = route.merge_overall_difficulty(bins)
    assert overall is not None
    assert overall.average == pytest.approx(58.1)


def test_a_route_scores_a_density_axis_the_same_however_its_road_is_cut():
    """信号1つのある100mの区間を、信号の所で10mと90mに切る（端の信号は両側が0.5回ずつ持つ）。ルートの値は回数だけで
    決まり、道の切り方で変わらない（探索の費用の側は`test_leg_costs.py`）。"""
    whole = route.aggregate_segments_into_bins(_signal_segments([0.1, 0.4], [1, 0], share=0.5))
    cut = route.aggregate_segments_into_bins(_signal_segments([0.01, 0.09, 0.4], [0.5, 0.5, 0], share=0.5))

    assert route.merge_axis_difficulties(cut) == route.merge_axis_difficulties(whole)
    assert route.merge_axis_contributions(cut) == route.merge_axis_contributions(whole)


def test_a_route_without_a_difficulty_has_no_overall_difficulty():
    assert route.merge_overall_difficulty(_segments([1.0])) is None


def test_the_load_of_a_route_is_its_rounded_average_over_every_segment_including_those_without_a_value():
    """欠損の区間を飛ばして積むと、データの無い区間が多いルートほど楽に見える。"""
    overall = route.merge_overall_difficulty(_segments([1.0, 1.0, 2.0], difficulty=[10.0, None, 20.0]))

    assert overall is not None
    # 平均 50/3 は 16.7 に丸め、総量はその 16.7 に全区間の 4km を掛ける（丸める前の平均なら 66.7）。
    assert (overall.average, overall.load) == (16.7, 66.8)


@pytest.mark.parametrize(
    ("distances", "bin_distances"),
    [
        # ちょうど幅に届いたところでビンを閉じる。
        ([WIDTH / 2, WIDTH / 2, 0.1], [WIDTH, 0.1]),
        ([0.3, 0.3, 0.3], [0.6, 0.3]),
    ],
)
def test_a_bin_closes_as_soon_as_it_reaches_the_width_and_the_rest_stays(distances, bin_distances):
    bins = route.aggregate_segments_into_bins(_segments(distances))

    assert [b.distance_km for b in bins] == bin_distances


@given(distances=st.lists(st.floats(min_value=0.001, max_value=1.5), min_size=1, max_size=40))
def test_bins_cover_the_route_without_gaps_or_overlaps(distances):
    segments = _segments(distances)

    bins = route.aggregate_segments_into_bins(segments)

    # 経路全体の距離が合う（ビンの距離は小数2桁へ丸める）。
    assert sum(b.distance_km for b in bins) == pytest.approx(sum(distances), abs=0.005 * len(bins))
    # 最後のビンのほかは幅に届いている。
    assert all(b.distance_km >= WIDTH for b in bins[:-1])
    # ビンは途切れずに連なり、最初と最後は経路の両端。
    assert (bins[0].start_longitude, bins[-1].end_longitude) == (segments[0].start_longitude, segments[-1].end_longitude)
    for before, after in zip(bins, bins[1:]):
        assert (before.end_latitude, before.end_longitude) == (after.start_latitude, after.start_longitude)
        assert after.cumulative_distance_km == pytest.approx(
            before.cumulative_distance_km + before.distance_km, abs=0.006)


def test_the_difficulty_of_a_bin_is_the_distance_weighted_mean_of_the_segments_with_one():
    bins = route.aggregate_segments_into_bins(_segments([0.1, 0.3, 0.2], difficulty=[10.0, 30.0, None]))

    assert bins[0].difficulty == pytest.approx((10.0 * 0.1 + 30.0 * 0.3) / 0.4)


def test_each_value_of_a_bin_is_averaged_over_the_segments_that_have_it():
    """「データ無しはキーを持たない」を引き継ぐ。値を持たない区間は分母にも入れない。"""
    bins = route.aggregate_segments_into_bins(_segments(
        [0.1, 0.3, 0.2],
        axis_difficulties=[{"axis_a": 10.0}, {"axis_a": 30.0, "axis_b": 50.0}, {}],
        axis_contributions=[{"axis_a": 4.0}, {"axis_a": 8.0}, {}],
        material_values=[{}, {}, {"material_a": 7.0}],
    ))

    merged = bins[0]
    assert merged.axis_difficulties == {"axis_a": 25.0, "axis_b": 50.0}
    assert merged.axis_contributions == {"axis_a": 7.0}
    assert merged.material_values == {"material_a": 7.0}


def test_segments_rounded_to_zero_length_do_not_weigh_in_the_mean():
    """区間の距離は小数2桁へ丸めるので、5mに満たない区間は長さ0で来る。長さ0の区間しか持たない値は平均できない。"""
    bins = route.aggregate_segments_into_bins(_segments(
        [0.0, 0.6],
        axis_difficulties=[{"axis_a": 90.0, "axis_z": 10.0}, {"axis_a": 30.0}],
    ))

    assert bins[0].axis_difficulties == {"axis_a": 30.0}


def test_difficulties_keep_one_decimal_and_physical_values_keep_four_significant_digits():
    """物理量はスケールが軸ごとに違う。小数の桁で丸めると、桁の小さい値がまるごと潰れる。"""
    segments = _segments(
        [0.1, 0.2],
        axis_difficulties=[{"axis_a": 10.0}, {"axis_a": 20.0}],
        axis_contributions=[{"axis_a": 10.0}, {"axis_a": 20.0}],
        material_values=[{"material_a": 1000.0}, {"material_a": 2000.0}],
    )

    assert route.merge_axis_difficulties(segments) == {"axis_a": 16.7}
    assert route.merge_axis_contributions(segments) == {"axis_a": 16.7}
    assert route.merge_material_values(segments) == {"material_a": 1667.0}


@given(st.lists(
    st.tuples(
        st.floats(min_value=0.0, max_value=1.5).map(lambda distance: round(distance, 2)),
        st.dictionaries(st.sampled_from(["axis_a", "axis_b"]), st.floats(min_value=-50.0, max_value=50.0)),
    ),
    min_size=1, max_size=40,
))
@example([(0.25, {"axis_a": 1.0}), (0.25, {}), (0.5, {"axis_a": 4.0})])
def test_route_raw_values_match_the_mean_over_the_bins_of_the_segments(edges):
    """区間の材料の値（同じ畳み方）を区間 → ビン → 候補と畳んだ値と、桁まで同じになる。

    例は、値を持たない区間がビンの重みにだけ効く形（ビンを経ずに区間の距離で平均すると値が変わる）。
    """
    segments = _segments([distance for distance, _ in edges], material_values=[values for _, values in edges])

    assert route.route_axis_raw_values(edges) == route.merge_material_values(route.aggregate_segments_into_bins(segments))


def test_a_value_of_zero_stays_zero():
    """有効数字で丸めるのに桁を対数で求めるので、0は別に扱う（停止の密度0の道はふつうにある）。"""
    segments = _segments([0.1, 0.2], material_values=[{"material_a": 0.0}, {"material_a": 0.0}])

    assert route.merge_material_values(segments) == {"material_a": 0.0}


def test_the_shape_of_a_bin_joins_the_segment_shapes_without_repeating_shared_points():
    bins = route.aggregate_segments_into_bins(_segments(
        [0.1, 0.1, 0.1, 0.3],
        geometry=[
            {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 0.0]]},
            None,  # 形の無い区間は飛ばす
            {"type": "LineString", "coordinates": [[1.0, 0.0], [2.0, 0.0]]},
            {"type": "LineString", "coordinates": [[3.0, 0.0], [4.0, 0.0]]},  # 前と離れた区間はそのまま続ける
        ],
    ))

    assert bins[0].geometry == {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0], [4.0, 0.0]]}


def test_a_bin_with_fewer_than_two_points_has_no_shape():
    """形が無ければ画面は始点と終点を直線で結ぶ。"""
    bins = route.aggregate_segments_into_bins(_segments(
        [0.6], geometry=[{"type": "LineString", "coordinates": [[0.0, 0.0]]}],
    ))

    assert bins[0].geometry is None


def test_a_bin_shows_the_arrival_and_the_wind_of_its_first_segment():
    """ビンの中で予報の時刻が変わっても、ビンへ入るときの値を出す。"""
    winds = [route.SegmentWind(speed_ms=float(i), direction_deg=0.0) for i in range(2)]

    bins = route.aggregate_segments_into_bins(_segments(
        [0.3, 0.3], estimated_arrival_time=["09:00", "09:01"], wind=winds,
    ))

    assert (bins[0].estimated_arrival_time, bins[0].wind) == ("09:00", winds[0])


def test_category_shares_are_the_share_of_distance_among_segments_that_have_the_material():
    shares = route.merge_material_category_shares([
        (0.2, {"surface": "gravel"}),
        (0.6, {"surface": "paved", "lit": "yes"}),
        (0.2, {"surface": "gravel"}),
        (0.5, {}),
        (0.0, {"surface": "soil"}),  # 長さの無い区間は数えない
    ])

    assert shares == {"surface": {"paved": 0.6, "gravel": 0.4}, "lit": {"yes": 1.0}}


def test_category_shares_are_listed_from_the_largest_and_ties_by_name():
    shares = route.merge_material_category_shares([
        (0.1, {"surface": "soil"}), (0.3, {"surface": "gravel"}), (0.3, {"surface": "compacted"}),
    ])

    assert list(shares["surface"]) == ["compacted", "gravel", "soil"]


@given(st.lists(
    st.tuples(st.floats(min_value=0.001, max_value=5.0), st.sampled_from(["v1", "v2", "v3"])), min_size=1, max_size=30,
))
def test_the_shares_of_a_material_add_up_to_one(rows):
    shares = route.merge_material_category_shares([(distance, {"m": value}) for distance, value in rows])

    assert sum(shares["m"].values()) == pytest.approx(1.0, abs=5e-4)
