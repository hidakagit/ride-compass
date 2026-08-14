from app.domain.road import classify_osm_surface, is_good_surface, paved_percent, surface_id_at_index


def test_paved_percent_sums_good_surface_categories():
    summary = [
        {"value": 1, "distance": 4000.0, "amount": 60.0},  # Paved
        {"value": 3, "distance": 1000.0, "amount": 15.0},  # Asphalt
        {"value": 10, "distance": 1500.0, "amount": 25.0},  # Gravel（対象外）
    ]

    assert paved_percent(summary) == 75.0


def test_paved_percent_returns_zero_when_all_unpaved():
    summary = [{"value": 11, "distance": 5000.0, "amount": 100.0}]  # Dirt

    assert paved_percent(summary) == 0.0


def test_paved_percent_returns_none_for_empty_list():
    assert paved_percent([]) is None


def test_paved_percent_returns_none_for_none_input():
    assert paved_percent(None) is None


def test_paved_percent_excludes_unknown_surface_from_denominator():
    # 不明（ID 0）は「悪い路面」ではなく「判定不能」なので分母から除外する
    # （classify_osm_surfaceがタグ無しをNoneにするのと同じ正準定義。domain/road.py参照）。
    summary = [
        {"value": 0, "distance": 5000.0, "amount": 50.0},  # Unknown（分母から除外）
        {"value": 1, "distance": 2500.0, "amount": 25.0},  # Paved
        {"value": 10, "distance": 2500.0, "amount": 25.0},  # Gravel
    ]

    assert paved_percent(summary) == 50.0  # 判定できた50%のうち半分が舗装


def test_paved_percent_returns_none_when_all_unknown():
    summary = [{"value": 0, "distance": 5000.0, "amount": 100.0}]

    assert paved_percent(summary) is None


def test_surface_id_at_index_finds_containing_range():
    values = [[0, 4, 1], [5, 9, 10]]

    assert surface_id_at_index(0, values) == 1
    assert surface_id_at_index(4, values) == 1
    assert surface_id_at_index(5, values) == 10
    assert surface_id_at_index(9, values) == 10


def test_surface_id_at_index_returns_none_when_no_data_or_out_of_range():
    assert surface_id_at_index(0, None) is None
    assert surface_id_at_index(20, [[0, 4, 1]]) is None


def test_is_good_surface_matches_good_surface_ids():
    assert is_good_surface(1) is True  # Paved
    assert is_good_surface(11) is False  # Dirt
    assert is_good_surface(None) is None


def test_is_good_surface_treats_unknown_id_as_none():
    # ID 0（Unknown）はFalse（悪い）ではなくNone（判定不能）。OSMタグ語彙の
    # classify_osm_surfaceが未知タグにNoneを返すのと同じ扱い（正準定義の統一）。
    assert is_good_surface(0) is None


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
