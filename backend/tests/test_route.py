"""`domain/route.py`——区間を約500m単位のビンへ畳む集約と、候補全体への集約関数。

ここで見ないもの:
- 区間から候補単位へ集約する配線（どのフィールドをどの関数で作るか） → `test_route_generator.py`
- 距離加重平均そのもの（欠損の除外・再正規化の計算） → `domain/difficulty.py`のテスト
- モデルのフィールド制約（緯度経度の範囲・未知フィールドの拒否） → 型が保証する

ビンの幅は既定値に頼らず、テストごとに渡す。
"""

import pytest

from app.domain import route
from app.domain.route import RouteSegmentDetail


def _segment(distance_km: float, difficulty: float | None = None, **fields) -> RouteSegmentDetail:
    return RouteSegmentDetail(
        start_latitude=0.0,
        start_longitude=0.0,
        end_latitude=0.0,
        end_longitude=0.0,
        cumulative_distance_km=0.0,
        distance_km=distance_km,
        difficulty=difficulty,
        **fields,
    )


def _line(*points: tuple[float, float]) -> dict:
    return {"type": "LineString", "coordinates": [list(p) for p in points]}


# ---- ビンの切り方 ----


def test_no_segments_make_no_bins():
    assert route.aggregate_segments_into_bins([], bin_distance_km=0.5) == []


@pytest.mark.parametrize(
    ("distances", "expected_bin_distances"),
    [
        # 累積がちょうど幅に届いた時点で閉じ、残りは幅に満たなくても最後のビンとして残す
        ([0.2, 0.3, 0.2], [0.5, 0.2]),
        # 最後の区間でちょうど閉じたときは、空のビンを足さない
        ([0.5, 0.5], [0.5, 0.5]),
        # 幅に届かないまま終わった区間も1つのビンになる（経路全体の距離が合うため）
        ([0.1, 0.1], [0.2]),
    ],
)
def test_bins_close_when_accumulated_distance_reaches_bin_width(distances, expected_bin_distances):
    bins = route.aggregate_segments_into_bins([_segment(d) for d in distances], bin_distance_km=0.5)

    assert [b.distance_km for b in bins] == expected_bin_distances


def test_bin_takes_its_start_from_first_segment_and_end_from_last():
    first = _segment(0.123).model_copy(
        update={
            "start_latitude": 35.1,
            "start_longitude": 139.1,
            "cumulative_distance_km": 4.0,
            "estimated_arrival_time": "09:00",
            "end_latitude": 35.2,
            "end_longitude": 139.2,
        }
    )
    last = _segment(0.456).model_copy(
        update={
            "start_latitude": 35.2,
            "start_longitude": 139.2,
            "cumulative_distance_km": 4.123,
            "estimated_arrival_time": "09:01",
            "end_latitude": 35.3,
            "end_longitude": 139.3,
        }
    )

    (merged,) = route.aggregate_segments_into_bins([first, last], bin_distance_km=10.0)

    assert (merged.start_latitude, merged.start_longitude) == (35.1, 139.1)
    assert (merged.end_latitude, merged.end_longitude) == (35.3, 139.3)
    assert merged.cumulative_distance_km == 4.0
    assert merged.estimated_arrival_time == "09:00"
    assert merged.distance_km == 0.58  # 0.579を小数2桁へ


# ---- ビンの値 ----


def test_bin_difficulty_is_distance_weighted_over_segments_with_a_value():
    segments = [_segment(1.0, 10.0), _segment(1.0, None), _segment(2.0, 40.0)]

    (merged,) = route.aggregate_segments_into_bins(segments, bin_distance_km=10.0)

    assert merged.difficulty == 30.0  # (10×1 + 40×2) / 3。値の無い区間は分母にも入れない


def test_bin_difficulty_is_missing_when_no_segment_has_one():
    (merged,) = route.aggregate_segments_into_bins([_segment(1.0, None), _segment(1.0, None)], bin_distance_km=10.0)

    assert merged.difficulty is None


@pytest.mark.parametrize("field", sorted(route.BIN_DICT_FIELD_MERGERS))
def test_every_declared_dict_field_is_carried_into_bins_per_key(field):
    # 母集団は宣言から取る: ビンへ引き継ぐと宣言したフィールドはすべて、キーごとの距離加重平均で残る
    segments = [
        _segment(1.0, **{field: {"a": 10.0}}),
        _segment(2.0, **{field: {"a": 40.0, "b": 7.0}}),
    ]

    (merged,) = route.aggregate_segments_into_bins(segments, bin_distance_km=10.0)

    # "b"は2つ目の区間にしか無い——キーを持たない区間は、そのキーの分母に入れない
    assert getattr(merged, field) == {"a": 30.0, "b": 7.0}


