import pytest

from app.domain.route import (
    RouteSegmentDetail,
    aggregate_segments_into_bins,
    merge_axis_raw_values,
    merge_material_category_shares,
    merge_material_values,
)


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


def test_aggregate_segments_into_bins_averages_difficulty_by_distance():
    segments = [
        _segment(0, distance_km=0.3, difficulty=80.0),
        _segment(1, distance_km=0.1, difficulty=20.0),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 1
    # (80*0.3 + 20*0.1) / 0.4 = 65.0
    assert bins[0].difficulty == pytest.approx(65.0)


def test_aggregate_segments_into_bins_excludes_none_values_from_averaging():
    segments = [
        _segment(0, distance_km=0.2, difficulty=None),
        _segment(1, distance_km=0.2, difficulty=8.0),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert bins[0].difficulty == pytest.approx(8.0)


def test_aggregate_segments_into_bins_returns_none_when_all_values_in_bin_are_none():
    segments = [_segment(0, distance_km=0.6, difficulty=None)]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert bins[0].difficulty is None


def test_aggregate_segments_into_bins_material_values_distance_weighted_average():
    segments = [
        _segment(0, distance_km=0.3, material_values={"gradient_percent": 10.0}),
        _segment(1, distance_km=0.1, material_values={"gradient_percent": -6.0}),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 1
    # (10*0.3 + -6*0.1) / 0.4 = 6.0
    assert bins[0].material_values["gradient_percent"] == pytest.approx(6.0)


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


# merge_material_values（改善計画T592: RouteCandidate.material_valuesの集約関数、
# merge_axis_difficultiesと同じ距離加重平均の共有実装を使う）。


def test_merge_material_values_distance_weighted_average():
    segments = [
        _segment(0, distance_km=0.3, material_values={"wind_drag_ratio": 8.0}),
        _segment(1, distance_km=0.1, material_values={"wind_drag_ratio": 4.0}),
    ]

    merged = merge_material_values(segments)

    # (8*0.3 + 4*0.1) / 0.4 = 7.0
    assert merged["wind_drag_ratio"] == pytest.approx(7.0)


def test_merge_material_values_omits_material_absent_from_every_segment():
    segments = [
        _segment(0, distance_km=0.2, material_values={"wind_drag_ratio": 5.0}),
        _segment(1, distance_km=0.2, material_values={"wind_drag_ratio": 5.0}),
    ]

    merged = merge_material_values(segments)

    assert set(merged.keys()) == {"wind_drag_ratio"}


# merge_axis_raw_values（折れ点を通す前の生値の集約。merge_axis_difficultiesと同じ
# 距離加重平均の共有実装を使う、docs/tasks/T687.md）。


def test_aggregate_segments_into_bins_carries_every_dict_field():
    """`RouteSegmentDetail`へ辞書フィールドを足したのに`_merge_segment_bin`へ書き足すのを
    忘れると、APIからは「そのフィールドだけ空」に見える（他は正常なので気づきにくい）。
    フィールド一覧をモデルから引いて機械的に検出する——`_merge_segment_bin`は表示用の
    区間を作り直す場所で、足し忘れが型でも例外でも現れない。"""
    dict_fields = [
        name
        for name, field in RouteSegmentDetail.model_fields.items()
        if field.annotation == dict[str, float]
    ]
    assert dict_fields, "辞書フィールドが1つも見つからない（この検査自体が空回りしている）"

    segments = [
        _segment(0, distance_km=0.2, **{name: {"probe": 1.0} for name in dict_fields}),
        _segment(1, distance_km=0.2, **{name: {"probe": 3.0} for name in dict_fields}),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    missing = [name for name in dict_fields if not getattr(bins[0], name)]
    assert not missing, f"_merge_segment_binが引き継いでいないフィールド: {missing}"


def test_axis_raw_values_keep_precision_for_small_scale_axes():
    # 統合レビュー第6回の指摘I-5: 生値の集約が0〜100のdifficulty向けの丸め（小数1桁）を
    # 流用しており、桁の小さい軸で値がまるごと潰れていた。公開軸accidentの単位は
    # 件/(km・年)で、material_catalogの代表点は少ない=0.02／普通=0.1／多い=0.3。
    # 実データの典型値（0.03〜0.15）が「0.0」か「0.1」にしかならず、
    # 0.05未満はすべて0.0＝事故ゼロの道と区別できなくなっていた。
    segments = [
        _segment(0, distance_km=0.3, axis_raw_values={"accident": 0.04}),
        _segment(1, distance_km=0.1, axis_raw_values={"accident": 0.04}),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert bins[0].axis_raw_values["accident"] == pytest.approx(0.04)


def test_axis_raw_values_round_to_significant_digits_not_fixed_decimals():
    # 丸めは値のスケールに依存しない（有効数字）。桁の大きい軸でも小さい軸でも
    # 同じ相対精度が残る。
    small = aggregate_segments_into_bins(
        [_segment(0, distance_km=0.4, axis_raw_values={"a": 0.0123456})], bin_distance_km=0.5
    )
    large = aggregate_segments_into_bins(
        [_segment(0, distance_km=0.4, axis_raw_values={"a": 1234.5678})], bin_distance_km=0.5
    )

    assert small[0].axis_raw_values["a"] == pytest.approx(0.01235)
    assert large[0].axis_raw_values["a"] == pytest.approx(1235.0)


def test_axis_difficulties_still_round_to_one_decimal():
    # difficultyは0〜100の相対評価で、小数1桁より細かくしても判断は変わらない。
    # 生値側の丸めを変えてもこちらは据え置き。
    segments = [_segment(0, distance_km=0.4, axis_difficulties={"wind": 12.3456})]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert bins[0].axis_difficulties["wind"] == pytest.approx(12.3)


def test_aggregate_segments_into_bins_carries_axis_raw_values():
    # ビン化は表示用の区間を作り直すため、集約する値を1つ足し忘れるとAPIからは
    # 「そのフィールドだけ空」に見える（本番で生値が全区間空になった実障害の回帰、
    # docs/tasks/T687.md）。axis_difficultiesが出ているのにaxis_raw_valuesだけ空、
    # という形で表面化する。
    segments = [
        _segment(0, distance_km=0.3, axis_difficulties={"stop_density": 80.0}, axis_raw_values={"stop_density": 4.0}),
        _segment(1, distance_km=0.1, axis_difficulties={"stop_density": 20.0}, axis_raw_values={"stop_density": 0.0}),
    ]

    bins = aggregate_segments_into_bins(segments, bin_distance_km=0.5)

    assert len(bins) == 1
    # (4.0*0.3 + 0.0*0.1) / 0.4 = 3.0
    assert bins[0].axis_raw_values["stop_density"] == pytest.approx(3.0)


def test_merge_axis_raw_values_distance_weighted_average():
    segments = [
        _segment(0, distance_km=30.0, axis_raw_values={"stop_density": 0.5}),
        _segment(1, distance_km=10.0, axis_raw_values={"stop_density": 2.5}),
    ]

    merged = merge_axis_raw_values(segments)

    # (0.5*30 + 2.5*10) / 40 = 1.0回/km。これへ距離を掛けた「約40回」が利用者へ出る値。
    assert merged["stop_density"] == pytest.approx(1.0)


def test_merge_axis_raw_values_omits_axis_absent_from_every_segment():
    # 単位が定まらない軸は生値を持たない。キー自体が現れないことで、frontendは
    # 「出せる軸だけ出す」判定を値の有無だけで行える。
    segments = [
        _segment(0, distance_km=1.0, axis_raw_values={"stop_density": 1.0}),
        _segment(1, distance_km=1.0, axis_raw_values={"stop_density": 1.0}),
    ]

    merged = merge_axis_raw_values(segments)

    assert set(merged.keys()) == {"stop_density"}


# merge_material_category_shares（categorical材料の内訳。数値材料の距離加重平均に対応する
# 「値ごとの延長割合」、docs/tasks/T718.md）。


def test_merge_material_category_shares_is_distance_weighted():
    segments = [
        _segment(0, distance_km=6.0, material_categories={"highway": "residential"}),
        _segment(1, distance_km=3.0, material_categories={"highway": "secondary"}),
        _segment(2, distance_km=1.0, material_categories={"highway": "residential"}),
    ]

    shares = merge_material_category_shares(segments)

    assert shares["highway"] == {"residential": 0.7, "secondary": 0.3}


def test_merge_material_category_shares_orders_by_share_descending():
    # フロントは並べ替えを持たず先頭を「最も延長の長い値」として出す。
    segments = [
        _segment(0, distance_km=1.0, material_categories={"highway": "primary"}),
        _segment(1, distance_km=5.0, material_categories={"highway": "residential"}),
    ]

    shares = merge_material_category_shares(segments)

    assert list(shares["highway"]) == ["residential", "primary"]


def test_merge_material_category_shares_excludes_segments_without_a_value():
    # 値の無い区間は分母にも入れない（「観測できた範囲でどの値が多いか」を表す）。
    segments = [
        _segment(0, distance_km=3.0, material_categories={"highway": "residential"}),
        _segment(1, distance_km=7.0, material_categories={}),
    ]

    shares = merge_material_category_shares(segments)

    assert shares["highway"] == {"residential": 1.0}


def test_merge_material_category_shares_omits_material_absent_from_every_segment():
    segments = [_segment(0, distance_km=1.0, material_categories={})]

    assert merge_material_category_shares(segments) == {}
