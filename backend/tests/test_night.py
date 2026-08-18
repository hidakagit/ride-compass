from app.domain.night import night_difficulty


def test_night_difficulty_lit_road_without_tunnel_is_no_lit_score_only():
    assert night_difficulty({"lit": "yes"}) == 0.0


def test_night_difficulty_no_lit_tag_is_penalized():
    assert night_difficulty({}) == 50.0


def test_night_difficulty_explicit_lit_no_is_penalized_same_as_absent():
    assert night_difficulty({"lit": "no"}) == 50.0


def test_night_difficulty_tunnel_adds_on_top_of_no_lit():
    assert night_difficulty({"tunnel": "yes"}) == 100.0


def test_night_difficulty_lit_and_tunnel_is_tunnel_score_only():
    assert night_difficulty({"lit": "yes", "tunnel": "yes"}) == 50.0


def test_night_difficulty_none_tags_passthrough():
    assert night_difficulty(None) is None
