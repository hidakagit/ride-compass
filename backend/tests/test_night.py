from app.domain.night import night_materials


def test_night_materials_lit_yes_is_not_no_lit():
    assert night_materials({"lit": "yes"}) == {"no_lit": False, "has_tunnel": False}


def test_night_materials_missing_lit_tag_is_no_lit():
    assert night_materials({}) == {"no_lit": True, "has_tunnel": False}


def test_night_materials_explicit_lit_no_is_no_lit():
    assert night_materials({"lit": "no"}) == {"no_lit": True, "has_tunnel": False}


def test_night_materials_tunnel_yes_sets_has_tunnel():
    assert night_materials({"tunnel": "yes"}) == {"no_lit": True, "has_tunnel": True}


def test_night_materials_lit_and_tunnel_both_set():
    assert night_materials({"lit": "yes", "tunnel": "yes"}) == {"no_lit": False, "has_tunnel": True}


def test_night_materials_none_tags_is_both_none():
    assert night_materials(None) == {"no_lit": None, "has_tunnel": None}
