from app.domain.road import classify_osm_surface, distance_weighted_road_score


def test_distance_weighted_road_score_sums_good_surface_distance():
    pairs = [(4000.0, True), (1000.0, True), (1500.0, False)]

    assert distance_weighted_road_score(pairs) == round(5000.0 / 6500.0 * 100, 1)


def test_distance_weighted_road_score_returns_zero_when_all_bad():
    assert distance_weighted_road_score([(5000.0, False)]) == 0.0


def test_distance_weighted_road_score_returns_none_for_empty_list():
    assert distance_weighted_road_score([]) is None


def test_distance_weighted_road_score_excludes_unknown_from_denominator():
    # 不明（None）は「悪い路面」ではなく「判定不能」なので分母から除外する
    # （classify_osm_surfaceがタグ無しをNoneにするのと同じ正準定義。domain/road.py参照）。
    pairs = [(5000.0, None), (2500.0, True), (2500.0, False)]

    assert distance_weighted_road_score(pairs) == 50.0  # 判定できた5000のうち半分が舗装


def test_distance_weighted_road_score_returns_none_when_all_unknown():
    assert distance_weighted_road_score([(5000.0, None)]) is None


def test_classify_osm_surface_matches_known_good_tags():
    assert classify_osm_surface("asphalt") is True
    assert classify_osm_surface("paving_stones") is True
    # T7で追加: フロントの表示グループで可視化済みなのに評価上「不明」だったタグ
    # （地図の色とルート評価の食い違い解消。domain/road.pyのコメント参照）
    assert classify_osm_surface("chipseal") is True
    assert classify_osm_surface("bricks") is True


def test_classify_osm_surface_matches_known_bad_tags():
    assert classify_osm_surface("gravel") is False
    assert classify_osm_surface("dirt") is False
    # T7で追加（上記good側と同じ経緯）
    assert classify_osm_surface("rock") is False
    assert classify_osm_surface("unhewn_cobblestone") is False


def test_classify_osm_surface_is_case_insensitive():
    assert classify_osm_surface("Asphalt") is True


def test_classify_osm_surface_returns_none_for_missing_or_unknown_tag():
    assert classify_osm_surface(None) is None
    assert classify_osm_surface("some_unknown_surface") is None
