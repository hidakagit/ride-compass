"""`domain/route.py`——ルートの器と、区間をビンへ畳む集約。

距離加重平均そのものは`test_difficulty.py`が持つ。ここで見るのは**何をどう畳むか**。
"""

import math

import pytest

from app.domain.route import (
    BIN_DROPPED_DICT_FIELDS,
    Coordinates,
    RouteSegmentDetail,
    aggregate_segments_into_bins,
    merge_axis_contributions,
    merge_axis_difficulties,
    merge_axis_raw_values,
    merge_material_category_shares,
    merge_material_values,
)


def _segment(distance_km: float = 1.0, cumulative: float = 0.0, **fields) -> RouteSegmentDetail:
    return RouteSegmentDetail(
        start_latitude=35.0,
        start_longitude=139.0,
        end_latitude=35.01,
        end_longitude=139.0,
        cumulative_distance_km=cumulative,
        distance_km=distance_km,
        **fields,
    )


def _line(*points: tuple[float, float]) -> dict:
    return {"type": "LineString", "coordinates": [list(p) for p in points]}


class TestCoordinates:
    def test_a_position_on_earth_is_accepted(self):
        assert Coordinates(latitude=35.0, longitude=139.0).latitude == 35.0

    @pytest.mark.parametrize(
        ("latitude", "longitude"), [(91.0, 139.0), (-91.0, 139.0), (35.0, 181.0), (35.0, -181.0)]
    )
    def test_a_position_off_the_globe_is_rejected(self, latitude, longitude):
        """範囲外をそのまま通すと、投影の式が定義域外で落ちるか、地球の裏側を指す。"""
        with pytest.raises(ValueError):
            Coordinates(latitude=latitude, longitude=longitude)


