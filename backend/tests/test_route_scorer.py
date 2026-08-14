from app.domain.route import RouteCandidate
from app.services.route_scorer import RouteScorer

GEOMETRY = {"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]}

WEIGHTS = {"distance_weight": 0.30, "elevation_weight": 0.15, "wind_weight": 0.30, "road_weight": 0.25}


def candidate(id_: str, distance_km: float, elevation_gain_m=None, wind_score=None, road_score=None) -> RouteCandidate:
    return RouteCandidate(
        id=id_,
        direction_label="北",
        distance_km=distance_km,
        geometry=GEOMETRY,
        elevation_gain_m=elevation_gain_m,
        wind_score=wind_score,
        road_score=road_score,
    )


def test_empty_candidate_list_returns_empty_list():
    scorer = RouteScorer(WEIGHTS)

    assert scorer.score([], target_distance_km=30.0) == []


def test_better_candidate_across_all_metrics_scores_higher():
    good = candidate("good", distance_km=30.0, elevation_gain_m=50.0, wind_score=-1.0, road_score=90.0)
    bad = candidate("bad", distance_km=40.0, elevation_gain_m=500.0, wind_score=3.0, road_score=10.0)

    scored = RouteScorer(WEIGHTS).score([good, bad], target_distance_km=30.0)

    scores = {c.id: c.total_score for c in scored}
    assert scores["good"] == 100.0
    assert scores["bad"] == 0.0


def test_missing_metric_is_excluded_and_weights_renormalized():
    # windだけ欠損している候補と、全指標揃っている候補
    with_wind = candidate("with-wind", distance_km=30.0, elevation_gain_m=100.0, wind_score=1.0, road_score=50.0)
    without_wind = candidate("without-wind", distance_km=30.0, elevation_gain_m=100.0, wind_score=None, road_score=50.0)

    scored = RouteScorer(WEIGHTS).score([with_wind, without_wind], target_distance_km=30.0)

    by_id = {c.id: c for c in scored}
    # 距離・獲得標高・路面は2候補とも同値（中立100点）。windはwith_windのみ存在し、1候補だけなのでmin=max=中立100点。
    # つまりどちらの候補も全指標が中立100点相当になり、total_scoreは等しくなるはず。
    assert by_id["with-wind"].total_score == 100.0
    assert by_id["without-wind"].total_score == 100.0


def test_candidates_with_identical_metrics_get_equal_scores():
    a = candidate("a", distance_km=30.0, elevation_gain_m=100.0, wind_score=0.5, road_score=80.0)
    b = candidate("b", distance_km=30.0, elevation_gain_m=100.0, wind_score=0.5, road_score=80.0)

    scored = RouteScorer(WEIGHTS).score([a, b], target_distance_km=30.0)

    assert scored[0].total_score == scored[1].total_score == 100.0
