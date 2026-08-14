from app.domain.scoring import normalize_min_max


def test_higher_is_better_maps_max_to_100_and_min_to_0():
    scores = normalize_min_max([10.0, 20.0, 30.0], higher_is_better=True)

    assert scores == [0.0, 50.0, 100.0]


def test_lower_is_better_inverts_the_mapping():
    scores = normalize_min_max([10.0, 20.0, 30.0], higher_is_better=False)

    assert scores == [100.0, 50.0, 0.0]


def test_all_equal_values_get_neutral_score():
    scores = normalize_min_max([5.0, 5.0, 5.0], higher_is_better=True)

    assert scores == [100.0, 100.0, 100.0]


def test_none_values_pass_through_unchanged():
    scores = normalize_min_max([10.0, None, 30.0], higher_is_better=True)

    assert scores == [0.0, None, 100.0]


def test_all_none_returns_all_none():
    scores = normalize_min_max([None, None], higher_is_better=True)

    assert scores == [None, None]
