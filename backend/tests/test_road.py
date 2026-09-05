from app.domain.road import classify_osm_surface


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
