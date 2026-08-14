from pathlib import Path

import yaml

from app.domain.attributes import ElevationAttribute, SurfaceAttribute
from app.domain.evaluation import EdgeCostResult, RoutePreference, compute_edge_cost
from app.domain.graph import RoadGraph

ROUTE_PREFERENCE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "route_preference.yaml"


def load_route_preference(path: Path = ROUTE_PREFERENCE_CONFIG_PATH) -> RoutePreference:
    """route_preference.yamlから既定のRoute Preference（重み）を読み込む（仕様書27-28章）。

    scoring.yaml/load_scoring_weights（ルート単位のRouteScorer用）と同じパターンだが、
    対象・データ構造が異なる別設定のため、別ファイル・別関数として分離している
    （Phase 4完了時点の引き継ぎ事項を参照）。呼び出し元が`path`を差し替えれば、
    将来複数プロファイル（快適性重視/トレーニング重視等、仕様書27・45章）を
    別ファイルとして追加した場合もコード変更なしで切り替えられる。
    """
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return RoutePreference(**config["route_preference"])


class EvaluationService:
    """Evaluation Engineのオーケストレーション層（仕様書26章）。

    I/Oは行わない。属性の取得自体はPhase 3の`ElevationAttributeService`・
    `GraphService.build_graph_with_surface_tags_for_bbox`が担当し、ここでは
    既に取得済みのRoadGraph・属性からEdge Costを算出するのみ。Route Engineからは
    独立しており、既存のルート探索（RoutingService/RouteGenerator）からは参照されない。
    """

    def __init__(self, preference: RoutePreference | None = None):
        self._preference = preference or load_route_preference()

    def evaluate_graph(
        self,
        graph: RoadGraph,
        elevation_attributes: dict[str, ElevationAttribute],
        surface_attributes: dict[str, SurfaceAttribute],
    ) -> dict[str, EdgeCostResult]:
        return {
            edge_id: compute_edge_cost(
                edge,
                elevation_attributes.get(edge_id),
                surface_attributes.get(edge_id),
                self._preference,
            )
            for edge_id, edge in graph.edges.items()
        }
