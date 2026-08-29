from pathlib import Path

import yaml

from app.domain.route import RouteCandidate, RouteScoreComponent
from app.domain.scoring import normalize_min_max

SCORING_CONFIG_PATH = Path(__file__).resolve().parent.parent / "scoring.yaml"


def load_scoring_weights(path: Path = SCORING_CONFIG_PATH) -> dict[str, float]:
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config["scoring"]


class RouteScorer:
    """距離の合わせ込みと総合難易度の2指標を重み付け合成し、total_scoreを算出する。

    正規化は`score()`に渡された候補集合内でのmin-max（`domain/scoring.py`）で行うため、
    同じ`generate_loops`呼び出し内の候補同士の相対比較としてのみ意味を持つ
    （異なるリクエスト間のtotal_scoreは比較できない）。I/Oは行わない。

    total_scoreと同時に、軸別の内訳（`RouteCandidate.score_breakdown`）も候補へ付与する
    （「なぜこの点数か」を分解して確認できるようにする。研究インターフェース改善 §10-2）。

    改善計画T401: 従来は距離・獲得標高・風・路面の4指標を個別にハードコード計算していたが、
    獲得標高・風・路面は`overall_difficulty`（軸スタジオの`RoutePreference.weights`で
    既に重み付け合成済みの値）に既に織り込まれており二重管理だった。「候補は軸スタジオで
    決めた尺度で比較されるべき」という方針のもと、distance（目標距離への近さ）と
    difficulty（overall_difficulty、小さいほど高評価）の2指標へ単純化した。
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
            "difficulty": (
                normalize_min_max([c.overall_difficulty for c in candidates], higher_is_better=False),
                self._weights["difficulty_weight"],
            ),
        }

        results = []
        for i, candidate in enumerate(candidates):
            # 取得できなかった指標（None）は除外し、残った指標の重みだけで再正規化して合成する
            available = [(scores[i], weight) for scores, weight in component_scores.values() if scores[i] is not None]
            weight_sum = sum(weight for _, weight in available)

            # 全指標が欠損、または有効な指標の重みがすべて0（重みのリクエスト上書きで起こりうる）
            # の場合は合成不能としてtotal_score=None（composite_difficultyのweight_sum==0ガードと同じ扱い）
            if not available or weight_sum == 0:
                breakdown = self._build_breakdown(component_scores, i, weight_sum=None)
                results.append(candidate.model_copy(update={"total_score": None, "score_breakdown": breakdown}))
                continue

            total = sum(score * weight for score, weight in available) / weight_sum
            breakdown = self._build_breakdown(component_scores, i, weight_sum=weight_sum)
            results.append(
                candidate.model_copy(update={"total_score": round(total, 1), "score_breakdown": breakdown})
            )

        return results

    @staticmethod
    def _build_breakdown(
        component_scores: dict[str, tuple[list[float | None], float]],
        index: int,
        weight_sum: float | None,
    ) -> list[RouteScoreComponent]:
        """total_scoreの内訳（軸別の正規化スコア・重み・寄与点）を組み立てる。

        寄与点はscore×weight÷有効重み和で、有効な指標分を合計するとtotal_scoreに一致する
        （丸め誤差を除く）。weight_sum=Noneは合成不能（total_score=None）を表し、
        寄与点は全てNoneにする（正規化スコアと重みは参考値としてそのまま返す）。
        """
        return [
            RouteScoreComponent(
                axis=axis,
                score=scores[index],
                weight=weight,
                contribution=(
                    round(scores[index] * weight / weight_sum, 1)
                    if scores[index] is not None and weight_sum
                    else None
                ),
            )
            for axis, (scores, weight) in component_scores.items()
        ]