class TestAggregateSegmentsIntoBins:
    """Edge単位の区間を、一定距離ごとのビンへ畳む。"""

    def test_no_segments_give_no_bins(self):
        assert aggregate_segments_into_bins([]) == []

    def test_segments_are_grouped_until_the_bin_is_full(self):
        segments = [_segment(0.2, cumulative=i * 0.2) for i in range(5)]

        bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

        assert [b.distance_km for b in bins] == [0.6, 0.4]

    def test_the_last_bin_is_kept_even_if_it_is_short(self):
        """切り捨てると経路全体の距離が合わなくなる。"""
        segments = [_segment(0.4), _segment(0.1)]

        bins = aggregate_segments_into_bins(segments, bin_distance_km=0.4)

        assert len(bins) == 2
        assert bins[1].distance_km == 0.1

    def test_a_run_that_divides_evenly_leaves_no_trailing_bin(self):
        """ちょうど割り切れると最後の入れ物は空になる。空のまま足すと、区間を持たない
        ビンが1つ増える。
        """
        segments = [_segment(0.5), _segment(0.5)]

        bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

        assert [b.distance_km for b in bins] == [0.5, 0.5]

    def test_the_total_distance_survives_the_binning(self):
        """畳んだあとの合計が元と違うと、経路全体の距離が表示と食い違う。"""
        segments = [_segment(0.17), _segment(0.23), _segment(0.31), _segment(0.29)]

        bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

        assert round(sum(b.distance_km for b in bins), 2) == 1.0

    def test_a_segment_longer_than_a_bin_stands_alone(self):
        """長い1本を分割はしない（形状も値も切れない）。次の区間と混ぜてしまうと、
        そのビンだけ極端に長くなる。
        """
        bins = aggregate_segments_into_bins([_segment(2.0), _segment(0.1)], bin_distance_km=0.5)

        assert [b.distance_km for b in bins] == [2.0, 0.1]

    def test_the_bin_spans_from_the_first_start_to_the_last_end(self):
        first = _segment(0.3, cumulative=1.0)
        last = _segment(0.3, cumulative=1.3)
        last = last.model_copy(update={"end_latitude": 36.0, "end_longitude": 140.0})

        merged = aggregate_segments_into_bins([first, last], bin_distance_km=10.0)[0]

        assert (merged.start_latitude, merged.start_longitude) == (first.start_latitude, first.start_longitude)
        assert (merged.end_latitude, merged.end_longitude) == (36.0, 140.0)
        assert merged.cumulative_distance_km == 1.0

    def test_the_arrival_time_of_the_bin_is_the_one_it_starts_with(self):
        segments = [_segment(0.3, estimated_arrival_time="10:00"), _segment(0.3, estimated_arrival_time="10:05")]

        merged = aggregate_segments_into_bins(segments, bin_distance_km=10.0)[0]

        assert merged.estimated_arrival_time == "10:00"

    def test_the_geometry_is_joined_without_repeating_the_shared_point(self):
        """境界の点を残すと、線が同じ座標を2回通る形になる。"""
        a = _segment(0.3, geometry=_line((139.0, 35.0), (139.0, 35.1)))
        b = _segment(0.3, geometry=_line((139.0, 35.1), (139.0, 35.2)))

        merged = aggregate_segments_into_bins([a, b], bin_distance_km=10.0)[0]

        assert merged.geometry["coordinates"] == [[139.0, 35.0], [139.0, 35.1], [139.0, 35.2]]

    def test_segments_without_a_geometry_are_skipped(self):
        """形状を持たない区間があってもビン全体の線を捨てない。"""
        a = _segment(0.3, geometry=_line((139.0, 35.0), (139.0, 35.1)))
        b = _segment(0.3)

        merged = aggregate_segments_into_bins([a, b], bin_distance_km=10.0)[0]

        assert merged.geometry["coordinates"] == [[139.0, 35.0], [139.0, 35.1]]

    def test_a_bin_that_cannot_form_a_line_has_no_geometry(self):
        """点が1つでは線にならない。空のLineStringを返すと描画側が落ちる。"""
        merged = aggregate_segments_into_bins([_segment(0.3)], bin_distance_km=10.0)[0]

        assert merged.geometry is None

    def test_the_difficulty_of_the_bin_is_weighted_by_distance(self):
        segments = [_segment(0.9, difficulty=0.0), _segment(0.1, difficulty=100.0)]

        merged = aggregate_segments_into_bins(segments, bin_distance_km=10.0)[0]

        assert merged.difficulty == 10.0

    def test_segments_without_a_difficulty_are_left_out_of_the_average(self):
        segments = [_segment(1.0, difficulty=40.0), _segment(9.0)]

        merged = aggregate_segments_into_bins(segments, bin_distance_km=100.0)[0]

        assert merged.difficulty == 40.0

    def test_a_bin_where_nothing_could_be_evaluated_has_no_difficulty(self):
        """0で埋めると、評価できなかった区間が最良の色で塗られる。"""
        merged = aggregate_segments_into_bins([_segment(1.0), _segment(1.0)], bin_distance_km=100.0)[0]

        assert merged.difficulty is None

    def test_the_fields_not_carried_into_a_bin_are_declared(self):
        """引き継ぎの足し忘れは型でも例外でも現れない。モデル側の辞書フィールドを引き、
        ビンへ入るか宣言に載っているかのどちらかであることを確かめる。
        """
        dict_fields = {
            name for name, field in RouteSegmentDetail.model_fields.items()
            if getattr(field.annotation, "__origin__", None) is dict
        }
        merged = aggregate_segments_into_bins([_segment(0.3)], bin_distance_km=10.0)[0]
        carried = {name for name in dict_fields if getattr(merged, name) != {} or name not in BIN_DROPPED_DICT_FIELDS}

        assert dict_fields
        assert dict_fields == carried | set(BIN_DROPPED_DICT_FIELDS)

    def test_a_dropped_field_carries_its_reason(self):
        for name, reason in BIN_DROPPED_DICT_FIELDS.items():
            assert name in RouteSegmentDetail.model_fields, name
            assert reason.strip(), name