def test_bin_geometry_joins_segments_without_repeating_the_shared_point():
    segments = [
        _segment(0.1, geometry=_line((0, 0), (1, 1))),
        _segment(0.1, geometry=_line((1, 1), (2, 2))),
    ]

    (merged,) = route.aggregate_segments_into_bins(segments, bin_distance_km=10.0)

    assert merged.geometry == _line((0, 0), (1, 1), (2, 2))


def test_bin_geometry_keeps_both_points_where_segments_do_not_touch():
    segments = [
        _segment(0.1, geometry=_line((0, 0), (1, 1))),
        _segment(0.1, geometry=_line((5, 5), (6, 6))),
    ]

    (merged,) = route.aggregate_segments_into_bins(segments, bin_distance_km=10.0)

    assert merged.geometry == _line((0, 0), (1, 1), (5, 5), (6, 6))


def test_bin_geometry_skips_segments_without_a_shape():
    segments = [_segment(0.1), _segment(0.1, geometry=_line((1, 1), (2, 2)))]

    (merged,) = route.aggregate_segments_into_bins(segments, bin_distance_km=10.0)

    assert merged.geometry == _line((1, 1), (2, 2))


@pytest.mark.parametrize(
    "geometries",
    [
        [None, None],
        # 形を持つ区間が1点しか無ければ線にならない
        [None, _line((1, 1))],
    ],
)
def test_bin_has_no_geometry_when_fewer_than_two_points_remain(geometries):
    segments = [_segment(0.1, geometry=g) for g in geometries]

    (merged,) = route.aggregate_segments_into_bins(segments, bin_distance_km=10.0)

    assert merged.geometry is None


# ---- 候補全体への集約関数（丸め方） ----


@pytest.mark.parametrize(
    ("merge", "field", "expected"),
    [
        # 0〜100の得点は小数1桁
        (route.merge_axis_difficulties, "axis_difficulties", 0.0),
        (route.merge_axis_contributions, "axis_contributions", 0.0),
        # 単位が軸ごとに違う物理量は、桁の小さい軸で値が潰れないよう有効数字4桁
        (route.merge_axis_raw_values, "axis_raw_values", 0.001235),
        (route.merge_material_values, "material_values", 0.001235),
    ],
)
def test_merge_rounds_scores_to_one_decimal_and_physical_values_to_significant_digits(merge, field, expected):
    assert merge([_segment(1.0, **{field: {"a": 0.00123456}})]) == {"a": expected}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12345.6, 12350.0),
        (-0.00123456, -0.001235),  # 符号付きの材料（下りの勾配等）も同じ桁で残る
        (0.0, 0.0),
    ],
)
def test_significant_digit_rounding_does_not_depend_on_scale(value, expected):
    assert route.merge_material_values([_segment(1.0, material_values={"m": value})]) == {"m": expected}


def test_key_seen_only_on_zero_length_segments_is_left_out():
    assert route.merge_material_values([_segment(0.0, material_values={"m": 5.0})]) == {}


# ---- categorical材料の延長割合 ----


def test_category_shares_are_fractions_of_distance_largest_first():
    shares = route.merge_material_category_shares([(1.0, {"surface": "asphalt"}), (3.0, {"surface": "gravel"})])

    assert shares == {"surface": {"gravel": 0.75, "asphalt": 0.25}}
    assert list(shares["surface"]) == ["gravel", "asphalt"]


def test_category_shares_with_equal_distance_are_ordered_by_value_name():
    shares = route.merge_material_category_shares([(1.0, {"surface": "b"}), (1.0, {"surface": "a"})])

    assert list(shares["surface"]) == ["a", "b"]


def test_category_share_denominator_is_only_the_distance_where_that_material_has_a_value():
    shares = route.merge_material_category_shares(
        [(1.0, {"surface": "asphalt", "smoothness": "good"}), (3.0, {"surface": "gravel"})]
    )

    assert shares["smoothness"] == {"good": 1.0}


def test_category_shares_are_rounded_to_four_decimals():
    shares = route.merge_material_category_shares([(1.0, {"surface": "a"}), (2.0, {"surface": "b"})])

    assert shares == {"surface": {"b": 0.6667, "a": 0.3333}}


def test_zero_length_segments_do_not_count_toward_category_shares():
    shares = route.merge_material_category_shares(
        [(0.0, {"surface": "gravel", "tracktype": "grade1"}), (2.0, {"surface": "asphalt"})]
    )

    # 距離0の区間にしか無い材料は、結果に現れない
    assert shares == {"surface": {"asphalt": 1.0}}


# ---- 畳み方の宣言漏れの検出 ----


def test_undeclared_dict_field_is_reported_whatever_its_value_type(monkeypatch):
    class WithExtraField(RouteSegmentDetail):
        road_names: dict[str, str] = {}

    monkeypatch.setattr(route, "RouteSegmentDetail", WithExtraField)

    assert route._undeclared_dict_fields() == ["road_names"]
