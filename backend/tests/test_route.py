import pytest

from app.domain.route import RouteSegmentDetail, aggregate_segments_into_bins


def _segment(
    index: int,
    distance_km: float = 0.1,
    cumulative_distance_km: float | None = None,
    **overrides,
) -> RouteSegmentDetail:
    lat = 35.70 + index * 0.001
    defaults = dict(
        geometry={"type": "LineString", "coordinates": [[139.70 + index * 0.001, lat], [139.70 + (index + 1) * 0.001, lat]]},
        start_latitude=lat,
        start_longitude=139.70 + index * 0.001,
        end_latitude=lat,
        end_longitude=139.70 + (index + 1) * 0.001,
        cumulative_distance_km=cumulative_distance_km if cumulative_distance_km is not None else index * distance_km,
        distance_km=distance_km,
        estimated_arrival_time=f"2026-08-23T00:0{index}:00+09:00",
    )
    defaults.update(overrides)
    return RouteSegmentDetail(**defaults)


def test_aggregate_segments_into_bins_returns_empty_for_empty_input():
    assert aggregate_segments_into_bins([]) == []


def test_aggregate_segments_into_bins_groups_by_cumulative_distance():
    # 0.1km x 6区間、bin_distance_km=0.5 → 1本目=5区間(0.5km)・2本目=1区間(0.1km、
    # 端数でも独立したビンとして残す）。
    segments = [_segment(i, distance_km=0.1) for i in range(6)]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 2
    assert bins[0].distance_km == pytest.approx(0.5)
    assert bins[1].distance_km == pytest.approx(0.1)


def test_aggregate_segments_into_bins_preserves_total_distance():
    segments = [_segment(i, distance_km=0.13) for i in range(23)]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    total_before = sum(s.distance_km for s in segments)
    total_after = sum(b.distance_km for b in bins)
    assert total_after == pytest.approx(total_before, abs=0.01)


