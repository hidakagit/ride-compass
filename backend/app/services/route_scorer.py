from pathlib import Path

import yaml

from app.domain.route import RouteCandidate
from app.domain.scoring import normalize_min_max

SCORING_CONFIG_PATH = Path(__file__).resolve().parent.parent / "scoring.yaml"


def load_scoring_weights(path: Path = SCORING_CONFIG_PATH) -> dict[str, float]:
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config["scoring"]


class RouteScorer:
    """距離・獲得標高・風・路面の各指標を重み付け合成し、total_scoreを算出する。

    正規化は`score()`に渡された候補集合内でのmin-max（`domain/scoring.py`）で行うため、
    同じ`generate_loops`呼び出し内の候補同士の相対比較としてのみ意味を持つ
    （異なるリクエスト間のtotal_scoreは比較できない）。I/Oは行わない。
    """

    def __init__(self, weights: dict[str, float]):
        self._weights = weights

    def score(self, candidates: list[RouteCandidate], target_distance_km: float) -> list[RouteCandidate]:
        if not candidates:
            return []

        distance_diffs = [abs(c.distance_km - target_distance_km) for c in candidates]
        component_scores = {
            "distance": (
                normalize_min_max(distance_diffs, higher_is_better=False),
                self._weights["distance_weight"],
            ),
            "elevation": (
                normalize_min_max([c.elevation_gain_m for c in candidates], higher_is_better=False),
                self._weights["elevation_weight"],
            ),
            "wind": (
                normalize_min_max([c.wind_score for c in candidates], higher_is_better=False),
                self._weights["wind_weight"],
            ),
            "road": (
                normalize_min_max([c.road_score for c in candidates], higher_is_better=True),
                self._weights["road_weight"],
            ),
        }

        results = []
        for i, candidate in enumerate(candidates):
            # 取得できなかった指標（None）は除外し、残った指標の重みだけで再正規化して合成する
            available = [(scores[i], weight) for scores, weight in component_scores.values() if scores[i] is not None]

            if not available:
                results.append(candidate.model_copy(update={"total_score": None}))
                continue

            weight_sum = sum(weight for _, weight in available)
            total = sum(score * weight for score, weight in available) / weight_sum
            results.append(candidate.model_copy(update={"total_score": round(total, 1)}))

        return results
