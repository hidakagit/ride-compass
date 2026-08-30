from app.domain.route import RouteCandidate
from app.services.route_scorer import RouteScorer

GEOMETRY = {"type": "LineString", "coordinates": [[139.7387, 35.7597], [139.75, 35.8]]}

WEIGHTS = {"distance_weight": 0.30, "difficulty_weight": 0.70}


def candidate(id_: str, distance_km: float, overall_difficulty=None) -> RouteCandidate:
    return RouteCandidate(
        id=id_,
        direction_label="北",
        distance_km=distance_km,
        geometry=GEOMETRY,
        overall_difficulty=overall_difficulty,
    )


def test_empty_candidate_list_returns_empty_list():
    scorer = RouteScorer(WEIGHTS)

    assert scorer.score([], target_distance_km=30.0) == []


def test_better_candidate_across_all_metrics_scores_higher():
    good = candidate("good", distance_km=30.0, overall_difficulty=10.0)
    bad = candidate("bad", distance_km=40.0, overall_difficulty=90.0)

    scored = RouteScorer(WEIGHTS).score([good, bad], target_distance_km=30.0)

    scores = {c.id: c.total_score for c in scored}
    assert scores["good"] == 100.0
    assert scores["bad"] == 0.0


def test_missing_metric_is_excluded_and_weights_renormalized():
    # difficultyだけ欠損している候補と、揃っている候補
    with_difficulty = candidate("with-difficulty", distance_km=30.0, overall_difficulty=50.0)
    without_difficulty = candidate("without-difficulty", distance_km=30.0, overall_difficulty=None)

    scored = RouteScorer(WEIGHTS).score([with_difficulty, without_difficulty], target_distance_km=30.0)

    by_id = {c.id: c for c in scored}
    # 距離は2候補とも同値（中立50点、改善計画T463）。difficultyはwith_difficultyのみ存在し、
    # 1候補だけなのでmin=max=中立50点。つまりどちらの候補も全指標が中立50点相当になり、
    # total_scoreは等しくなるはず。
    assert by_id["with-difficulty"].total_score == 50.0
    assert by_id["without-difficulty"].total_score == 50.0


def test_candidates_with_identical_metrics_get_equal_scores():
    a = candidate("a", distance_km=30.0, overall_difficulty=40.0)
    b = candidate("b", distance_km=30.0, overall_difficulty=40.0)

    scored = RouteScorer(WEIGHTS).score([a, b], target_distance_km=30.0)

    # 改善計画T463: normalize_min_maxの同値ケースは中立50点（以前は100点）。
    assert scored[0].total_score == scored[1].total_score == 50.0


def test_score_breakdown_contributions_sum_to_total_score():
    # total_scoreの内訳（軸別の正規化スコア・重み・寄与点）を返す（研究IF改善 §10-2）。
    # 有効な指標の寄与点の合計はtotal_scoreに一致する（丸め誤差±0.2以内）。
    good = candidate("good", distance_km=30.0, overall_difficulty=10.0)
    bad = candidate("bad", distance_km=40.0, overall_difficulty=90.0)

    scored = RouteScorer(WEIGHTS).score([good, bad], target_distance_km=30.0)

    for c in scored:
        assert c.score_breakdown is not None
        # このaxis id集合はフロントの評価軸カタログ（frontend/src/lib/evaluationAxes.ts:
        # SCORING_AXES）が「重みキーから"_weight"を除いた値」として前提にしている
        # （改善計画T25）。ここを変えたらフロント側の対応も必要。
        assert [e.axis for e in c.score_breakdown] == ["distance", "difficulty"]
        assert {e.axis: e.weight for e in c.score_breakdown} == {
            "distance": 0.30,
            "difficulty": 0.70,
        }
        contributions = [e.contribution for e in c.score_breakdown if e.contribution is not None]
        assert abs(sum(contributions) - c.total_score) <= 0.2


def test_score_breakdown_missing_metric_has_none_contribution():
    # 指標が取得できなかった軸はscore/contributionともNoneのまま内訳に含める
    # （「この軸は評価に使われなかった」ことが分かるようにする）。
    a = candidate("a", distance_km=30.0, overall_difficulty=None)
    b = candidate("b", distance_km=32.0, overall_difficulty=None)

    scored = RouteScorer(WEIGHTS).score([a, b], target_distance_km=30.0)

    for c in scored:
        difficulty_entry = next(e for e in c.score_breakdown if e.axis == "difficulty")
        assert difficulty_entry.score is None
        assert difficulty_entry.contribution is None
        assert difficulty_entry.weight == 0.70


def test_all_zero_weights_yield_none_total_score_without_crash():
    # 重みのリクエスト上書き（研究IF改善 §10-1）で全重み0を渡した場合、
    # ZeroDivisionErrorにせず合成不能（total_score=None）として扱う。
    zero_weights = {"distance_weight": 0.0, "difficulty_weight": 0.0}
    a = candidate("a", distance_km=30.0, overall_difficulty=40.0)
    b = candidate("b", distance_km=35.0, overall_difficulty=60.0)

    scored = RouteScorer(zero_weights).score([a, b], target_distance_km=30.0)

    for c in scored:
        assert c.total_score is None
        assert c.score_breakdown is not None
        assert all(e.contribution is None for e in c.score_breakdown)
