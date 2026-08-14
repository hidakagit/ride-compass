"""Evaluation Engine（仕様書26-33章）。

Road Attribute（domain/attributes.py）とRoute PreferenceからEdge Costを算出する。
Route Engineから独立させ、Route Engine自身は「勾配がきつい」「路面が悪い」といった
評価の中身を一切知らない設計を目指す（仕様書33章）。

Score（難易度換算）は既存の`domain/difficulty.py`（Step9で導入、地図の難易度レイヤー用。
0-100、値が大きいほど走りにくい絶対基準）をそのまま再利用する。ルート単位の可視化と
Edge単位のEvaluation Engineが同じ「難易度」の意味・スケールを共有することで、新しい
正規化方式を発明せず、評価基準の食い違いも避ける。
"""

from pydantic import BaseModel

from app.domain.attributes import ElevationAttribute, SurfaceAttribute
from app.domain.difficulty import composite_difficulty, gradient_difficulty, road_difficulty
from app.domain.graph import DirectedEdge
from app.domain.road import classify_osm_surface

# 自転車で法的・実質的に通行できない道路種別（Hard Constraint、仕様書29章）。
# Costを上げるのではなく探索対象から除外する。将来、access/bicycleタグ等の
# より精密な判定に拡張する余地を残すため、ここではOSMのhighway分類のみを対象にする。
DISALLOWED_HIGHWAY_TYPES = {"motorway", "motorway_link", "trunk", "trunk_link"}


class RoutePreference(BaseModel):
    """Evaluation Engineが使う重み（仕様書27章）。

    現時点ではRoad Attributeとして実装済みの標高・路面のみを対象とする
    （交通・自転車インフラ・信号は未実装、Phase 3参照）。設定ファイルからの外部化は
    Phase 5で行う方針（仕様書40章のPhase分割）のため、ここではデフォルト値を持つ
    Pydanticモデルとしてのみ用意し、YAML等の読み込み機構はまだ追加しない。
    """

    elevation_weight: float = 0.5
    road_weight: float = 0.5


class EdgeCostResult(BaseModel):
    """Edge Costの算出結果。

    difficultyは0-100（大きいほど走りにくい、domain/difficulty.pyと同じ絶対基準）。
    costは距離ベース（メートル相当、小さいほど良い＝Route Engineが最短経路探索に
    そのまま使える単位）。allowed=FalseはHard Constraintによる除外を表し、この場合
    cost/difficultyはNoneになる。

    Road Graphへ恒久保存しない（仕様書32章）。このモデルは呼び出しごとの計算結果を
    表すだけであり、Route Preferenceが変われば同じEdgeでも異なる結果になりうる。
    """

    edge_id: str
    cost: float | None
    difficulty: float | None
    allowed: bool


def is_edge_allowed(edge: DirectedEdge) -> bool:
    """Hard Constraint（仕様書29章）。highwayタグが自転車で通行できない種別かどうかを判定する。

    highwayタグが無い（不明）場合は除外しない。判断材料が無いEdgeまで一律除外すると
    経路探索対象が過度に狭まるため、不明な場合は許可しSoft Constraint側の評価に委ねる。
    """
    if edge.highway is None:
        return True
    return edge.highway not in DISALLOWED_HIGHWAY_TYPES


def compute_edge_cost(
    edge: DirectedEdge,
    elevation_attribute: ElevationAttribute | None,
    surface_attribute: SurfaceAttribute | None,
    preference: RoutePreference,
) -> EdgeCostResult:
    """RouteEngineが利用できるEdge Costを算出する（仕様書31章）。

    具体的な計算式（difficultyを距離への乗算ペナルティとして反映する方式）は今回の
    初期実装であり、固定ではない。加重和・ペナルティ方式などを比較検討できるよう、
    この関数だけを差し替えれば済む独立した責務にしてある（仕様書31章）。
    """
    if not is_edge_allowed(edge):
        return EdgeCostResult(edge_id=edge.edge_id, cost=None, difficulty=None, allowed=False)

    gradient_percent = elevation_attribute.average_grade if elevation_attribute else None
    is_good_surface = classify_osm_surface(surface_attribute.surface_type) if surface_attribute else None

    difficulty = composite_difficulty(
        [
            (gradient_difficulty(gradient_percent), preference.elevation_weight),
            (road_difficulty(is_good_surface), preference.road_weight),
        ]
    )

    # difficulty(0-100)を距離に対する乗算ペナルティへ変換する。
    # 0=最も走りやすい(係数1.0=距離そのまま)、100=最も走りにくい(係数2.0=距離の2倍のコスト)。
    penalty_multiplier = 1.0 + (difficulty / 100) if difficulty is not None else 1.0
    cost = edge.distance_m * penalty_multiplier

    return EdgeCostResult(edge_id=edge.edge_id, cost=round(cost, 1), difficulty=difficulty, allowed=True)