def test_aggregate_segments_into_bins_start_end_and_cumulative_come_from_bin_boundaries():
    segments = [
        _segment(0, distance_km=0.2, cumulative_distance_km=0.0),
        _segment(1, distance_km=0.2, cumulative_distance_km=0.2),
        _segment(2, distance_km=0.2, cumulative_distance_km=0.4),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 1
    binned = bins[0]
    assert (binned.start_latitude, binned.start_longitude) == (segments[0].start_latitude, segments[0].start_longitude)
    assert (binned.end_latitude, binned.end_longitude) == (segments[-1].end_latitude, segments[-1].end_longitude)
    assert binned.cumulative_distance_km == segments[0].cumulative_distance_km
    assert binned.estimated_arrival_time == segments[0].estimated_arrival_time


def test_aggregate_segments_into_bins_concatenates_geometry_without_duplicating_boundary_points():
    segments = [_segment(0, distance_km=0.3), _segment(1, distance_km=0.3)]
    # 2区間目の始点座標を1区間目の終点座標と一致させ、境界点の重複除去を検証する。
    segments[1] = segments[1].model_copy(
        update={
            "geometry": {
                "type": "LineString",
                "coordinates": [segments[0].geometry["coordinates"][-1], [139.703, 35.703]],
            }
        }
    )

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 1
    coordinates = bins[0].geometry["coordinates"]
    assert coordinates == [
        segments[0].geometry["coordinates"][0],
        segments[0].geometry["coordinates"][1],
        [139.703, 35.703],
    ]


def test_aggregate_segments_into_bins_averages_difficulty_fields_by_distance():
    segments = [
        _segment(0, distance_km=0.3, gradient_percent=10.0, difficulty=80.0),
        _segment(1, distance_km=0.1, gradient_percent=-6.0, difficulty=20.0),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 1
    # (10*0.3 + -6*0.1) / 0.4 = 6.0
    assert bins[0].gradient_percent == pytest.approx(6.0)
    # (80*0.3 + 20*0.1) / 0.4 = 65.0
    assert bins[0].difficulty == pytest.approx(65.0)


def test_aggregate_segments_into_bins_excludes_none_values_from_averaging():
    segments = [
        _segment(0, distance_km=0.2, gradient_percent=None),
        _segment(1, distance_km=0.2, gradient_percent=8.0),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert bins[0].gradient_percent == pytest.approx(8.0)


def test_aggregate_segments_into_bins_returns_none_when_all_values_in_bin_are_none():
    segments = [_segment(0, distance_km=0.6, gradient_percent=None, difficulty=None)]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert bins[0].gradient_percent is None
    assert bins[0].difficulty is None


def test_aggregate_segments_into_bins_road_surface_good_picks_majority_by_distance():
    segments = [
        _segment(0, distance_km=0.1, road_surface_good=False),
        _segment(1, distance_km=0.35, road_surface_good=True),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert bins[0].road_surface_good is True


def test_aggregate_segments_into_bins_single_edge_larger_than_bin_size_forms_its_own_bin():
    # 実際のRoad Graphエンジンのように、1本のEdgeがbin_distance_kmを超える長さのことがある
    # （東京都心の合成テストグラフ等）。1本ずつ独立したビンになる（分割はしない）。
    segments = [_segment(0, distance_km=10.0), _segment(1, distance_km=10.0)]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 2
    assert bins[0].distance_km == 10.0
    assert bins[1].distance_km == 10.0


# merge_axis_difficulties（改善計画T309・T316フォローアップ: 既存軸の非公開化でKeyError/
# ValidationErrorになり500になっていた実障害の修正箇所）。axis_id→difficultyの汎用dictを
# ビン内でaxis_idごとに距離加重平均する。専用のユニットテストが無かった（"axis_difficulties"が
# test_route.pyに1件も無かった）ため、aggregate_segments_into_bins経由で新規に追加する。


def test_aggregate_segments_into_bins_axis_difficulties_distance_weighted_average():
    segments = [
        _segment(0, distance_km=0.3, axis_difficulties={"wind": 80.0}),
        _segment(1, distance_km=0.1, axis_difficulties={"wind": 20.0}),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 1
    # (80*0.3 + 20*0.1) / 0.4 = 65.0
    assert bins[0].axis_difficulties["wind"] == pytest.approx(65.0)


def test_aggregate_segments_into_bins_axis_difficulties_averages_only_over_segments_that_have_it():
    # 一部の区間にしか無いaxis_idは、それを持つ区間だけで加重平均する
    # （持たない区間を0扱いで巻き込んで薄めてはならない）。
    segments = [
        _segment(0, distance_km=0.2, axis_difficulties={"wind": 100.0}),
        _segment(1, distance_km=0.2, axis_difficulties={}),  # "wind"軸を持たない区間
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    # 0扱いで平均されるなら(100*0.2+0*0.2)/0.4=50.0になってしまうが、
    # 正しくは持っている区間(0.2km)だけで平均され100.0のまま。
    assert bins[0].axis_difficulties["wind"] == pytest.approx(100.0)


def test_aggregate_segments_into_bins_axis_difficulties_omits_axis_absent_from_every_segment():
    # ビン内のどの区間にも無いaxis_idは、結果の辞書にキー自体が現れない
    # （RouteSegmentDetail.axis_difficultiesと同じ「データ無しはキーを持たない」規約）。
    segments = [
        _segment(0, distance_km=0.2, axis_difficulties={"wind": 50.0}),
        _segment(1, distance_km=0.2, axis_difficulties={"wind": 50.0}),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert set(bins[0].axis_difficulties.keys()) == {"wind"}
    assert "elevation" not in bins[0].axis_difficulties


def test_aggregate_segments_into_bins_axis_difficulties_survives_axis_unpublished_mid_route():
    # T316フォローアップの実障害シナリオに近い形: ある軸("elevation")が経路の途中区間の
    # axis_difficultiesから欠落している（軸の非公開化を想定）状態でも、
    # aggregate_segments_into_bins全体が例外を投げずに完了し、他の軸("wind")は正しく
    # 集約されること。
    segments = [
        _segment(0, distance_km=0.2, axis_difficulties={"elevation": 40.0, "wind": 30.0}),
        _segment(1, distance_km=0.2, axis_difficulties={"wind": 60.0}),  # elevation軸が欠落
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 1
    assert bins[0].axis_difficulties["elevation"] == pytest.approx(40.0)
    # (30*0.2 + 60*0.2) / 0.4 = 45.0
    assert bins[0].axis_difficulties["wind"] == pytest.approx(45.0)