class TestMergingAxisDictionaries:
    """キーごとの距離加重平均。**どの区間にも無いキーは結果に含めない。**"""

    def test_a_key_present_everywhere_is_averaged_by_distance(self):
        segments = [
            _segment(0.9, axis_difficulties={"a": 0.0}),
            _segment(0.1, axis_difficulties={"a": 100.0}),
        ]

        assert merge_axis_difficulties(segments) == {"a": 10.0}

    def test_a_key_missing_from_some_segments_uses_the_rest(self):
        segments = [_segment(1.0, axis_difficulties={"a": 40.0}), _segment(9.0, axis_difficulties={})]

        assert merge_axis_difficulties(segments) == {"a": 40.0}

    def test_a_key_no_segment_has_does_not_appear(self):
        """0で埋めると、評価できなかった軸が「最良」として内訳に並ぶ。"""
        assert merge_axis_difficulties([_segment(1.0)]) == {}

    def test_a_key_only_on_zero_length_segments_does_not_appear(self):
        """長さの無い区間しか値を持たないと、加重平均の分母が0になる。キーを残すと、
        割れなかった軸が0点として内訳に並ぶ。
        """
        segments = [_segment(0.0, axis_difficulties={"a": 50.0}), _segment(1.0)]

        assert merge_axis_difficulties(segments) == {}

    def test_difficulties_are_rounded_to_one_decimal(self):
        segments = [_segment(1.0, axis_difficulties={"a": 0.0}), _segment(2.0, axis_difficulties={"a": 100.0})]

        assert merge_axis_difficulties(segments) == {"a": 66.7}

    def test_contributions_use_the_same_rounding_as_difficulties(self):
        segments = [_segment(1.0, axis_contributions={"a": 0.0}), _segment(2.0, axis_contributions={"a": 100.0})]

        assert merge_axis_contributions(segments) == {"a": 66.7}

    def test_raw_values_keep_their_significant_digits(self):
        """物理量はスケールが軸ごとに違う。固定の小数桁で丸めると、桁の小さい軸
        （事故密度は0〜0.5程度）で値がまるごと潰れる。
        """
        segments = [_segment(1.0, axis_raw_values={"a": 0.000123456})]

        assert merge_axis_raw_values(segments) == {"a": 0.0001235}

    def test_material_values_keep_their_significant_digits(self):
        segments = [_segment(1.0, material_values={"m": 0.000123456})]

        assert merge_material_values(segments) == {"m": 0.0001235}

    def test_a_value_of_zero_survives_the_rounding(self):
        """有効数字の丸めは0の対数を取れない。例外にせずそのまま返す。"""
        assert merge_material_values([_segment(1.0, material_values={"m": 0.0})]) == {"m": 0.0}

    def test_a_non_finite_value_is_passed_through(self):
        segments = [_segment(1.0, material_values={"m": math.inf})]

        assert merge_material_values(segments) == {"m": math.inf}


class TestMergeMaterialCategoryShares:
    """文字列の材料は平均できないため、値ごとの延長割合へ畳む。"""

    def test_each_value_gets_its_share_of_the_distance(self):
        segments = [
            _segment(3.0, material_categories={"m": "a"}),
            _segment(1.0, material_categories={"m": "b"}),
        ]

        assert merge_material_category_shares(segments) == {"m": {"a": 0.75, "b": 0.25}}

    def test_segments_without_a_value_are_not_in_the_denominator(self):
        """観測できた範囲でどの値が多いかを表す。分母へ入れると、タグの無い道が多い
        ほど全ての割合が小さく出る。
        """
        segments = [_segment(1.0, material_categories={"m": "a"}), _segment(9.0)]

        assert merge_material_category_shares(segments) == {"m": {"a": 1.0}}

    def test_a_segment_with_no_length_is_skipped(self):
        segments = [_segment(0.0, material_categories={"m": "a"}), _segment(1.0, material_categories={"m": "b"})]

        assert merge_material_category_shares(segments) == {"m": {"b": 1.0}}

    def test_no_values_at_all_give_no_entry(self):
        assert merge_material_category_shares([_segment(1.0)]) == {}

    def test_the_values_are_ordered_by_share_then_by_name(self):
        """フロントは並べ替えを持たない。同率のときの並びも決めておかないと、実行ごとに
        凡例の順序が変わる。
        """
        segments = [
            _segment(1.0, material_categories={"m": "b"}),
            _segment(1.0, material_categories={"m": "a"}),
            _segment(3.0, material_categories={"m": "c"}),
        ]

        assert list(merge_material_category_shares(segments)["m"]) == ["c", "a", "b"]

    def test_each_material_is_counted_separately(self):
        segments = [
            _segment(1.0, material_categories={"m": "a", "n": "x"}),
            _segment(1.0, material_categories={"m": "b"}),
        ]

        shares = merge_material_category_shares(segments)

        assert shares["m"] == {"a": 0.5, "b": 0.5}
        assert shares["n"] == {"x": 1.0}
